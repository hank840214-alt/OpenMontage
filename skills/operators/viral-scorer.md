# Viral Scorer — Podcast Clip Ranking

## When to Use

You are the **Viral Scorer** for the podcast-repurpose pipeline. You rank candidate clips by viral potential using a research-backed 6-dimension rubric, and return the top-N clips for production.

**Invoked between SCRIPT and SCENE_PLAN stages** when `deliverable_types` includes short-form social clips (Reels, Shorts, TikTok). Skip when the pipeline only produces companion video or quote cards.

## Scientific Basis

Research sources (see `~/Documents/Obsidian Vault/AI-Research/OSS-Research/2026-04-17-viral-video-science-research.md`):

| Paper | Finding | Weight |
|-------|---------|--------|
| Beyond Views (Shi 2018) | Topic + context predicts engagement at R²=0.77 before upload | 25% (topic) |
| Rhapsody (Park 2025) | Audio features + transcript > transcript-only for highlight detection | 20% (audio) |
| OpusClip / Facebook | 65% of viewers who pass 3s reach 10s; AI-optimized hooks +30% retention | 20% (hook) |
| Industry consensus 2025 | 85% of viewers watch with sound off; captions +40% completion | 15% (silent-readability) |
| OpusClip methodology | 4-segment structure (Hook / Value / Story / CTA) required | 10% (structure) |
| Understanding Virality (Gupta 2025) | VLM features predict engagement better than SSIM/FID | 10% (multimodal) |

## Prerequisites

| Resource | Purpose |
|----------|---------|
| `script` artifact | Full transcript with word-level timestamps |
| Source audio file | Original podcast MP3/WAV |
| `ClipFinder` (ClipsAI) | Candidate clip extraction from transcript |
| `CGDETRPredictor` or `QDDETRPredictor` (Lighthouse) | Audio moment retrieval scores |
| `brand.yaml` | Brand topic affinity (for topic scoring) |
| `playbook` | Target platform (IG Reels / YT Shorts / TikTok) |

## Tool Environment

All viral-scoring tools live in isolated venvs:

```bash
# ClipsAI requires DYLD_LIBRARY_PATH to resolve torchcodec's ffmpeg 6 dep
source ~/viral-tools/bin/env.sh
source ~/viral-tools/clipsai-venv/bin/activate

# Lighthouse in separate venv (torch 2.1.0 CPU)
source ~/viral-tools/lighthouse-venv/bin/activate
```

Never mix venvs — run each tool as a subprocess.

## Inputs

```yaml
viral_scorer_input:
  transcript_path: /abs/path/to/transcript.json        # WhisperX format, word-level
  source_audio_path: /abs/path/to/episode.mp3
  source_video_path: null                              # Optional, for multimodal scoring
  target_platform: instagram_reels                     # instagram_reels | youtube_shorts | tiktok
  target_clip_count: 5                                 # Top-N to return
  min_duration_s: 15
  max_duration_s: 60
  brand_topics: ["AI", "Claude Code", "productivity"]  # From brand.yaml
  language: zh-TW
```

## 6-Dimension Scoring Rubric

Each candidate clip gets a score in [0, 100] per dimension. Final score = weighted sum.

### 1. Topic Score (25%) — Cold-Start Engagement Predictor

**What it measures**: How well the clip's topic aligns with high-engagement categories and the brand's topic affinity.

**Method**:
1. Extract clip summary from transcript (first 2 sentences + key noun phrases)
2. Score against brand topics (semantic similarity via embeddings, 0-50 points)
3. Score against "viral topic categories" (50 points): reframes, contrarian claims, numbered lists, case studies, insider secrets, counterintuitive findings
4. Penalize if topic is evergreen-but-saturated (diet, productivity tips) unless brand is specialized there

**Signal**: A clip about "為什麼 AI 讓我的 podcast 腳本時間減半" scores higher than "今天天氣真好"

### 2. Hook Score (20%) — First 3 Seconds

**What it measures**: Strength of the opening 3 seconds at capturing attention.

