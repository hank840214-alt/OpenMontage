"""Viral scorer tool — ranks podcast clip candidates by 6-dimension virality rubric.

Delegates to ~/viral-tools/bin/viral_score.py running in clipsai-venv.
"""

from __future__ import annotations

import json
import os
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
    ToolStatus,
    ToolTier,
)

_CLIPSAI_PY = Path.home() / "viral-tools/clipsai-venv/bin/python"
_VIRAL_SCORE = Path.home() / "viral-tools/bin/viral_score.py"
_ENV_SH = Path.home() / "viral-tools/bin/env.sh"


class ViralScorer(BaseTool):
    name = "viral_scorer"
    version = "0.1.0"
    tier = ToolTier.ANALYZE
    capability = "viral_scoring"
    provider = "viral-tools"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["cmd:python3"]
    install_instructions = (
        "Requires ~/viral-tools/clipsai-venv/ and ~/viral-tools/bin/viral_score.py.\n"
        "See ~/viral-tools/ for setup instructions."
    )
    agent_skills = ["viral-scorer"]

    capabilities = [
        "podcast_clip_ranking",
        "6dim_virality_scoring",
        "cjk_aware",
        "lighthouse_amr_saliency",
    ]
    supports = {
        "caching": True,
        "offline": True,
        "cjk": True,
        "languages": ["zh-TW", "zh-CN", "en"],
    }
    best_for = [
        "ranking podcast clips by viral potential",
        "zh-TW content virality scoring",
        "Instagram Reels / TikTok clip selection",
    ]
    not_good_for = [
        "real-time scoring (AMR takes 3+ min cold start)",
        "video-only analysis without transcript",
    ]

    input_schema = {
        "type": "object",
        "required": ["transcript_path", "audio_path"],
        "properties": {
            "transcript_path": {"type": "string", "description": "Path to WhisperX transcript JSON"},
            "audio_path": {"type": "string", "description": "Path to source audio file"},
            "brand_topics": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "Brand keyword list for topic scoring",
            },
            "top_n": {"type": "integer", "default": 5, "description": "Number of clips to return"},
            "platform": {"type": "string", "default": "instagram_reels"},
            "language": {"type": "string", "default": "zh-TW"},
            "output_path": {
                "type": "string",
                "description": "Path for ranking YAML output (default: alongside audio)",
            },
            "min_duration": {"type": "number", "default": 15.0},
            "max_duration": {"type": "number", "default": 60.0},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "viral_ranking": {"type": "object"},
            "top_clip_score": {"type": "number"},
            "candidates_total": {"type": "integer"},
            "saliency_source": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=800, vram_mb=0, disk_mb=50, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["timeout"])
    idempotency_key_fields = ["transcript_path", "audio_path", "top_n", "platform"]
    side_effects = ["writes viral_ranking.yaml alongside audio or at output_path"]
    user_visible_verification = [
        "Check viral_ranking.yaml for top N clips with final_score values",
        "Verify saliency_source: lighthouse (AMR) > transcript_fallback",
    ]

    def check_dependencies(self) -> None:
        super().check_dependencies()
        if not _CLIPSAI_PY.exists():
            raise DependencyError(
                f"clipsai-venv not found at {_CLIPSAI_PY}. {self.install_instructions}"
            )
        if not _VIRAL_SCORE.exists():
            raise DependencyError(
                f"viral_score.py not found at {_VIRAL_SCORE}. {self.install_instructions}"
            )

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        # AMR saliency is ~3 min cold, cached thereafter; scoring is ~10s
        cache = Path(inputs.get("audio_path", "")).with_suffix(
            Path(inputs.get("audio_path", "x")).suffix + ".saliency.json"
        )
        return 15.0 if cache.exists() else 200.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        try:
            self.check_dependencies()
        except DependencyError as e:
            return ToolResult(success=False, error=str(e))

        transcript_path = Path(inputs["transcript_path"])
        audio_path = Path(inputs["audio_path"])

        if not transcript_path.exists():
            return ToolResult(success=False, error=f"transcript_path not found: {transcript_path}")
        if not audio_path.exists():
            return ToolResult(success=False, error=f"audio_path not found: {audio_path}")

        output_path = Path(
            inputs.get("output_path")
            or audio_path.parent / "viral_ranking.yaml"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)

        brand_topics = inputs.get("brand_topics", [])
        top_n = int(inputs.get("top_n", 5))
        platform = inputs.get("platform", "instagram_reels")
        language = inputs.get("language", "zh-TW")
        min_duration = float(inputs.get("min_duration", 15.0))
        max_duration = float(inputs.get("max_duration", 60.0))

        cmd = [
            str(_CLIPSAI_PY),
            str(_VIRAL_SCORE),
            "--transcript", str(transcript_path),
            "--audio", str(audio_path),
            "--platform", platform,
            "--top-n", str(top_n),
            "--lang", language,
            "--min-duration", str(min_duration),
            "--max-duration", str(max_duration),
            "--output", str(output_path),
        ]
        if brand_topics:
            cmd += ["--brand-topics"] + [str(t) for t in brand_topics]

        env = os.environ.copy()
        # Source env.sh equivalents (torchcodec DYLD path)
        env["DYLD_LIBRARY_PATH"] = (
            f"/opt/homebrew/opt/ffmpeg@6/lib:{env.get('DYLD_LIBRARY_PATH', '')}"
        )

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="viral_score.py timed out after 600s")

        if proc.returncode != 0:
            return ToolResult(
                success=False,
                error=f"viral_score.py exited {proc.returncode}:\n{proc.stderr[-500:]}",
            )

        if not output_path.exists():
            return ToolResult(success=False, error=f"Expected output not written: {output_path}")

        try:
            try:
                import yaml as _yaml
                ranking = _yaml.safe_load(output_path.read_text())
            except ImportError:
                # yaml not in this venv — parse via clipsai-venv python
                import subprocess as _sp
                _parse = _sp.run(
                    [str(_CLIPSAI_PY), "-c",
                     "import sys, yaml, json; d=yaml.safe_load(open(sys.argv[1])); print(json.dumps(d))",
                     str(output_path)],
                    capture_output=True, text=True, timeout=30,
                )
                if _parse.returncode != 0:
                    return ToolResult(success=False, error=f"YAML parse via clipsai-venv failed: {_parse.stderr}")
                import json as _json
                ranking = _json.loads(_parse.stdout)
        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to parse output YAML: {exc}")

        top_score = ranking.get("clips", [{}])[0].get("final_score") if ranking.get("clips") else None

        return ToolResult(
            success=True,
            data={
                "viral_ranking": ranking,
                "top_clip_score": top_score,
                "candidates_total": ranking.get("candidates_total", 0),
                "saliency_source": ranking.get("saliency_source", "unknown"),
                "output_path": str(output_path),
            },
            artifacts=[str(output_path)],
            duration_seconds=round(time.time() - start, 2),
        )
