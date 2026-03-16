"""
Enhanced Bash Toolkit for EnvAgent

Extends EnvBench's BashTerminalToolkit with static analysis tools.
This maintains compatibility with EnvBench while adding our contributions.
"""

import sys
from pathlib import Path
from typing import List

# Add EnvBench to path
ENVBENCH_PATH = Path(__file__).parents[2] / "EnvBench"
if str(ENVBENCH_PATH) not in sys.path:
    sys.path.insert(0, str(ENVBENCH_PATH))

from langchain_core.tools import BaseTool

# EnvBench imports
from inference.src.toolkits.bash_terminal import BashTerminalToolkit

# Our tools
from envagent.tools.ast_import_parser import ASTImportParserTool
from envagent.tools.api_pattern_analyzer import APIPatternAnalyzerTool
from envagent.tools.environment_analyzer import EnvironmentAnalyzerTool


class EnhancedBashToolkit(BashTerminalToolkit):
    """
    Bash Agent toolkit + static analysis tools.

    This is our core contribution: extending the baseline Bash Agent
    with tools that enable:
    1. Automatic dependency discovery (AST import parsing)
    2. Version inference based on API usage patterns
    3. OS and environment awareness for cross-platform setup

    Research rationale:
    - Inherits from BashTerminalToolkit (fair comparison with baseline)
    - Adds 3 new tools without modifying EnvBench code
    - Same Docker environment, same evaluation metrics
    - Clear contribution boundary
    """

    # Pydantic v2 config to allow extra fields
    class Config:
        arbitrary_types_allowed = True
        extra = 'allow'  # Allow dynamic attributes

    def get_tools(self, *args, **kwargs) -> List[BaseTool]:
        """
        Returns all available tools for the agent.

        Includes:
        - execute_bash_command (from base BashTerminalToolkit)
        - analyze_environment (our environment analyzer)
        - analyze_imports (our AST parser)
        - analyze_api_patterns (our API analyzer)

        The agent can choose which tools to use based on the task.
        """
        # Get base bash tool from EnvBench
        base_tools = super().get_tools(*args, **kwargs)

        # Create our static analysis tools (instantiate here to avoid Pydantic issues)
        env_analyzer = EnvironmentAnalyzerTool()
        ast_parser = ASTImportParserTool()
        api_analyzer = APIPatternAnalyzerTool()

        # Add our static analysis tools
        our_tools = [
            env_analyzer.as_langchain_tool(),  # Environment analysis first
            ast_parser.as_langchain_tool(),
            api_analyzer.as_langchain_tool(),
        ]

        return base_tools + our_tools


# Example usage and testing
if __name__ == "__main__":
    print("EnhancedBashToolkit implementation complete")
    print("Base class: BashTerminalToolkit from EnvBench")
    print("Additional tools: 3 (environment_analyzer, ast_import_parser, api_pattern_analyzer)")
