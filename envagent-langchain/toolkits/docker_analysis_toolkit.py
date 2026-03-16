"""
Docker-based Analysis Toolkit for EnvAgent

This toolkit wraps static analysis logic as bash commands that execute
inside the Docker container, solving the host/container execution mismatch.

Key insight: Instead of running Python code on the host (wrong environment),
we send Python scripts as bash commands to execute inside Docker (correct environment).
"""

import sys
from pathlib import Path
from typing import List

# Add EnvBench to path
ENVBENCH_PATH = Path(__file__).parents[2] / "EnvBench"
if str(ENVBENCH_PATH) not in sys.path:
    sys.path.insert(0, str(ENVBENCH_PATH))

from langchain_core.tools import BaseTool, StructuredTool
from inference.src.toolkits.bash_terminal import BashTerminalToolkit


class DockerAnalysisToolkit(BashTerminalToolkit):
    """
    Enhanced Bash Toolkit with static analysis capabilities.

    Difference from baseline BashTerminalToolkit:
    - Adds 3 analysis tools (environment, imports, API patterns)
    - Tools execute as Python scripts INSIDE Docker (not on host)
    - Uses bash_executor for all operations

    Research contribution:
    - AST-based dependency extraction
    - API pattern analysis for version inference
    - Environment-aware setup
    """

    class Config:
        arbitrary_types_allowed = True
        extra = 'allow'

    def get_tools(self, *args, **kwargs) -> List[BaseTool]:
        """Get all tools including base bash + our analysis tools"""
        base_tools = super().get_tools(*args, **kwargs)

        # Add our Docker-executed analysis tools
        analysis_tools = [
            self._create_environment_analyzer(),
            self._create_import_analyzer(),
            self._create_api_analyzer(),
        ]

        return base_tools + analysis_tools

    def _create_environment_analyzer(self) -> StructuredTool:
        """
        Tool to analyze environment inside Docker container.
        Executes Python script via bash_executor.
        """
        async def analyze_environment() -> str:
            """
            Analyze the current system environment to understand OS, packages, and tools.
            Returns comprehensive environment information for cross-platform setup decisions.
            """
            # Python script that will run INSIDE Docker
            script = """python -c '
import platform
import sys
import os
import subprocess
import json

def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        return result.stdout.strip()
    except:
        return ""

# OS Information
os_info = {
    "system": platform.system(),
    "release": platform.release(),
    "architecture": platform.machine(),
}

# Python Information
python_info = {
    "version": platform.python_version(),
    "executable": sys.executable,
}

# Package managers
pkg_managers = []
for pm in ["pip", "pip3", "conda", "poetry"]:
    if run_cmd(f"which {pm}"):
        pkg_managers.append(pm)

# Installed packages (first 50)
installed = run_cmd("pip list 2>/dev/null | head -50")

# Output
print("=== ENVIRONMENT ANALYSIS ===")
print(f"OS: {os_info[\"system\"]} {os_info[\"release\"]} ({os_info[\"architecture\"]})")
print(f"Python: {python_info[\"version\"]} at {python_info[\"executable\"]}")
print(f"Package Managers: {\", \".join(pkg_managers)}")
print(f"Working Directory: {os.getcwd()}")
print()
print("Installed Packages (first 50):")
print(installed)
'"""

            # Execute via bash_executor (runs in Docker)
            result = (await self._execute_bash_command(script))[0]
            return result

        return StructuredTool.from_function(
            coroutine=analyze_environment,
            name="analyze_environment",
            description="Analyze the current system environment (OS, Python version, installed packages, package managers). Use this FIRST to understand the target platform."
        )

    def _create_import_analyzer(self) -> StructuredTool:
        """
        Tool to analyze Python imports using AST.
        Executes inside Docker to analyze the correct repository.
        """
        async def analyze_imports(repository_path: str = ".") -> str:
            """
            Analyze Python files to extract all external package dependencies using AST.
            This automatically discovers required packages without reading requirements files.

            Args:
                repository_path: Path to analyze (default: current directory)
            """
            # Python script for AST-based import analysis
            script = f"""python -c '
import ast
import sys
from pathlib import Path
from collections import defaultdict

STDLIB_MODULES = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else {{
    "abc", "argparse", "ast", "asyncio", "base64", "collections", "copy", "csv",
    "datetime", "decimal", "functools", "glob", "hashlib", "io", "itertools",
    "json", "logging", "math", "os", "pathlib", "pickle", "random", "re",
    "shutil", "socket", "sqlite3", "string", "struct", "subprocess", "sys",
    "tempfile", "threading", "time", "typing", "urllib", "uuid", "warnings"
}}

def extract_imports(file_path):
    # Extract import statements from Python file
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            tree = ast.parse(f.read(), filename=str(file_path))

        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module.split(".")[0])

        return imports
    except:
        return []

# Find Python files in repository
repo_path = Path("{repository_path}")
py_files = list(repo_path.rglob("*.py"))[:100]  # Limit to first 100 files

# Extract all imports
all_imports = defaultdict(list)
for py_file in py_files:
    rel_path = str(py_file.relative_to(repo_path))
    imports = extract_imports(py_file)
    for imp in imports:
        if imp not in STDLIB_MODULES and not imp.startswith("_"):
            all_imports[imp].append(rel_path)

# Filter out likely local imports (check if they exist as files)
external_imports = {{}}
for pkg, files in all_imports.items():
    # Check if this looks like an external package
    pkg_path = repo_path / pkg
    pkg_py = repo_path / f"{{pkg}}.py"

    if not pkg_path.exists() and not pkg_py.exists():
        external_imports[pkg] = files[:3]  # Keep first 3 locations

# Output
if external_imports:
    print(f"Found {{len(external_imports)}} external dependencies:")
    print()
    for pkg in sorted(external_imports.keys())[:30]:  # First 30
        locs = external_imports[pkg]
        loc_str = ", ".join(locs)
        if len(external_imports[pkg]) > 3:
            loc_str += f" (and {{len(external_imports[pkg]) - 3}} more)"
        print(f"  - {{pkg}}: {{loc_str}}")
else:
    print("No external dependencies found.")
'"""

            # Execute via bash_executor
            result = (await self._execute_bash_command(script))[0]
            return result

        return StructuredTool.from_function(
            coroutine=analyze_imports,
            name="analyze_imports",
            description="Automatically extract all external Python dependencies from source code using AST parsing. Much faster than manually checking requirements files. Use this to discover what packages are needed."
        )

    def _create_api_analyzer(self) -> StructuredTool:
        """
        Tool to analyze API usage patterns for version inference.
        Executes inside Docker.
        """
        async def analyze_api_patterns(packages: str, repository_path: str = ".") -> str:
            """
            Analyze HOW specific packages are used in the code to infer version constraints.
            This checks which functions, classes, and methods are called.

            Args:
                packages: Comma-separated package names (e.g., "numpy,pandas,jinja2")
                repository_path: Path to analyze (default: current directory)

            Example: If code uses pandas.DataFrame.append, we know it needs pandas < 2.0
            """
            # Clean package list
            pkg_list = [p.strip() for p in packages.split(',') if p.strip()]
            if not pkg_list:
                return "Error: No packages specified"

            # Python script for API pattern analysis
            packages_str = ','.join(pkg_list)
            script = f"""python -c '
import ast
import sys
from pathlib import Path
from collections import defaultdict

PACKAGES = "{packages_str}".split(",")

def extract_api_usage(file_path, target_packages):
    # Extract API calls for target packages
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            tree = ast.parse(content, filename=str(file_path))

        api_usage = defaultdict(set)

        for node in ast.walk(tree):
            # Function calls: package.function()
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    # Check if it\\'s a package call
                    obj = node.func.value
                    if isinstance(obj, ast.Name):
                        if obj.id in target_packages:
                            api_usage[obj.id].add(f"{{obj.id}}.{{node.func.attr}}")
                    elif isinstance(obj, ast.Attribute):
                        # Nested like pkg.module.func()
                        parts = []
                        current = obj
                        while isinstance(current, ast.Attribute):
                            parts.insert(0, current.attr)
                            current = current.value
                        if isinstance(current, ast.Name) and current.id in target_packages:
                            api = f"{{current.id}}.{{\\".\\".join(parts)}}.{{node.func.attr}}"
                            api_usage[current.id].add(api)

            # Attribute access: package.Class
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    if node.value.id in target_packages:
                        api_usage[node.value.id].add(f"{{node.value.id}}.{{node.attr}}")

        return api_usage
    except:
        return {{}}

# Analyze repository
repo_path = Path("{repository_path}")
py_files = list(repo_path.rglob("*.py"))[:50]  # Limit to 50 files

all_api_usage = defaultdict(set)
for py_file in py_files:
    usage = extract_api_usage(py_file, PACKAGES)
    for pkg, apis in usage.items():
        all_api_usage[pkg].update(apis)

# Output
if all_api_usage:
    print("API Usage Patterns (for version inference):")
    print()
    for pkg in sorted(all_api_usage.keys()):
        apis = sorted(all_api_usage[pkg])[:15]  # First 15 APIs
        print(f"Package: {{pkg}}")
        for api in apis:
            print(f"  - {{api}}")
        if len(all_api_usage[pkg]) > 15:
            print(f"  ... and {{len(all_api_usage[pkg]) - 15}} more")
        print()
else:
    print(f"No API usage found for packages: {packages_str}")
'"""

            # Execute via bash_executor
            result = (await self._execute_bash_command(script))[0]
            return result

        return StructuredTool.from_function(
            coroutine=analyze_api_patterns,
            name="analyze_api_patterns",
            description="Analyze HOW specific packages are used (which functions, classes, methods) to infer version constraints. Useful for determining if code needs older/newer versions based on API changes."
        )


# For testing
if __name__ == "__main__":
    print("DockerAnalysisToolkit implementation complete")
    print("Tools execute Python scripts inside Docker container")
    print("Solves host/container execution mismatch")
