"""
API Pattern Analyzer Tool for EnvAgent

This tool extracts API usage patterns from Python source code to help LLMs
infer appropriate package versions.

Key idea: By analyzing HOW a package is used (which functions, classes, methods),
the LLM can determine compatible version ranges based on API changes/deprecations.

Example:
    If code uses `jinja2.Markup` class, LLM knows this class was removed in 3.1.0,
    so the code requires jinja2 < 3.1.0
"""

import ast
from pathlib import Path
from typing import Dict, List, Set, Optional
from dataclasses import dataclass
from collections import defaultdict

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


@dataclass
class APIUsage:
    """Record of how a package is used"""
    package: str
    api_element: str  # e.g., "Markup", "Environment.from_string", "select_autoescape"
    usage_type: str  # "class", "function", "attribute", "method"
    file_path: str
    line_number: int
    code_snippet: str  # Short snippet showing usage


class APIAnalysisResult(BaseModel):
    """Result of API pattern analysis"""
    package_apis: Dict[str, List[str]] = Field(
        description="Mapping of package names to list of API elements used"
    )
    detailed_usages: List[Dict] = Field(
        description="Detailed usage information for version inference"
    )


class APIPatternAnalyzerTool:
    """
    Tool that analyzes HOW packages are used in the code.

    This goes beyond just knowing "the code imports numpy" - it identifies
    WHICH numpy functions/classes are called, which helps determine version constraints.

    Example insights:
    - numpy.char.chararray → deprecated in 1.20.0
    - pandas.DataFrame.append → removed in 2.0.0
    - sklearn.cross_validation → moved to model_selection in 0.18.0
    """

    def __init__(self):
        # We'll track these types of API usage
        self.api_types = {
            'class_instantiation': [],
            'function_call': [],
            'attribute_access': [],
            'method_call': []
        }

    def extract_api_calls_from_file(self, file_path: Path, target_packages: Set[str]) -> List[APIUsage]:
        """
        Extract API usage patterns from a single Python file.

        Args:
            file_path: Path to Python file
            target_packages: Set of package names to analyze

        Returns:
            List of APIUsage objects
        """
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                source = f.read()
                source_lines = source.splitlines()

            tree = ast.parse(source, filename=str(file_path))
            usages = []

            # Track imported names and their original packages
            import_map = {}  # local_name -> (package, original_name)

            # First pass: build import map
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        pkg_name = alias.name.split('.')[0]
                        if pkg_name in target_packages:
                            local_name = alias.asname if alias.asname else alias.name
                            import_map[local_name] = (pkg_name, alias.name)

                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        pkg_name = node.module.split('.')[0]
                        if pkg_name in target_packages:
                            for alias in node.names:
                                local_name = alias.asname if alias.asname else alias.name
                                import_map[local_name] = (pkg_name, f"{node.module}.{alias.name}")

            # Second pass: find API usage
            for node in ast.walk(tree):
                # Class instantiation: MyClass()
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        name = node.func.id
                        if name in import_map:
                            pkg, full_name = import_map[name]
                            line_num = node.lineno
                            snippet = source_lines[line_num - 1].strip() if line_num <= len(source_lines) else ""

                            usages.append(APIUsage(
                                package=pkg,
                                api_element=full_name,
                                usage_type="class" if name[0].isupper() else "function",
                                file_path=str(file_path),
                                line_number=line_num,
                                code_snippet=snippet[:100]  # Limit snippet length
                            ))

                    # Method call: obj.method()
                    elif isinstance(node.func, ast.Attribute):
                        if isinstance(node.func.value, ast.Name):
                            obj_name = node.func.value.id
                            method_name = node.func.attr
                            if obj_name in import_map:
                                pkg, full_name = import_map[obj_name]
                                line_num = node.lineno
                                snippet = source_lines[line_num - 1].strip() if line_num <= len(source_lines) else ""

                                usages.append(APIUsage(
                                    package=pkg,
                                    api_element=f"{full_name}.{method_name}",
                                    usage_type="method",
                                    file_path=str(file_path),
                                    line_number=line_num,
                                    code_snippet=snippet[:100]
                                ))

                # Attribute access: pkg.attribute
                elif isinstance(node, ast.Attribute):
                    if isinstance(node.value, ast.Name):
                        obj_name = node.value.id
                        attr_name = node.attr
                        if obj_name in import_map:
                            pkg, full_name = import_map[obj_name]
                            line_num = getattr(node, 'lineno', 0)
                            snippet = source_lines[line_num - 1].strip() if line_num <= len(source_lines) else ""

                            usages.append(APIUsage(
                                package=pkg,
                                api_element=f"{full_name}.{attr_name}",
                                usage_type="attribute",
                                file_path=str(file_path),
                                line_number=line_num,
                                code_snippet=snippet[:100]
                            ))

            return usages

        except (SyntaxError, UnicodeDecodeError):
            return []

    def analyze_repository(
        self,
        repository_path: str,
        target_packages: Optional[List[str]] = None
    ) -> APIAnalysisResult:
        """
        Analyze API usage patterns for specified packages in the repository.

        Args:
            repository_path: Path to repository root
            target_packages: List of package names to analyze (if None, analyze all)

        Returns:
            APIAnalysisResult with API usage patterns
        """
        repo_root = Path(repository_path)

        # Find all Python files
        py_files = list(repo_root.rglob("*.py"))

        # If no target packages specified, we can't analyze (need import context)
        if target_packages is None:
            return APIAnalysisResult(package_apis={}, detailed_usages=[])

        target_packages_set = set(target_packages)

        # Collect all API usages
        all_usages = []
        for py_file in py_files:
            # Skip virtual environments and build artifacts
            if any(part in py_file.parts for part in ['.venv', 'venv', '__pycache__', '.tox', 'build', 'dist']):
                continue

            usages = self.extract_api_calls_from_file(py_file, target_packages_set)
            all_usages.extend(usages)

        # Aggregate by package
        package_apis = defaultdict(list)
        detailed_usages = []

        for usage in all_usages:
            api_elem = usage.api_element
            if api_elem not in package_apis[usage.package]:
                package_apis[usage.package].append(api_elem)

            detailed_usages.append({
                "package": usage.package,
                "api": usage.api_element,
                "type": usage.usage_type,
                "location": f"{usage.file_path}:{usage.line_number}",
                "snippet": usage.code_snippet
            })

        return APIAnalysisResult(
            package_apis=dict(package_apis),
            detailed_usages=detailed_usages
        )

    def as_langchain_tool(self) -> StructuredTool:
        """Convert to LangChain tool for agent use"""
        def analyze(
            packages: str,
            repository_path: str = "."
        ) -> str:
            """
            Analyze HOW specific packages are used in the code to infer version constraints.
            This tool extracts which functions, classes, and methods from each package are called,
            which can help determine compatible versions based on API changes.

            Example: If code uses pandas.DataFrame.append, we know this was removed in pandas 2.0,
            so the code likely needs pandas < 2.0.
            """
            package_list = [p.strip() for p in packages.split(',') if p.strip()]

            if not package_list:
                return "Error: No packages specified. Provide comma-separated package names."

            result = self.analyze_repository(repository_path, package_list)

            if not result.package_apis:
                return f"No API usage found for packages: {', '.join(package_list)}"

            # Format output for LLM
            output = [
                f"API usage patterns for version inference:",
                ""
            ]

            for package, apis in sorted(result.package_apis.items()):
                output.append(f"📦 {package}:")
                # Group by API type
                for api in sorted(apis)[:10]:  # Limit to first 10 APIs per package
                    # Find example usage
                    example = next(
                        (u for u in result.detailed_usages if u['package'] == package and u['api'] == api),
                        None
                    )
                    if example:
                        output.append(f"  - {api} ({example['type']})")
                        output.append(f"    Example: {example['snippet']}")

                if len(apis) > 10:
                    output.append(f"  ... and {len(apis) - 10} more APIs")
                output.append("")

            output.append("💡 Use this information to infer appropriate version constraints.")
            output.append("For example, if deprecated APIs are used, the package likely needs an older version.")

            return "\n".join(output)

        return StructuredTool.from_function(
            func=analyze,
            name="analyze_api_patterns",
            description=(
                "Analyze HOW specific Python packages are used in the code. "
                "Extracts which functions, classes, and methods are called to help infer compatible versions. "
                "Useful for determining version constraints based on API changes, deprecations, or removals. "
                "Input: comma-separated package names (e.g., 'numpy,pandas,jinja2')"
            )
        )


# Example usage
if __name__ == "__main__":
    analyzer = APIPatternAnalyzerTool()
    result = analyzer.analyze_repository(".", target_packages=["numpy", "pandas"])

    for pkg, apis in result.package_apis.items():
        print(f"\n{pkg}:")
        for api in apis[:5]:
            print(f"  - {api}")