**Method**:
1. Extract first 3 seconds of transcript
2. Classify hook type against the 10-type taxonomy (Bold Statement / Curiosity Gap / Question / Proof-First / Shock / Relatable / Value-First / Insider Secret / Urgent Warning / Pattern Interrupt)
3. Score the hook:
   - **Strong (70-100)**: Specific claim, question, or contrarian statement with concrete subject
   - **Medium (40-69)**: Generic but coherent value proposition
   - **Weak (0-39)**: Intro / logo / "so anyway" / pure filler
4. Boost if hook combines verbal + visual cue (multimodal hook)

**Signal**: "大多數人做 X 都做錯了，今天我告訴你正確的方式" scores >80. "嗨大家好，今天來聊聊..." scores <20.

### 3. Audio Score (20%) — Signal Quality + Emotional Arousal

**What it measures**: Audio features that correlate with viral moments — laughter, emphasis, pace change, pitch spikes. Rhapsody paper shows these beat transcript-only analysis.

**Method**:
1. Run Lighthouse `QDDETRPredictor` on the source audio with query "laughter, excited speech, emphatic statement"
2. Extract `pred_saliency_scores` for the clip window
3. Normalize: mean saliency × 100, capped at 100
4. Bonus for clips containing laugh/cheer/exclamation markers from transcript

**Signal**: A clip with rising pitch + laughter + emphatic "this is the part nobody tells you" > flat monotone.

### 4. Silent-Readability Score (15%) — 85% Sound-Off Rule

**What it measures**: Can the clip be understood with sound off? 85% of viewers default to muted.

**Method**:
1. Estimate caption density: words-per-second of the clip
   - 2.5-3.5 wps = optimal (100 points)
   - <1.5 or >4.5 wps = penalty (under 40)
2. Check if hook is verbalized (must be captionable in first 3s)
3. Flag if clip relies on audio-only cues (music stings, pauses used for comedy) — penalty 20 points
4. Bonus: transcript contains numbers, comparisons, or quotable phrases (easy to caption dramatically)

**Signal**: A clip with 3 wps and quotable numbers ("用這 3 個 prompts 省了我 4 小時") > a clip of rapid-fire anecdote.

### 5. Structure Score (10%) — 4-Segment Viral Formula

**What it measures**: Does the clip follow Hook / Value-Drop / Story-Payoff / CTA structure? Standalone clips need this even if sourced from longer episode.

**Method**:
1. Segment the clip transcript into temporal quarters
2. Check:
   - Q1 (0-25%): Contains a hook (see Hook Score)
   - Q2 (25-50%): Contains a concrete value or claim
   - Q3 (50-90%): Contains a story, example, or payoff
   - Q4 (last 10%): Contains resolution or implicit CTA
3. Score 25 points per segment present, max 100

**Signal**: Clips that resolve within the window > clips that cut mid-thought.

### 6. Multimodal Score (10%) — VLM Feature Alignment

**What it measures**: For video sources, visual engagement features (speaker expressiveness, scene variety, on-screen elements).

**Method**:
1. If `source_video_path` is null → default to 50 points (neutral)
2. If present: sample 3 frames from the clip, run Claude Vision with rubric:
   - Speaker facial expressiveness (0-40)
   - Scene variety / B-roll potential (0-30)
   - On-screen text / gesture emphasis (0-30)
3. Cache results per clip to avoid re-running on later passes

**Signal**: A clip with the speaker leaning in + hand gesture + expressive face > static head-on shot.

## Algorithm

