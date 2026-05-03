"""Hook scorer tool — three-layer audio + visual + LLM hook detection.

Delegates to ~/projects/hook_scorer_poc/hook_scorer.py running in its own venv.

Pipeline:
  1. ffmpeg → audio.wav (16kHz mono)
  2. faster-whisper → transcript.json (WhisperX-style with word-level timestamps)
  3. librosa per-second features → per-sentence aggregate → percentile tokenize
     (energy_label: explosive/high/normal/low + delta_label: sharp_jump/jump/flat)
  4. (optional) YuNet face detection + HSEMotion 8-class emotion + shot detection
  5. Filter candidate sentences (energy peak OR delta peak) → LLM scoring
     → 9-class hook taxonomy with primary + secondary types

Output: candidates.json with start/end/duration/primary_hook/headline/score/reason
fields, ranked by LLM. Compatible with downstream `om cut` / `om burn-subtitle`.
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
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ResumeSupport,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)

_HS_DIR = Path.home() / "projects/hook_scorer_poc"
_HS_PY = _HS_DIR / ".venv/bin/python"
_HS_SCRIPT = _HS_DIR / "hook_scorer.py"


class HookScorer(BaseTool):
    name = "hook_scorer"
    version = "0.8.0"
    tier = ToolTier.ANALYZE
    capability = "hook_detection"
    provider = "hook_scorer_poc"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.HYBRID  # local CV + Gemini cloud LLM (or local LM Studio)

    dependencies = [
        "cmd:ffmpeg",
        # Python venv at ~/projects/hook_scorer_poc/.venv
    ]
    install_instructions = (
        "Requires ~/projects/hook_scorer_poc/ with .venv/. "
        "See PoC repo for setup. Set GEMINI_API_KEY or run LM Studio server "
        "on http://localhost:1234/v1 with --provider lmstudio."
    )
    agent_skills = []

    capabilities = [
        "long_video_hook_detection",
        "audio_visual_llm_fusion",
        "9_class_hook_taxonomy",
        "shot_change_aware",
        "cjk_aware",
        "audio_only_or_video_input",
    ]
    supports = {
        "caching": True,
        "offline": False,  # Gemini default; LM Studio can be offline
        "cjk": True,
        "languages": ["zh-TW", "zh-CN", "en"],
        "video_input": True,
        "audio_only_input": True,
    }
    best_for = [
        "long-form podcast → viral short clips",
        "30-90 minute video hook discovery",
        "low-energy quotable line detection (delta-based)",
    ]
    not_good_for = [
        "<2 minute clips (LLM overhead dominates)",
        "non-CJK content where Breeze ASR is inferior to whisper-large-v3",
        "real-time streaming (LLM call adds 1-3 min)",
    ]

    input_schema = {
        "type": "object",
        "required": [],
        "properties": {
            "video_path": {"type": "string", "description": "input video file (enables visual stage)"},
            "audio_path": {"type": "string", "description": "input audio file (skip if video_path given)"},
            "transcript_path": {"type": "string", "description": "WhisperX-style JSON (skip ASR)"},
            "out_dir": {"type": "string", "description": "intermediate artifacts directory"},
            "out_path": {"type": "string", "description": "final candidates.json path"},
            "provider": {"type": "string", "enum": ["gemini", "lmstudio"], "default": "gemini"},
            "model": {"type": "string", "description": "LLM model id (provider-specific)"},
            "top_k": {"type": "integer", "default": 10},
            "frames_per_window": {"type": "integer", "default": 4},
            "asr_language": {"type": "string", "default": "zh"},
            "no_resume": {"type": "boolean", "default": False, "description": "force re-run all stages"},
        },
        "oneOf": [
            {"required": ["video_path"]},
            {"required": ["audio_path"]},
        ],
    }

    output_schema = {
        "type": "object",
        "properties": {
            "out_path": {"type": "string"},
            "n_picks": {"type": "integer"},
            "n_source_sentences": {"type": "integer"},
            "n_filtered_candidates": {"type": "integer"},
            "video_duration_sec": {"type": "number"},
            "has_visual": {"type": "boolean"},
            "provider": {"type": "string"},
            "model": {"type": "string"},
            "stage_timings_seconds": {
                "type": "object",
                "properties": {
                    "stage0_audio": {"type": "number"},
                    "stage1_asr": {"type": "number"},
                    "stage2_audio_feat": {"type": "number"},
                    "stage3_visual": {"type": "number"},
                    "stage4_llm": {"type": "number"},
                    "total": {"type": "number"},
                },
            },
        },
    }

    artifact_schema = {
        "candidates_json": {
            "type": "file",
            "description": "ranked hook candidates (consumed by om cut / om burn-subtitle)",
        },
        "audio_features_json": {"type": "file", "description": "per-sentence audio features"},
        "visual_features_json": {"type": "file", "description": "per-window visual features (optional)"},
        "transcript_json": {"type": "file", "description": "WhisperX-style transcript"},
    }

    resource_profile = ResourceProfile(
        cpu_cores=4, ram_mb=4096, vram_mb=0, disk_mb=2048, network_required=True,
    )

    resume_support = ResumeSupport.FROM_CHECKPOINT
    idempotency_key_fields = ["video_path", "audio_path", "transcript_path", "provider", "model", "top_k"]
    side_effects = []
    fallback = "viral_scorer"
    fallback_tools = ["viral_scorer", "lighthouse_saliency"]

    user_visible_verification = [
        "the candidates.json file exists and contains >= 1 candidate",
        "each candidate has start/end timestamps that fit within video duration",
        "primary_hook is one of the 9 known types",
    ]

    # ---- runtime ----

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        # Rough: ASR ~0.3-1.5x rt + visual ~5s/min + LLM ~60-180s
        if inputs.get("transcript_path"):
            asr = 0.0
        else:
            asr = 90.0  # 8-min audio average
        visual = 30.0 if inputs.get("video_path") else 0.0
        llm = 90.0
        return asr + visual + llm + 5.0

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        # Gemini 2.5 Pro free tier: ~zero. Conservative upper bound for API tier.
        return 0.0 if inputs.get("provider", "gemini") == "lmstudio" else 0.05

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        t0 = time.time()
        if not _HS_SCRIPT.exists():
            return ToolResult(success=False, error=f"hook_scorer script not found at {_HS_SCRIPT}")
        if not _HS_PY.exists():
            return ToolResult(success=False, error=f"hook_scorer venv missing at {_HS_PY}")

        out_dir = Path(inputs.get("out_dir") or "./hook_scorer_run")
        out_path = Path(inputs.get("out_path") or out_dir / "hooks.json")

        cmd = [str(_HS_PY), str(_HS_SCRIPT)]
        if inputs.get("video_path"):
            cmd += ["--video", str(inputs["video_path"])]
        if inputs.get("audio_path"):
            cmd += ["--audio", str(inputs["audio_path"])]
        if inputs.get("transcript_path"):
            cmd += ["--transcript", str(inputs["transcript_path"])]
        cmd += ["--out-dir", str(out_dir), "--out", str(out_path)]
        cmd += ["--provider", inputs.get("provider", "gemini")]
        if inputs.get("model"):
            cmd += ["--model", inputs["model"]]
        cmd += ["--top", str(inputs.get("top_k", 10))]
        cmd += ["--frames-per-window", str(inputs.get("frames_per_window", 4))]
        cmd += ["--asr-language", inputs.get("asr_language", "zh")]
        if inputs.get("no_resume"):
            cmd += ["--no-resume"]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        except subprocess.TimeoutExpired as e:
            return ToolResult(success=False, error=f"hook_scorer timeout after 3600s: {e}")
        if proc.returncode != 0:
            return ToolResult(
                success=False,
                error=f"hook_scorer failed (rc={proc.returncode}):\n"
                      f"STDOUT:\n{proc.stdout[-2000:]}\n\nSTDERR:\n{proc.stderr[-2000:]}",
                duration_seconds=time.time() - t0,
            )

        if not out_path.exists():
            return ToolResult(
                success=False,
                error=f"hook_scorer ran but output missing: {out_path}",
                duration_seconds=time.time() - t0,
            )

        try:
            result_data = json.loads(out_path.read_text())
        except json.JSONDecodeError as e:
            return ToolResult(success=False, error=f"output JSON invalid: {e}")

        # Parse stage timings from stderr (logged by orchestrator)
        timings: dict[str, float] = {}
        for line in proc.stdout.splitlines() + proc.stderr.splitlines():
            for stage in ("stage0_audio", "stage1_asr", "stage2_audio_feat",
                          "stage3_visual", "stage4_llm", "total"):
                if line.lstrip().startswith(stage):
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            timings[stage] = float(parts[-1].rstrip("s"))
                        except ValueError:
                            pass

        artifacts = [str(out_path)]
        for art in (out_dir / "audio_features.json",
                    out_dir / "visual_features.json",
                    out_dir / "transcript.json"):
            if art.exists():
                artifacts.append(str(art))

        return ToolResult(
            success=True,
            data={
                "out_path": str(out_path),
                "n_picks": result_data.get("n_picks", 0),
                "n_source_sentences": result_data.get("n_source_sentences", 0),
                "n_filtered_candidates": result_data.get("n_filtered_candidates", 0),
                "video_duration_sec": result_data.get("video_duration_sec", 0),
                "has_visual": result_data.get("has_visual", False),
                "provider": result_data.get("provider"),
                "model": result_data.get("model"),
                "stage_timings_seconds": timings,
                "top_3_preview": [
                    {
                        "rank": i + 1,
                        "start": c.get("start"),
                        "duration": c.get("duration"),
                        "primary_hook": c.get("primary_hook"),
                        "headline": c.get("headline"),
                        "score": c.get("score"),
                    }
                    for i, c in enumerate(result_data.get("candidates", [])[:3])
                ],
            },
            artifacts=artifacts,
            duration_seconds=time.time() - t0,
            model=result_data.get("model"),
        )
