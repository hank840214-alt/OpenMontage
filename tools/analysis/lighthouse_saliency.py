"""Lighthouse AMR saliency tool — per-second audio saliency via CLAP QD-DETR.

Delegates to ~/viral-tools/bin/lighthouse_saliency.py running in lighthouse-venv.
Results are cached as <audio>.saliency.json by the underlying script.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
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
    ToolTier,
)

_LIGHTHOUSE_PY = Path.home() / "viral-tools/lighthouse-venv/bin/python"
_LIGHTHOUSE_SCRIPT = Path.home() / "viral-tools/bin/lighthouse_saliency.py"
_LIGHTHOUSE_WEIGHTS = (
    Path.home() / "viral-tools/lighthouse-weights/clap_qd_detr_clotho-moment.ckpt"
)

_DEFAULT_QUERY = (
    "laughter, excited speech, emphatic statement, emotional outburst, "
    "rising pitch, joyful exclamation"
)


class LighthouseSaliency(BaseTool):
    name = "lighthouse_saliency"
    version = "0.1.0"
    tier = ToolTier.ANALYZE
    capability = "audio_saliency"
    provider = "lighthouse"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies: list[str] = []
    install_instructions = (
        "Requires:\n"
        "  ~/viral-tools/lighthouse-venv/ (Python 3.11 with LINE Lighthouse + CLAP)\n"
        "  ~/viral-tools/lighthouse-weights/clap_qd_detr_clotho-moment.ckpt (86MB)\n"
        "See ~/viral-tools/ for setup."
    )
    agent_skills = ["viral-scorer"]

    capabilities = [
        "audio_moment_retrieval",
        "per_second_saliency",
        "clap_qddetr",
        "long_form_podcast",
    ]
    supports = {"caching": True, "offline": True}
    best_for = [
        "finding emotionally salient moments in long podcasts",
        "audio-based clip ranking (no transcript needed)",
        "zh/en podcast saliency scoring",
    ]
    not_good_for = [
        "music-only audio (optimized for speech)",
        "very short clips < 10s",
        "real-time use (cold start ~3 min, cached ~instant)",
    ]

    input_schema = {
        "type": "object",
        "required": ["audio_path"],
        "properties": {
            "audio_path": {"type": "string", "description": "Path to audio file (m4a/mp3/wav)"},
            "query": {
                "type": "string",
                "default": _DEFAULT_QUERY,
                "description": "Natural language query for moment retrieval",
            },
            "output_path": {
                "type": "string",
                "description": "Override cache path (default: <audio>.saliency.json)",
            },
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "saliency_per_second": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Per-second saliency scores (log-scale, use percentile normalization)",
            },
            "score_count": {"type": "integer"},
            "cache_path": {"type": "string"},
            "from_cache": {"type": "boolean"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=4, ram_mb=1024, vram_mb=0, disk_mb=200, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=0, retryable_errors=[])
    idempotency_key_fields = ["audio_path", "query"]
    side_effects = ["writes <audio>.saliency.json cache file alongside audio"]
    user_visible_verification = [
        "Check saliency_per_second length matches audio duration in seconds",
        "Typical values: -14 to -12 log-scale; percentile normalization surfaces signal",
    ]

    def check_dependencies(self) -> None:
        if not _LIGHTHOUSE_PY.exists():
            raise DependencyError(
                f"lighthouse-venv not found at {_LIGHTHOUSE_PY}. {self.install_instructions}"
            )
        if not _LIGHTHOUSE_SCRIPT.exists():
            raise DependencyError(
                f"lighthouse_saliency.py not found at {_LIGHTHOUSE_SCRIPT}. {self.install_instructions}"
            )
        if not _LIGHTHOUSE_WEIGHTS.exists():
            raise DependencyError(
                f"Lighthouse weights not found at {_LIGHTHOUSE_WEIGHTS}. {self.install_instructions}"
            )

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        audio_path = Path(inputs.get("audio_path", ""))
        cache = Path(inputs.get("output_path") or str(audio_path) + ".saliency.json")
        return 5.0 if cache.exists() else 200.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        try:
            self.check_dependencies()
        except DependencyError as e:
            return ToolResult(success=False, error=str(e))

        audio_path = Path(inputs["audio_path"])
        if not audio_path.exists():
            return ToolResult(success=False, error=f"audio_path not found: {audio_path}")

        query = inputs.get("query", _DEFAULT_QUERY)
        cache_path = Path(
            inputs.get("output_path") or str(audio_path) + ".saliency.json"
        )

        # Return from cache if available
        if cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text())
                scores = payload.get("saliency_per_second", [])
                if scores:
                    return ToolResult(
                        success=True,
                        data={
                            "saliency_per_second": scores,
                            "score_count": len(scores),
                            "cache_path": str(cache_path),
                            "from_cache": True,
                        },
                        artifacts=[str(cache_path)],
                        duration_seconds=round(time.time() - start, 2),
                    )
            except Exception:
                pass  # Fall through to recompute

        # lighthouse_saliency.py positional args: AUDIO OUT [WEIGHT] [QUERY]
        cmd = [
            str(_LIGHTHOUSE_PY),
            str(_LIGHTHOUSE_SCRIPT),
            str(audio_path),
            str(cache_path),
            str(_LIGHTHOUSE_WEIGHTS),
            query,
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1800,  # AMR can take up to 30min for very long audio
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="Lighthouse saliency timed out after 1800s")

        if proc.returncode != 0:
            return ToolResult(
                success=False,
                error=f"lighthouse_saliency.py exited {proc.returncode}:\n{proc.stderr[-500:]}",
            )

        if not cache_path.exists():
            return ToolResult(success=False, error=f"Expected cache not written: {cache_path}")

        try:
            payload = json.loads(cache_path.read_text())
        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to parse saliency JSON: {exc}")

        scores = payload.get("saliency_per_second", [])
        return ToolResult(
            success=True,
            data={
                "saliency_per_second": scores,
                "score_count": len(scores),
                "cache_path": str(cache_path),
                "from_cache": False,
            },
            artifacts=[str(cache_path)],
            duration_seconds=round(time.time() - start, 2),
        )
