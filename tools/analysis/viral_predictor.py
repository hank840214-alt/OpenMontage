"""Viral Predictor — LLM-based virality ideation via OpenRouter.

STUB: Marked UNAVAILABLE if OPENROUTER_API_KEY is not set.
The underlying viral-predictor venv (~/viral-tools/viral-predictor-venv/) runs
a Streamlit UI; this wrapper provides a headless API path for batch use.
"""

from __future__ import annotations

import os
from typing import Any

from tools.base_tool import (
    BaseTool,
    DependencyError,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


class ViralPredictor(BaseTool):
    name = "viral_predictor"
    version = "0.1.0"
    tier = ToolTier.ANALYZE
    capability = "viral_prediction"
    provider = "openrouter"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["env:OPENROUTER_API_KEY"]
    install_instructions = (
        "Set OPENROUTER_API_KEY in your environment or ~/OpenMontage/.env.\n"
        "Get a key at https://openrouter.ai/\n"
        "The Streamlit UI (~/viral-tools/viral-predictor-venv/) is available for interactive use."
    )

    capabilities = ["llm_viral_scoring", "ab_ideation", "hook_rewriting"]
    supports = {"offline": False, "caching": False}
    best_for = [
        "A/B hook title ideation",
        "LLM-based virality prediction for clip text",
        "multi-model consensus scoring",
    ]
    not_good_for = [
        "batch scoring (API cost adds up)",
        "offline / no-key environments (use viral_scorer instead)",
    ]

    input_schema = {
        "type": "object",
        "required": ["clip_text"],
        "properties": {
            "clip_text": {"type": "string", "description": "Transcript text of the clip to evaluate"},
            "platform": {"type": "string", "default": "instagram_reels"},
            "model": {"type": "string", "default": "anthropic/claude-3-haiku"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=128, vram_mb=0, disk_mb=0, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["rate_limit", "timeout"])
    side_effects = ["API call to OpenRouter (costs money)"]
    user_visible_verification = [
        "Check returned viral_score and reasoning fields",
    ]

    def get_status(self) -> ToolStatus:
        if os.environ.get("OPENROUTER_API_KEY"):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def check_dependencies(self) -> None:
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise DependencyError(
                "OPENROUTER_API_KEY not set. " + self.install_instructions
            )

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        # Rough estimate: ~1K tokens in + ~500 out at Haiku pricing (~$0.0003)
        return 0.001

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        try:
            self.check_dependencies()
        except DependencyError as e:
            return ToolResult(
                success=False,
                error=(
                    f"ViralPredictor unavailable: {e}\n"
                    "Use viral_scorer (local, zero-cost) instead for offline scoring."
                ),
            )

        # TODO: Implement headless OpenRouter API call when key is available.
        # The viral-predictor Streamlit app at ~/viral-tools/viral-predictor-venv/
        # contains the prompt templates and model routing logic to adapt here.
        return ToolResult(
            success=False,
            error=(
                "ViralPredictor headless execution not yet implemented.\n"
                "Run the Streamlit UI: "
                "~/viral-tools/viral-predictor-venv/bin/streamlit run "
                "~/viral-tools/viral-predictor-venv/app.py"
            ),
        )
