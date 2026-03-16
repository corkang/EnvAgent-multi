"""
AST-based Import Parser Tool for EnvAgent

This tool analyzes Python source code to extract import statements and identify
external package dependencies.

Usage in agent:
    imports = ast_import_parser(repository_path="/workspace")
    # Returns: {"numpy": ["src/main.py:5", "tests/test.py:3"], ...}
"""

import ast
import sys
from pathlib import Path
from typing import Dict, List, Set
from collections import defaultdict

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class ImportLocation(BaseModel):
    """Location of an import statement"""
    file_path: str
    line_number: int
    import_name: str
    module_name: str  # What was actually imported


class ImportAnalysisResult(BaseModel):
    """Result of import analysis"""
    external_dependencies: Dict[str, List[str]] = Field(
        description="Mapping of package names to list of locations (file:line)"
    )
    total_imports: int = Field(description="Total number of import statements found")
    external_count: int = Field(description="Number of external dependencies")
    stdlib_count: int = Field(description="Number of stdlib imports (filtered out)")
    local_count: int = Field(description="Number of local imports (filtered out)")


class ASTImportParserTool:
    """
    Tool that parses Python files using AST to extract import dependencies.

    Filters out:
    - Standard library modules
    - Local/relative imports from the repository itself

    Returns only external PyPI dependencies.
    """

    def __init__(self):
        self.stdlib_modules = set(sys.stdlib_module_names)

        # Common package name mappings (import name -> PyPI package name)
        self.known_mappings = {
            'cv2': 'opencv-python',
            'PIL': 'Pillow',
            'sklearn': 'scikit-learn',
            'yaml': 'PyYAML',
            'bs4': 'beautifulsoup4',
            'dateutil': 'python-dateutil',
        }

    def parse_imports_from_file(self, file_path: Path) -> List[ImportLocation]:
        """Parse a single Python file and extract imports"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                source = f.read()

            tree = ast.parse(source, filename=str(file_path))
            imports = []

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(ImportLocation(
                            file_path=str(file_path),
                            line_number=node.lineno,
                            import_name=alias.name.split('.')[0],  # Top-level package
                            module_name=alias.name
                        ))

                elif isinstance(node, ast.ImportFrom):
                    if node.module:  # Skip "from . import x"
                        imports.append(ImportLocation(
                            file_path=str(file_path),
                            line_number=node.lineno,
                            import_name=node.module.split('.')[0],  # Top-level package
                            module_name=node.module
                        ))

            return imports

        except (SyntaxError, UnicodeDecodeError) as e:
            # Skip files that can't be parsed
            return []

    def is_local_import(self, import_name: str, repo_root: Path) -> bool:
        """Check if an import is from a local module in the repository"""
        # Check if there's a matching .py file or package directory
        potential_paths = [
            repo_root / f"{import_name}.py",
            repo_root / import_name / "__init__.py",
            repo_root / "src" / f"{import_name}.py",
            repo_root / "src" / import_name / "__init__.py",
        ]
        return any(p.exists() for p in potential_paths)

    def analyze_repository(self, repository_path: str) -> ImportAnalysisResult:
        """
        Analyze all Python files in a repository and extract external dependencies.

        Args:
            repository_path: Path to the repository root

        Returns:
            ImportAnalysisResult with external dependencies mapping
        """
        repo_root = Path(repository_path)

        # Find all Python files
        py_files = list(repo_root.rglob("*.py"))

        # Collect all imports
        all_imports = []
        for py_file in py_files:
            # Skip virtual environments and build artifacts
            if any(part in py_file.parts for part in ['.venv', 'venv', '__pycache__', '.tox', 'build', 'dist']):
                continue

            imports = self.parse_imports_from_file(py_file)
            all_imports.extend(imports)

        # Categorize imports
        external_deps = defaultdict(list)
        stdlib_count = 0
        local_count = 0

        for imp in all_imports:
            import_name = imp.import_name
            location = f"{imp.file_path}:{imp.line_number}"

            # Filter standard library
            if import_name in self.stdlib_modules:
                stdlib_count += 1
                continue

            # Filter local imports
            if self.is_local_import(import_name, repo_root):
                local_count += 1
                continue

            # Map to PyPI package name if known
            package_name = self.known_mappings.get(import_name, import_name)

            external_deps[package_name].append(location)

        return ImportAnalysisResult(
            external_dependencies=dict(external_deps),
            total_imports=len(all_imports),
            external_count=len(external_deps),
            stdlib_count=stdlib_count,
            local_count=local_count
        )

    def as_langchain_tool(self) -> StructuredTool:
        """Convert to LangChain tool for agent use"""
        def analyze(
            repository_path: str = "."
        ) -> str:
            """
            Analyze Python files in the repository to identify external package dependencies.
            Returns a formatted list of packages and where they are used.
            """
            result = self.analyze_repository(repository_path)

            if result.external_count == 0:
                return "No external dependencies found."

            # Format output for LLM
            output = [
                f"Found {result.external_count} external dependencies:",
                ""
            ]

            for package, locations in sorted(result.external_dependencies.items()):
                # Show first 3 locations for each package
                locations_str = ", ".join(locations[:3])
                if len(locations) > 3:
                    locations_str += f" (and {len(locations) - 3} more)"
                output.append(f"  - {package}: used in {locations_str}")

            output.append("")
            output.append(f"Total: {result.total_imports} imports "
                         f"({result.external_count} external, "
                         f"{result.stdlib_count} stdlib, "
                         f"{result.local_count} local)")

            return "\n".join(output)

        return StructuredTool.from_function(
            func=analyze,
            name="analyze_imports",
            description=(
                "Analyze all Python source files in the repository to identify external package dependencies. "
                "This helps determine what packages need to be installed via pip. "
                "Returns a list of external packages and where they are used in the codebase."
            )
        )


# Example usage
if __name__ == "__main__":
    parser = ASTImportParserTool()
    result = parser.analyze_repository(".")

    print(f"External dependencies: {result.external_count}")
    for pkg, locs in result.external_dependencies.items():
        print(f"  {pkg}: {len(locs)} uses")
