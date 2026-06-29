"""unified_system.bridge — Unified System orchestration entry point.

This module wires the three layers together:

    OpenManus-RL (training)
        ↕  trajectoires + récompenses
    crewAI        (orchestration)
        ↕  actions exécutées dans sandbox
    OpenHands     (exécution)

Quick-start
-----------
::

    from unified_system.bridge import UnifiedSystem

    system = UnifiedSystem.from_env()          # reads env vars
    system.train(n_steps=500)                  # RL training loop
    result = system.run_task("Write a merge-sort in Python")   # inference

Environment variables
---------------------
OH_BASE_URL         URL of the running OpenHands server  (default: http://localhost:3000)
OH_TOKEN            Bearer token for OpenHands           (default: "")
CREWAI_LLM_MODEL    Model string for crewAI agents       (default: gpt-4o-mini)
OPENAI_API_KEY      API key forwarded to crewAI / OpenAI
RL_MAX_STEPS        Max RL training steps                (default: 1000)
RL_BATCH_SIZE       Parallel sandboxes per RL step       (default: 4)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ── crewAI imports ─────────────────────────────────────────────────────────────
from crewai import Agent, Crew, Task
from crewai.tools.openhands_tool import OpenHandsTask

# ── OpenManus-RL imports ──────────────────────────────────────────────────────
from openmanus_rl.engines.openai import CrewAIEngine
from openmanus_rl.multi_turn_rollout.tool_integration import SSRFSafeToolRegistry


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class UnifiedSystemConfig:
    """All runtime parameters for the unified stack."""

    # OpenHands
    openhands_base_url: str = "http://localhost:3000"
    openhands_token: str = ""
    openhands_timeout: int = 120

    # crewAI
    crewai_llm_model: str = "gpt-4o-mini"
    crewai_verbose: bool = False

    # OpenManus-RL
    rl_max_steps: int = 1000
    rl_batch_size: int = 4
    rl_reward_allocation: str = "last_token"  # "last_token" | "uniform_positive" | "discounted"

    # Tool security
    enable_ssrf_protection: bool = True

    @classmethod
    def from_env(cls) -> "UnifiedSystemConfig":
        """Build config from environment variables."""
        return cls(
            openhands_base_url=os.getenv("OH_BASE_URL", "http://localhost:3000"),
            openhands_token=os.getenv("OH_TOKEN", ""),
            openhands_timeout=int(os.getenv("OH_TIMEOUT", "120")),
            crewai_llm_model=os.getenv("CREWAI_LLM_MODEL", "gpt-4o-mini"),
            rl_max_steps=int(os.getenv("RL_MAX_STEPS", "1000")),
            rl_batch_size=int(os.getenv("RL_BATCH_SIZE", "4")),
        )


# ── Core unified system ───────────────────────────────────────────────────────

class UnifiedSystem:
    """Entry point that assembles and exposes the three-layer agent stack.

    Layers
    ------
    1. **Tool registry** (OpenManus-RL + crewAI security)
       :class:`SSRFSafeToolRegistry` loads RL tools while routing every HTTP
       request through the crewAI SSRF-protected adapter.

    2. **crewAI Crew** (orchestration)
       A single-agent crew whose sole tool is :class:`OpenHandsTask`.  The
       crew translates high-level instructions into OpenHands API calls.

    3. **OpenManus-RL engine** (training)
       :class:`CrewAIEngine` wraps the crew so OpenManus-RL can treat it as an
       LLM policy and collect RL trajectories against an OpenHands environment.

    Args:
        config: :class:`UnifiedSystemConfig` with all runtime parameters.
        crew_factory: Optional custom factory returning a crewAI :class:`Crew`.
            When omitted, the default software-developer crew is used.
    """

    def __init__(
        self,
        config: Optional[UnifiedSystemConfig] = None,
        crew_factory: Optional[Callable[[], Crew]] = None,
    ) -> None:
        self.config = config or UnifiedSystemConfig()

        # ── Layer 1: SSRF-safe tool registry ──────────────────────────────
        self.tool_registry = SSRFSafeToolRegistry() if self.config.enable_ssrf_protection else None

        # ── Layer 2: crewAI crew ───────────────────────────────────────────
        self._crew_factory = crew_factory or self._default_crew_factory
        self.crew = self._crew_factory()

        # ── Layer 3: OpenManus-RL engine ───────────────────────────────────
        self.engine = CrewAIEngine(crew_factory=self._crew_factory)

    # ── Public API ─────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "UnifiedSystem":
        """Create a UnifiedSystem using environment variable configuration."""
        return cls(config=UnifiedSystemConfig.from_env())

    def run_task(self, instruction: str) -> str:
        """Run a single task through the full crewAI → OpenHands stack.

        This is the **inference** path: no RL training is involved.

        Args:
            instruction: Natural-language task description.

        Returns:
            The final output from the OpenHands sandbox agent.
        """
        return self.engine(prompt=instruction)

    def build_rl_env_config(self) -> dict:
        """Return an omegaconf-compatible dict for OpenManus-RL's env config.

        Inject into your training config with::

            from omegaconf import OmegaConf
            cfg = OmegaConf.create(system.build_rl_env_config())

        Returns:
            dict with ``env.*`` keys expected by :class:`OpenHandsEnvironmentManager`.
        """
        return {
            "env": {
                "env_name": "openhands",
                "openhands_base_url": self.config.openhands_base_url,
                "openhands_token": self.config.openhands_token,
                "openhands_timeout": self.config.openhands_timeout,
                "rollout": {"n": 1},
                "history_length": 0,
                "seed": 42,
            },
            "data": {
                "train_batch_size": self.config.rl_batch_size,
                "val_batch_size": max(1, self.config.rl_batch_size // 4),
            },
            "algorithm": {
                "reward_allocation": self.config.rl_reward_allocation,
            },
        }

    def health_check(self) -> dict:
        """Ping each layer and return a status report.

        Returns:
            dict with ``openhands``, ``crewai``, and ``rl_engine`` keys.
        """
        import requests

        status: dict[str, Any] = {}

        # OpenHands
        try:
            r = requests.get(
                f"{self.config.openhands_base_url}/health",
                timeout=5,
                headers={"Authorization": f"Bearer {self.config.openhands_token}"}
                if self.config.openhands_token else {},
            )
            status["openhands"] = "ok" if r.ok else f"HTTP {r.status_code}"
        except Exception as exc:
            status["openhands"] = f"error: {exc}"

        # crewAI — just verify the crew object exists
        try:
            status["crewai"] = f"ok — {len(self.crew.agents)} agent(s)"
        except Exception as exc:
            status["crewai"] = f"error: {exc}"

        # OpenManus-RL engine
        try:
            _ = self.engine  # non-None check
            status["rl_engine"] = "ok — CrewAIEngine ready"
        except Exception as exc:
            status["rl_engine"] = f"error: {exc}"

        return status

    # ── Default crewAI crew ────────────────────────────────────────────────

    def _default_crew_factory(self) -> Crew:
        """Build the default software-developer crew.

        The crew has one agent (a software engineer) whose single tool is
        :class:`OpenHandsTask`.  To customise the crew, pass your own
        ``crew_factory`` to :class:`UnifiedSystem.__init__`.
        """
        oh_tool = OpenHandsTask(
            openhands_base_url=self.config.openhands_base_url,
            openhands_token=self.config.openhands_token,
            timeout=self.config.openhands_timeout,
        )

        engineer = Agent(
            role="Software Engineer",
            goal=(
                "Implement software tasks precisely and efficiently "
                "using the OpenHands sandbox."
            ),
            backstory=(
                "You are an expert software engineer trained via reinforcement "
                "learning on thousands of real coding tasks.  You always produce "
                "clean, tested, documented code."
            ),
            tools=[oh_tool],
            llm=self.config.crewai_llm_model,
            verbose=self.config.crewai_verbose,
        )

        task = Task(
            description="Complete the following software task: {observation}",
            expected_output=(
                "A concise description of what was implemented, plus the "
                "sandbox output confirming success."
            ),
            agent=engineer,
        )

        return Crew(
            agents=[engineer],
            tasks=[task],
            verbose=self.config.crewai_verbose,
        )
