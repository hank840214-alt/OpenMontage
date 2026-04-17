"""PycapsSubtitle — viral-style word-by-word caption burn using pycaps.

Delegates to ~/viral-tools/pycaps-venv/bin/pycaps render.
"""

from __future__ import annotations

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

_PYCAPS_CLI = Path.home() / "viral-tools/pycaps-venv/bin/pycaps"
_PYCAPS_PY = Path.home() / "viral-tools/pycaps-venv/bin/python"


class PycapsSubtitle(BaseTool):
    name = "pycaps_subtitle"
    version = "0.1.0"
    tier = ToolTier.ENHANCE
    capability = "subtitle_burn"
    provider = "pycaps"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies: list[str] = []
    install_instructions = (
        "Requires ~/viral-tools/pycaps-venv/ (Python 3.12 with pycaps[all]).\n"
        "See ~/viral-tools/ for setup."
    )

    capabilities = ["subtitle_burn", "word_by_word_captions", "css_styled_captions"]
    supports = {
        "offline": True,
        "cjk": True,
        "word_by_word": True,
        "templates": True,
    }
    best_for = ["viral-style word-by-word captions", "Instagram Reels subtitles", "zh-TW subtitle burn"]
    not_good_for = [
        "English-only emoji insertion (zh works without LLM key)",
        "ASS/SRT export without video (use subtitle_gen instead)",
    ]

    input_schema = {
        "type": "object",
        "required": ["video_path", "output_path"],
        "properties": {
            "video_path": {"type": "string", "description": "Input video file path"},
            "transcript_path": {
                "type": "string",
                "description": (
                    "Optional: path to whisper_json transcript for fast path "
                    "(skips re-transcription). Must be pycaps whisper_json format."
                ),
            },
            "template": {"type": "string", "default": "hype"},
            "output_path": {"type": "string", "description": "Output video file path"},
            "layout_align": {
                "type": "string",
                "default": "bottom",
                "enum": ["bottom", "center", "top"],
            },
            "video_quality": {
                "type": "string",
                "default": "middle",
                "enum": ["low", "middle", "high", "very_high"],
            },
            "lang": {"type": "string", "default": "zh"},
            "whisper_model": {"type": "string", "default": "base"},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "output_path": {"type": "string"},
            "template": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=4, ram_mb=1024, vram_mb=0, disk_mb=500, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=[])
    idempotency_key_fields = ["video_path", "template", "transcript_path"]
    side_effects = ["writes captioned video to output_path"]
    user_visible_verification = [
        "Watch first 5s of output video to verify word-by-word captions appear",
    ]

    def check_dependencies(self) -> None:
        if not _PYCAPS_CLI.exists() and not _PYCAPS_PY.exists():
            raise DependencyError(
                f"pycaps CLI not found at {_PYCAPS_CLI}. {self.install_instructions}"
            )
        # Quick smoke-test to confirm it loads
        try:
            subprocess.run(
                [str(_PYCAPS_CLI), "--help"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            raise DependencyError(f"pycaps CLI not functional: {e}")

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        try:
            self.check_dependencies()
        except DependencyError as e:
            return ToolResult(success=False, error=str(e))

        video_path = Path(inputs["video_path"])
        output_path = Path(inputs["output_path"])

        if not video_path.exists():
            return ToolResult(success=False, error=f"video_path not found: {video_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        template = inputs.get("template", "hype")
        layout_align = inputs.get("layout_align", "bottom")
        video_quality = inputs.get("video_quality", "middle")
        transcript_path = inputs.get("transcript_path")

        cmd = [
            str(_PYCAPS_CLI), "render",
            "--input", str(video_path),
            "--output", str(output_path),
            "--template", template,
            "--video-quality", video_quality,
            "--layout-align", layout_align,
        ]

        if transcript_path and Path(transcript_path).exists():
            # Fast path: skip re-transcription
            cmd += ["--transcript", transcript_path, "--transcript-format", "whisper_json"]
        else:
            # Let pycaps run Whisper internally
            lang = inputs.get("lang", "zh")
            whisper_model = inputs.get("whisper_model", "base")
            cmd += ["--lang", lang, "--whisper-model", whisper_model]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="pycaps render timed out after 600s")

        if proc.returncode != 0:
            return ToolResult(
                success=False,
                error=f"pycaps render exited {proc.returncode}:\n{proc.stderr[-500:]}",
            )

        if not output_path.exists():
            return ToolResult(success=False, error=f"Expected output not written: {output_path}")

        return ToolResult(
            success=True,
            data={
                "output_path": str(output_path),
                "template": template,
                "size_bytes": output_path.stat().st_size,
            },
            artifacts=[str(output_path)],
            duration_seconds=round(time.time() - start, 2),
        )
