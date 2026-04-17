"""ClipsAI clip detector — finds candidate clips from a WhisperX transcript.

Delegates to the clipsai-venv via an inline Python script (same approach used
by viral_score.py internally).  Returns candidate time windows without scoring.
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
    ToolTier,
)

_CLIPSAI_PY = Path.home() / "viral-tools/clipsai-venv/bin/python"

# Inline script sent to the venv's Python — mirrors viral_score.extract_candidates
_CLIPSAI_SCRIPT = r"""
import json
import sys
from pathlib import Path

transcript_path = Path(sys.argv[1])
min_s = float(sys.argv[2])
max_s = float(sys.argv[3])

with open(transcript_path) as f:
    data = json.load(f)

# Build word list from WhisperX segments
words = []
for seg in data.get("segments", []):
    for w in seg.get("words", []):
        if w.get("start") is None or w.get("end") is None:
            continue
        words.append({
            "start_time": float(w["start"]),
            "end_time": float(w["end"]),
            "text": w.get("word") or w.get("text") or "",
        })

if not words:
    json.dump({"clips": [], "error": "no_words"}, sys.stdout)
    sys.exit(0)

try:
    from clipsai import ClipFinder, Transcription
    transcription = Transcription({
        "source_software": "whisperx",
        "language": data.get("language", "zh"),
        "num_speakers": 1,
        "char_info": [],
        "start_time": words[0]["start_time"],
        "end_time": words[-1]["end_time"],
    })
    finder = ClipFinder(
        min_clip_duration=min_s,
        max_clip_duration=max_s,
    )
    clips = finder.find_clips(transcription=transcription)
    out = [{"start": c.start_time, "end": c.end_time} for c in clips]
    json.dump({"clips": out}, sys.stdout)
except Exception as e:
    # Fallback: greedy segment windows
    segments = data.get("segments", [])
    clips = []
    buf = []
    for seg in segments:
        if not seg.get("text"):
            continue
        if not buf:
            buf.append(seg)
            continue
        projected = seg["end"] - buf[0]["start"]
        if projected <= max_s:
            buf.append(seg)
        else:
            span = buf[-1]["end"] - buf[0]["start"]
            if span >= min_s:
                clips.append({"start": buf[0]["start"], "end": buf[-1]["end"]})
            buf = [seg]
    if buf:
        span = buf[-1]["end"] - buf[0]["start"]
        if span >= min_s:
            clips.append({"start": buf[0]["start"], "end": buf[-1]["end"]})
    json.dump({"clips": clips, "fallback": str(e)}, sys.stdout)
"""


class ClipsAIDetector(BaseTool):
    name = "clipsai_detector"
    version = "0.1.0"
    tier = ToolTier.ANALYZE
    capability = "clip_detection"
    provider = "clipsai"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies: list[str] = []
    install_instructions = (
        "Requires ~/viral-tools/clipsai-venv/ (Python 3.11 with ClipsAI + WhisperX).\n"
        "See ~/viral-tools/ for setup."
    )

    capabilities = ["podcast_clip_detection", "semantic_segmentation", "cjk_aware"]
    supports = {"offline": True, "cjk": True}
    best_for = [
        "podcast clip detection",
        "9:16 reframe candidates",
        "semantic boundary segmentation",
    ]
    not_good_for = [
        "music or non-speech audio",
        "clips longer than 120s (ClipsAI max)",
    ]

    input_schema = {
        "type": "object",
        "required": ["transcript_path", "source_audio_path"],
        "properties": {
            "transcript_path": {
                "type": "string",
                "description": "Path to WhisperX transcript JSON",
            },
            "source_audio_path": {
                "type": "string",
                "description": "Source audio file (used for duration reference)",
            },
            "min_duration_s": {"type": "number", "default": 15.0},
            "max_duration_s": {"type": "number", "default": 60.0},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "clips": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "number"},
                        "end": {"type": "number"},
                        "text": {"type": "string"},
                    },
                },
            },
            "clip_count": {"type": "integer"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=1024, vram_mb=0, disk_mb=0, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["timeout"])
    side_effects = []
    user_visible_verification = [
        "Verify clip count and durations in returned data",
    ]

    def check_dependencies(self) -> None:
        if not _CLIPSAI_PY.exists():
            raise DependencyError(
                f"clipsai-venv not found at {_CLIPSAI_PY}. {self.install_instructions}"
            )

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        try:
            self.check_dependencies()
        except DependencyError as e:
            return ToolResult(success=False, error=str(e))

        transcript_path = Path(inputs["transcript_path"])
        if not transcript_path.exists():
            return ToolResult(success=False, error=f"transcript_path not found: {transcript_path}")

        min_s = float(inputs.get("min_duration_s", 15.0))
        max_s = float(inputs.get("max_duration_s", 60.0))

        env = os.environ.copy()
        env["DYLD_LIBRARY_PATH"] = (
            f"/opt/homebrew/opt/ffmpeg@6/lib:{env.get('DYLD_LIBRARY_PATH', '')}"
        )

        try:
            proc = subprocess.run(
                [str(_CLIPSAI_PY), "-c", _CLIPSAI_SCRIPT,
                 str(transcript_path), str(min_s), str(max_s)],
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="ClipsAI detection timed out after 300s")

        if proc.returncode != 0:
            return ToolResult(
                success=False,
                error=f"ClipsAI exited {proc.returncode}:\n{proc.stderr[-400:]}",
            )

        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return ToolResult(
                success=False,
                error=f"Non-JSON output from ClipsAI: {proc.stdout[:200]}",
            )

        clips = payload.get("clips", [])

        # Enrich each clip with transcript text
        enriched = []
        try:
            with open(transcript_path) as f:
                transcript_data = json.load(f)
            for c in clips:
                segs = [
                    s for s in transcript_data.get("segments", [])
                    if s.get("end", 0) >= c["start"] and s.get("start", 0) <= c["end"]
                ]
                text = "".join(s.get("text", "") for s in segs).strip()
                enriched.append({
                    "start": round(c["start"], 2),
                    "end": round(c["end"], 2),
                    "duration": round(c["end"] - c["start"], 2),
                    "text": text,
                })
        except Exception:
            enriched = [
                {"start": round(c["start"], 2), "end": round(c["end"], 2),
                 "duration": round(c["end"] - c["start"], 2), "text": ""}
                for c in clips
            ]

        return ToolResult(
            success=True,
            data={
                "clips": enriched,
                "clip_count": len(enriched),
                "fallback_used": "fallback" in payload,
            },
            duration_seconds=round(time.time() - start, 2),
        )
