"""
Environment Analyzer Tool for EnvAgent

This tool collects comprehensive information about the target system environment
to enable OS-aware and cross-platform environment setup.

Key information collected:
1. OS type, version, architecture
2. Shell environment
3. Package managers (system + Python)
4. Python installations and version managers
5. Build tools and compilers
6. Installed packages (system + Python)
7. File system information
"""

import platform
import sys
import os
import subprocess
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

from langchain_core.tools import StructuredTool
from pydantic import Field


@dataclass
class OSInfo:
    """Operating system information"""
    system: str  # Linux, Windows, Darwin
    release: str  # e.g., 22.04, 11, 13.0
    version: str  # Detailed version string
    machine: str  # x86_64, arm64, AMD64, etc.
    platform: str  # Full platform string


@dataclass
class ShellInfo:
    """Shell environment information"""
    shell_type: str  # bash, zsh, PowerShell, cmd
    shell_version: str
    env_var_syntax: str  # export/set/$env:
    path_separator: str  # : or ;
    line_separator: str  # \n or \r\n


@dataclass
class PackageManagerInfo:
    """Available package managers"""
    system_managers: List[str]  # apt-get, yum, brew, choco
    python_managers: List[str]  # pip, conda, poetry


@dataclass
class PythonEnvironmentInfo:
    """Python environment information"""
    current_version: str
    available_versions: List[str]  # From pyenv if available
    python_path: str
    version_manager: Optional[str]  # pyenv, pyenv-win, conda
    virtualenv_tools: List[str]  # venv, virtualenv, conda


@dataclass
class BuildToolsInfo:
    """Build tools and compilers"""
    c_compiler: Optional[str]  # gcc, clang, cl.exe
    cpp_compiler: Optional[str]
    make_tool: Optional[str]  # make, nmake
    other_tools: List[str]  # cmake, ninja, etc.


@dataclass
class InstalledPackagesInfo:
    """Currently installed packages"""
    system_packages_count: int
    python_packages: Dict[str, str]  # package_name -> version
    python_packages_count: int


@dataclass
class FileSystemInfo:
    """File system information"""
    path_separator: str  # / or \
    case_sensitive: bool
    working_directory: str


@dataclass
class EnvironmentAnalysisResult:
    """Complete environment analysis result"""
    os_info: OSInfo
    shell_info: ShellInfo
    package_managers: PackageManagerInfo
    python_env: PythonEnvironmentInfo
    build_tools: BuildToolsInfo
    installed_packages: InstalledPackagesInfo
    filesystem: FileSystemInfo


