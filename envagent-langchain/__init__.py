"""
EnvAgent: OS-Aware Cross-Platform Environment Setup Agent

Extends EnvBench's Bash Agent with static analysis capabilities
for cross-platform environment setup.

Key Components:
- EnvAgent: Main agent class (extends EnvSetupPythonAgent)
- EnhancedBashToolkit: Toolkit with 4 tools (bash + 3 analysis tools)
- Tools: Environment analyzer, AST import parser, API pattern analyzer
- Prompts: OS-aware prompts encouraging static analysis

Research Contribution:
- AST-based dependency extraction
- API pattern analysis for version inference
- Cross-platform environment awareness
"""

__version__ = "0.1.0"

# Main agent
from envagent.agents.envagent import EnvAgent

# Toolkit
from envagent.toolkits.enhanced_bash_toolkit import EnhancedBashToolkit

# Individual tools
from envagent.tools.ast_import_parser import ASTImportParserTool
from envagent.tools.api_pattern_analyzer import APIPatternAnalyzerTool
from envagent.tools.environment_analyzer import EnvironmentAnalyzerTool

# Prompts
from envagent.prompts import get_envagent_prompt

__all__ = [
    "EnvAgent",
    "EnhancedBashToolkit",
    "ASTImportParserTool",
    "APIPatternAnalyzerTool",
    "EnvironmentAnalyzerTool",
    "get_envagent_prompt",
]
