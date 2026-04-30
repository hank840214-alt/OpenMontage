# Script Director - Podcast Repurpose Pipeline

## When To Use

This stage creates the transcript truth, speaker attribution, highlight set, and chapter structure that every later stage depends on.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/script.schema.json` | Artifact validation |
| Prior artifact | `state.artifacts["idea"]["brief"]` | Deliverable mix and source truth |
| Tools | `transcriber`, `audio_enhance` | Diarized transcript and cleanup |

## Process

### 1. Protect Transcript Quality

If the source audio is weak, use `audio_enhance` before or alongside transcription. Speaker diarization quality directly affects quote attribution and clip quality.

### 2. Produce A Speaker-Aware Transcript

Diarization is not optional for multi-speaker episodes. Verify speaker mapping early and store the richer diarization detail in `script.metadata`.

Recommended metadata keys:

- `speaker_map`
- `transcript_path`
- `chapter_candidates`
- `highlight_candidates`
- `rejected_highlights`

### 3. Rank Highlight Moments

Use the episode transcript to find moments matching one or more of these eight virality signals (ranked by impact — clips opening with HOOK or EMOTIONAL PEAK convert better than CONFLICT or PRACTICAL VALUE alone):

1. **HOOK MOMENT** — a line that creates immediate curiosity in the first 3 seconds ("The secret is...", "Nobody talks about...", "I was completely wrong about...").
2. **EMOTIONAL PEAK** — genuine surprise, laughter, anger, vulnerability, excitement; raw unscripted reaction.
3. **OPINION BOMB** — strong, polarizing or counter-intuitive claim that triggers agree/disagree.
4. **REVELATION** — surprising fact, stat, or confession that reframes how the listener thinks.
5. **CONFLICT / TENSION** — disagreement, pushback, or a problem confronted head-on. (Solo podcasts: internal-conflict reframes count.)
6. **QUOTABLE ONE-LINER** — a sentence that works as a standalone quote card.
7. **STORY PEAK** — the climax or twist of an anecdote; the payoff moment.
8. **PRACTICAL VALUE** — a concrete tip, hack, or insight the listener can immediately apply.

A strong highlight typically lands at least two signals — e.g. HOOK + REVELATION, or STORY PEAK + EMOTIONAL PEAK. Single-signal clips usually need exceptional execution to carry alone.

Every highlight should also be evaluated for:

- standalone clarity,
- hook strength,
- attribution confidence,
- platform fit.

For each candidate, record which signals it hits in metadata (`virality_signals: [hook, revelation]`) so downstream stages and the viral scorer can act on it without re-classifying.

### 4. Build Chapters For Long-Form Packaging

If the user wants a full-episode companion asset, identify the topic shifts now. These become chapter markers and later visual transition points.

### 5. Keep The Schema Clean

Use `sections[]` for the structured production-facing segments and put the richer highlight inventory in metadata.

### 6. Quality Gate

- speaker attribution is trustworthy,
- the highlight set is strong enough for the requested deliverables,
- weak clips are rejected instead of padded,
- chapter markers cover the long-form conversation cleanly.

### Mid-Production Fact Verification

If you encounter uncertainty during script writing:
- Use `web_search` to verify factual claims before committing them to the script
- Use `web_search` to find reference images for visual accuracy
- Log verification in the decision log: `category="visual_accuracy_check"`

Every factual claim in the script should be traceable to the `research_brief`.
If you make a claim that isn't in the research, do additional research and
add the source. Do not invent statistics, dates, or attributions.

## Common Pitfalls

- Treating diarization errors as minor when they change who said the quote.
- Selecting clips that need too much earlier context.
- Overfitting the batch to one section of the episode.
