"""
EnvAgent: Tool-Enhanced Cross-Platform Environment Setup Agent

Based on EnvBench's Bash Agent with static analysis tools.

Key differences from baseline:
1. Static analysis tools (environment analyzer, import analyzer, API analyzer)
2. Tools execute inside Docker via bash_executor (solving host/container mismatch)
3. Enhanced prompts that guide tool usage
4. Same ReAct framework, same Docker environment
5. Fair comparison with clear contribution boundary (tools + prompts)
"""

import sys
from pathlib import Path
from typing import Optional

# Add EnvBench to path
ENVBENCH_PATH = Path(__file__).parents[2] / "EnvBench"
if str(ENVBENCH_PATH) not in sys.path:
    sys.path.insert(0, str(ENVBENCH_PATH))

from langchain_core.language_models import BaseChatModel
from langgraph.graph.graph import CompiledGraph
from langgraph.prebuilt import create_react_agent

# EnvBench imports
from inference.src.agents.base import BaseEnvSetupAgent
from inference.src.context_providers.build_instructions import EnvSetupInstructionProvider
from inference.src.agents.python.state_schema import (
    EnvSetupPythonState,
    EnvSetupPythonTrajectoryEntry,
    EnvSetupPythonUpdate
)
from inference.src.toolkits.bash_terminal import BashTerminalToolkit

# Our imports
from envagent.prompts import get_envagent_prompt
from envagent.toolkits.docker_analysis_toolkit import DockerAnalysisToolkit


class EnvAgent(BaseEnvSetupAgent[EnvSetupPythonState, EnvSetupPythonUpdate, EnvSetupPythonTrajectoryEntry]):
    """
    Enhanced version of EnvBench Bash Agent with static analysis tools.

    **Research Contribution:**
    - Static analysis tools that execute inside Docker container
    - AST-based import extraction (auto-discover dependencies)
    - API pattern analysis (version inference from code usage)
    - Environment analyzer (OS, Python, installed packages)
    - Same framework (fair comparison)

    **Architecture:**
    - Base: EnvSetupPythonAgent (from EnvBench)
    - Toolkit: DockerAnalysisToolkit (extends BashTerminalToolkit with 3 tools)
    - Prompt: get_envagent_prompt (guides tool usage)
    - Framework: ReAct (same as baseline)

    **Novelty:**
    1. Docker-executed static analysis (vs. host execution)
    2. AST-based dependency discovery (vs. manual requirements parsing)
    3. API pattern version inference (vs. trial and error)
    """

    def __init__(
        self,
        model: BaseChatModel,
        instruction_provider: EnvSetupInstructionProvider,
        bash_executor,  # Docker bash executor from EnvBench
        max_iterations: Optional[int] = None,
    ):
        # Use DockerAnalysisToolkit with static analysis tools
        self.toolkit = DockerAnalysisToolkit(bash_executor=bash_executor)

        self.model = model
        self.instruction_provider = instruction_provider
        self._max_iterations = max_iterations

    @property
    def max_iterations(self) -> Optional[int]:
        """
        Maximum iterations for the agent.
        Same formula as EnvBench (2 * max_iterations + 1).
        """
        if self._max_iterations is None:
            return None
        return 2 * self._max_iterations + 1

    @property
    def commands_history(self):
        """Get command execution history from toolkit"""
        return self.toolkit.commands_history

    def get_agent(self) -> CompiledGraph:
        """
        Create the ReAct agent with enhanced prompts.

        Returns:
            CompiledGraph: LangGraph agent ready to execute
        """
        tools = self.toolkit.get_tools()

        # Use create_react_agent (same as EnvBench)
        # But with our enhanced prompt modifier
        return create_react_agent(
            model=self.model,
            tools=tools,
            state_schema=EnvSetupPythonState,
            state_modifier=get_envagent_prompt  # Our enhanced bash-focused prompt
        )

    def construct_initial_state(
        self,
        repository: str,
        revision: str,
        *args,
        **kwargs
    ) -> EnvSetupPythonState:
        """
        Construct initial state for the agent.

        Same as baseline - includes build instructions from repository.
        """
        return {
            "build_instructions": self.instruction_provider(
                repository=repository,
                revision=revision
            )
        }

    @staticmethod
    def process_update_for_trajectory(
        update: EnvSetupPythonUpdate,
        *args,
        **kwargs
    ) -> EnvSetupPythonTrajectoryEntry:
        """
        Process agent update for trajectory logging.

        Same as baseline - records agent and tool actions.
        """
        # Import here to avoid circular dependency
        from inference.src.utils import message_to_info

        if "agent" in update:
            node = "agent"
            messages = update["agent"].get("messages", [])
        elif "tools" in update:
            node = "tools"
            messages = update["tools"].get("messages", [])
        else:
            raise RuntimeError(
                f"Expected update from 'agent' or 'tools' nodes, "
                f"but got {set(update.keys()) - {'timestamp'}}."
            )

        return {
            "timestamp": update["timestamp"],
            "node": node,
            "messages": [message_to_info(message) for message in messages],
        }


# Example usage and testing
if __name__ == "__main__":
    print("EnvAgent implementation complete")
    print("\nKey features:")
    print("- Base: EnvSetupPythonAgent (EnvBench)")
    print("- Toolkit: DockerAnalysisToolkit (extends BashTerminalToolkit)")
    print("  Tools:")
    print("    * execute_bash_command (from base)")
    print("    * analyze_environment (NEW - OS, Python, packages)")
    print("    * analyze_imports (NEW - AST-based dependency extraction)")
    print("    * analyze_api_patterns (NEW - version inference)")
    print("- Prompt: Tool-focused workflow guidance")
    print("- Framework: ReAct (same as baseline)")
    print("\nResearch validity:")
    print("✓ Fair comparison (same base, same framework)")
    print("✓ Clear contribution (static analysis tools)")
    print("✓ Same evaluation (Docker environment, pyright metrics)")