class EnvironmentAnalyzerTool:
    """
    Tool that analyzes the target system environment for cross-platform setup.

    This tool collects detailed information about:
    - Operating system and architecture
    - Shell environment and syntax
    - Available package managers
    - Python installations and tools
    - Build tools and compilers
    - Already installed packages (to avoid redundant installs)
    - File system characteristics

    The collected information helps the agent make OS-specific decisions.
    """

    def __init__(self):
        self.os_system = platform.system()

    def _run_command(self, command: str, shell: bool = True) -> Optional[str]:
        """Run a command and return output, or None if failed"""
        try:
            result = subprocess.run(
                command,
                shell=shell,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
            return None

    def _detect_os_info(self) -> OSInfo:
        """Detect operating system information"""
        return OSInfo(
            system=platform.system(),
            release=platform.release(),
            version=platform.version(),
            machine=platform.machine(),
            platform=platform.platform()
        )

    def _detect_shell_info(self) -> ShellInfo:
        """Detect shell environment information"""
        system = platform.system()

        if system == "Windows":
            # Check if PowerShell is available
            ps_version = self._run_command("powershell -Command $PSVersionTable.PSVersion.ToString()")
            if ps_version:
                return ShellInfo(
                    shell_type="PowerShell",
                    shell_version=ps_version,
                    env_var_syntax="$env:",
                    path_separator=";",
                    line_separator="\r\n"
                )
            else:
                return ShellInfo(
                    shell_type="cmd",
                    shell_version="",
                    env_var_syntax="set",
                    path_separator=";",
                    line_separator="\r\n"
                )
        else:
            # Linux or macOS
            shell = os.environ.get("SHELL", "/bin/bash")
            shell_name = Path(shell).name

            # Try to get version
            version = ""
            if shell_name == "bash":
                version_output = self._run_command("bash --version")
                if version_output:
                    version = version_output.split('\n')[0]
            elif shell_name == "zsh":
                version_output = self._run_command("zsh --version")
                if version_output:
                    version = version_output

            return ShellInfo(
                shell_type=shell_name,
                shell_version=version,
                env_var_syntax="export",
                path_separator=":",
                line_separator="\n"
            )

    def _detect_package_managers(self) -> PackageManagerInfo:
        """Detect available package managers"""
        system_managers = []
        python_managers = []

        # System package managers
        system_pm_commands = {
            "apt-get": "apt-get --version",
            "yum": "yum --version",
            "dnf": "dnf --version",
            "brew": "brew --version",
            "choco": "choco --version",
            "pacman": "pacman --version"
        }

        for pm, cmd in system_pm_commands.items():
            if self._run_command(cmd):
                system_managers.append(pm)

        # Python package managers
        python_pm_commands = {
            "pip": "pip --version",
            "pip3": "pip3 --version",
            "conda": "conda --version",
            "poetry": "poetry --version",
            "pipenv": "pipenv --version"
        }

        for pm, cmd in python_pm_commands.items():
            if self._run_command(cmd):
                python_managers.append(pm)

        return PackageManagerInfo(
            system_managers=system_managers,
            python_managers=python_managers
        )

    def _detect_python_environment(self) -> PythonEnvironmentInfo:
        """Detect Python environment information"""
        current_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        python_path = sys.executable

        # Check for version managers
        version_manager = None
        if self._run_command("pyenv --version"):
            version_manager = "pyenv"
        elif self._run_command("pyenv-win --version"):
            version_manager = "pyenv-win"
        elif self._run_command("conda --version"):
            version_manager = "conda"

        # Get available Python versions from pyenv
        available_versions = []
        if version_manager in ["pyenv", "pyenv-win"]:
            versions_output = self._run_command("pyenv versions")
            if versions_output:
                for line in versions_output.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('*'):
                        # Extract version number
                        version = line.split()[0] if line.split() else ""
                        if version and version[0].isdigit():
                            available_versions.append(version)

        # Detect virtualenv tools
        virtualenv_tools = []
        if self._run_command("python -m venv --help"):
            virtualenv_tools.append("venv")
        if self._run_command("virtualenv --version"):
            virtualenv_tools.append("virtualenv")
        if self._run_command("conda --version"):
            virtualenv_tools.append("conda")

        return PythonEnvironmentInfo(
            current_version=current_version,
            available_versions=available_versions,
            python_path=python_path,
            version_manager=version_manager,
            virtualenv_tools=virtualenv_tools
        )

    def _detect_build_tools(self) -> BuildToolsInfo:
        """Detect available build tools and compilers"""
        c_compiler = None
        cpp_compiler = None
        make_tool = None
        other_tools = []

        # C compilers
        for compiler in ["gcc", "clang", "cl"]:
            if self._run_command(f"{compiler} --version"):
                c_compiler = compiler
                break

        # C++ compilers
        for compiler in ["g++", "clang++", "cl"]:
            if self._run_command(f"{compiler} --version"):
                cpp_compiler = compiler
                break

        # Make tools
        for make in ["make", "nmake", "ninja"]:
            if self._run_command(f"{make} --version"):
                if make_tool is None:
                    make_tool = make
                else:
                    other_tools.append(make)

        # Other build tools
        for tool in ["cmake", "meson", "autoconf", "automake"]:
            if self._run_command(f"{tool} --version"):
                other_tools.append(tool)

        return BuildToolsInfo(
            c_compiler=c_compiler,
            cpp_compiler=cpp_compiler,
            make_tool=make_tool,
            other_tools=other_tools
        )

    def _detect_installed_packages(self) -> InstalledPackagesInfo:
        """Detect currently installed packages"""
        system = platform.system()
        system_packages_count = 0
        python_packages = {}

        # System packages count (don't list all - too many)
        if system == "Linux":
            # For apt-based systems
            output = self._run_command("dpkg --list 2>/dev/null | grep '^ii' | wc -l")
            if output and output.isdigit():
                system_packages_count = int(output)
            # For rpm-based systems
            elif self._run_command("rpm -qa"):
                output = self._run_command("rpm -qa | wc -l")
                if output and output.isdigit():
                    system_packages_count = int(output)
        elif system == "Darwin":
            # macOS with brew
            output = self._run_command("brew list | wc -l")
            if output:
                try:
                    system_packages_count = int(output.strip())
                except ValueError:
                    pass
        elif system == "Windows":
            # Windows with choco
            output = self._run_command("choco list --local-only | Select-String 'packages installed'")
            if output:
                # Parse output like "5 packages installed."
                try:
                    system_packages_count = int(output.split()[0])
                except (ValueError, IndexError):
                    pass

        # Python packages - get list with versions
        pip_list_output = self._run_command("pip list --format=json")
        if pip_list_output:
            try:
                packages = json.loads(pip_list_output)
                for pkg in packages:
                    python_packages[pkg['name']] = pkg['version']
            except json.JSONDecodeError:
                pass

        return InstalledPackagesInfo(
            system_packages_count=system_packages_count,
            python_packages=python_packages,
            python_packages_count=len(python_packages)
        )

    def _detect_filesystem_info(self) -> FileSystemInfo:
        """Detect file system information"""
        system = platform.system()

        if system == "Windows":
            path_sep = "\\"
            case_sensitive = False
        else:
            path_sep = "/"
            # Check case sensitivity
            case_sensitive = True  # Most Unix systems are case-sensitive

        return FileSystemInfo(
            path_separator=path_sep,
            case_sensitive=case_sensitive,
            working_directory=os.getcwd()
        )

    def analyze_environment(self) -> EnvironmentAnalysisResult:
        """
        Perform comprehensive environment analysis.

        Returns:
            EnvironmentAnalysisResult with all collected information
        """
        return EnvironmentAnalysisResult(
            os_info=self._detect_os_info(),
            shell_info=self._detect_shell_info(),
            package_managers=self._detect_package_managers(),
            python_env=self._detect_python_environment(),
            build_tools=self._detect_build_tools(),
            installed_packages=self._detect_installed_packages(),
            filesystem=self._detect_filesystem_info()
        )

    def as_langchain_tool(self) -> StructuredTool:
        """Convert to LangChain tool for agent use"""
        def analyze() -> str:
            """
            Analyze the current system environment to gather information for cross-platform setup.

            This tool collects comprehensive information about:
            - Operating system (type, version, architecture)
            - Shell environment (bash/PowerShell, environment variable syntax)
            - Package managers (apt-get/brew/choco, pip/conda)
            - Python installations (versions, pyenv, virtualenv tools)
            - Build tools (gcc/clang/MSVC, make tools)
            - Already installed packages (system + Python packages with versions)
            - File system (path separators, case sensitivity)

            Use this information to make OS-specific decisions when generating setup scripts.
            """
            result = self.analyze_environment()

            # Format output for LLM consumption
            output = []
            output.append("=== SYSTEM ENVIRONMENT ANALYSIS ===\n")

            # OS Info
            output.append(f"📍 Operating System:")
            output.append(f"  - System: {result.os_info.system}")
            output.append(f"  - Release: {result.os_info.release}")
            output.append(f"  - Architecture: {result.os_info.machine}")
            output.append("")

            # Shell Info
            output.append(f"🖥️  Shell Environment:")
            output.append(f"  - Shell: {result.shell_info.shell_type} {result.shell_info.shell_version}")
            output.append(f"  - Environment variables: {result.shell_info.env_var_syntax}")
            output.append(f"  - Path separator: '{result.shell_info.path_separator}'")
            output.append("")

            # Package Managers
            output.append(f"📦 Package Managers:")
            output.append(f"  - System: {', '.join(result.package_managers.system_managers) if result.package_managers.system_managers else 'None detected'}")
            output.append(f"  - Python: {', '.join(result.package_managers.python_managers) if result.package_managers.python_managers else 'None detected'}")
            output.append("")

            # Python Environment
            output.append(f"🐍 Python Environment:")
            output.append(f"  - Current version: {result.python_env.current_version}")
            output.append(f"  - Python path: {result.python_env.python_path}")
            output.append(f"  - Version manager: {result.python_env.version_manager or 'None'}")
            if result.python_env.available_versions:
                output.append(f"  - Available versions: {', '.join(result.python_env.available_versions[:5])}")
            output.append(f"  - Virtualenv tools: {', '.join(result.python_env.virtualenv_tools)}")
            output.append("")

            # Build Tools
            output.append(f"🔨 Build Tools:")
            output.append(f"  - C compiler: {result.build_tools.c_compiler or 'Not found'}")
            output.append(f"  - C++ compiler: {result.build_tools.cpp_compiler or 'Not found'}")
            output.append(f"  - Make tool: {result.build_tools.make_tool or 'Not found'}")
            if result.build_tools.other_tools:
                output.append(f"  - Other tools: {', '.join(result.build_tools.other_tools)}")
            output.append("")

            # Installed Packages
            output.append(f"📚 Installed Packages:")
            output.append(f"  - System packages: ~{result.installed_packages.system_packages_count}")
            output.append(f"  - Python packages: {result.installed_packages.python_packages_count}")

            # Show some common packages if installed
            common_packages = ['numpy', 'pandas', 'requests', 'setuptools', 'wheel', 'pip']
            found_common = {pkg: ver for pkg, ver in result.installed_packages.python_packages.items()
                          if pkg.lower() in common_packages}
            if found_common:
                output.append(f"  - Common packages already installed:")
                for pkg, ver in sorted(found_common.items())[:10]:
                    output.append(f"    • {pkg}=={ver}")
            output.append("")

            # File System
            output.append(f"📁 File System:")
            output.append(f"  - Path separator: '{result.filesystem.path_separator}'")
            output.append(f"  - Case sensitive: {result.filesystem.case_sensitive}")
            output.append(f"  - Working directory: {result.filesystem.working_directory}")
            output.append("")

            # Recommendations based on OS
            output.append(f"💡 Platform-Specific Notes:")
            if result.os_info.system == "Windows":
                output.append(f"  - Use PowerShell syntax for commands")
                output.append(f"  - Virtual env activation: .\\venv\\Scripts\\activate")
                output.append(f"  - May need Visual C++ Build Tools for C extensions")
            elif result.os_info.system == "Darwin":
                output.append(f"  - Use bash/zsh syntax for commands")
                output.append(f"  - Virtual env activation: source venv/bin/activate")
                output.append(f"  - May need Xcode Command Line Tools: xcode-select --install")
                if "arm" in result.os_info.machine.lower() or "m1" in result.os_info.machine.lower():
                    output.append(f"  - ARM architecture (M1/M2) - some packages may need special versions")
            else:  # Linux
                output.append(f"  - Use bash syntax for commands")
                output.append(f"  - Virtual env activation: source venv/bin/activate")
                output.append(f"  - May need build-essential for C extensions")

            return "\n".join(output)

        return StructuredTool.from_function(
            func=analyze,
            name="analyze_environment",
            description=(
                "Analyze the current system environment to collect OS, shell, package managers, "
                "Python installations, build tools, and installed packages information. "
                "Use this at the beginning to understand the target platform and make OS-specific decisions."
            )
        )


# Example usage
if __name__ == "__main__":
    analyzer = EnvironmentAnalyzerTool()
    result = analyzer.analyze_environment()

    print(f"OS: {result.os_info.system} {result.os_info.release}")
    print(f"Shell: {result.shell_info.shell_type}")
    print(f"Python: {result.python_env.current_version}")
    print(f"Installed Python packages: {result.installed_packages.python_packages_count}")