```python
# Pseudocode — implement as a Python helper in ~/viral-tools/bin/viral_score.py
def score_clips(input_spec):
    # 1. Extract candidate clips with ClipsAI
    #    (subprocess in clipsai-venv with DYLD_LIBRARY_PATH set)
    candidates = run_clipsai(input_spec.transcript_path, input_spec.source_audio_path)
    # candidates = [{start, end, text, ...}, ...]

    # 2. Pre-compute Lighthouse audio saliency once for the full episode
    saliency = run_lighthouse_audio(input_spec.source_audio_path)
    # saliency = {"scores": [...], "sr": N} — per-second saliency

    # 3. Score each candidate
    scored = []
    for c in candidates:
        if not (input_spec.min_duration_s <= (c.end - c.start) <= input_spec.max_duration_s):
            continue

        scores = {
            "topic": topic_score(c, input_spec.brand_topics),
            "hook": hook_score(c),
            "audio": audio_score(c, saliency),
            "silent_readability": readability_score(c),
            "structure": structure_score(c),
            "multimodal": multimodal_score(c, input_spec.source_video_path),
        }
        weighted = (
            scores["topic"] * 0.25 +
            scores["hook"] * 0.20 +
            scores["audio"] * 0.20 +
            scores["silent_readability"] * 0.15 +
            scores["structure"] * 0.10 +
            scores["multimodal"] * 0.10
        )
        scored.append({"clip": c, "scores": scores, "final": weighted})

    # 4. Return top-N, but enforce topic diversity (no two top clips on same topic cluster)
    scored.sort(key=lambda x: x["final"], reverse=True)
    return diversify(scored)[:input_spec.target_clip_count]
```

## Outputs

Emits a `viral_ranking` artifact that feeds SCENE_PLAN:

```yaml
viral_ranking:
  generated_at: 2026-04-17T15:40:00+08:00
  input_hash: sha256:...                  # Of transcript + audio
  candidates_total: 23                    # From ClipsAI
  candidates_eligible: 14                 # After duration filter
  clips:
    - rank: 1
      start: 412.3
      end: 464.8
      duration: 52.5
      hook_preview: "大多數人用 AI 寫腳本都卡在這一步..."
      final_score: 78.4
      scores:
        topic: 82
        hook: 88
        audio: 71
        silent_readability: 75
        structure: 90
        multimodal: 50      # No video
      why_picked: "Strong contrarian hook + Rhapsody audio saliency spike at 430s + 4-segment structure resolved in window"
      risks: []
    - rank: 2
      ...
  rejected_samples:                       # For transparency / debugging
    - start: 102.0
      reason: "hook_score=18 (generic intro)"
```

## Gotchas

- **Language model**: topic & hook scoring uses Claude as LLM classifier. Cache per clip — don't re-score identical clips across runs.
- **Lighthouse weights**: First run downloads model weights (~500MB). Pre-warm the cache during pipeline setup.
- **ClipsAI on Chinese**: `ClipFinder` uses transcript text segmentation. For zh-TW, validate that WhisperX transcript has punctuation restored — ClipsAI segments on sentence boundaries.
- **Cold-start vs calibrated**: Score is *relative* — compare clips from same episode, not across episodes. Absolute thresholds for "worth posting" come from post-hoc engagement data (Producer-level decision, not Scorer).
- **Topic diversity**: Without `diversify()`, top-N can all be the same 3 minutes of a hot topic. Enforce at most 2 clips per 5-minute window of the source.

## Integration with Existing Stages

```
SCRIPT stage
  produces: script artifact (full transcript)
      │
      ▼
[NEW] VIRAL-SCORER stage
  consumes: script + source_audio
  produces: viral_ranking artifact
      │
      ▼
SCENE_PLAN stage
  consumes: script + viral_ranking (filters to top-N clips)
  produces: scene_plan
```

**Checkpoint**: Viral ranking is human-approvable in `guided` mode. Producer surfaces top-5 + rejected for user to veto before committing to SCENE_PLAN.

## Minimal CLI Usage

Once the `viral_score.py` helper exists:

```bash
source ~/viral-tools/bin/env.sh
python ~/viral-tools/bin/viral_score.py \
    --transcript ~/podcast-wip/ep_042/transcript.json \
    --audio ~/podcast-wip/ep_042/episode.mp3 \
    --platform instagram_reels \
    --top-n 5 \
    --lang zh-TW \
    --output viral_ranking.yaml
```
