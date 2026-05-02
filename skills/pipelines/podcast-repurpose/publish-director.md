# Publish Director - Podcast Repurpose Pipeline

## When To Use

Package podcast-derived clips and companion assets so that every short-form piece points back to the episode instead of drifting as an isolated fragment.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/publish_log.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["compose"]["render_report"]`, `state.artifacts["idea"]["brief"]`, `state.artifacts["script"]["script"]` | Outputs, source truth, chapters |
| Playbook | Active style playbook | Brand voice |

## Process

### 1. Link Every Clip Back To The Episode

Each short-form asset should reference:

- show name,
- episode title or number,
- guest name where relevant,
- full episode destination.

### 2. Tailor The Copy

- Shorts / Reels: hook-led, concise, **strict ≤30 seconds**. Engagement velocity in the first 30–60 minutes decides whether the algorithm expands reach; clips over 30s see watch-time decay that suppresses that signal.
- TikTok: cross-post only when the cost is zero (re-encode + caption). As of 2026-02 the algorithm deprioritizes accounts under 100K, so TikTok is no longer a primary battleground for sub-100K creators — do not author native TikTok cuts.
- LinkedIn: insight-led and more contextual
- YouTube companion: chapter-rich and search-friendly
- YouTube Shorts: same vertical asset as IG Reels — always auto cross-post, zero marginal cost.

### 2a. Plan The Collab Post

For every clip whose subject is a podcast guest (or any external creator who appears or is referenced in the clip), prepare an Instagram **Collab Post** invite:

- Pull `collab_handle` from the brief / scene plan metadata.
- Build the IG copy so it makes sense on **both** profiles — host + guest see the same post on their grids.
- Collab Posts are the highest-leverage growth tactic available in 2026 (2–5× organic reach overnight) and are the single biggest unused asset for podcasts whose guests have their own followings. Skipping them is a strategic loss, not a polish issue.
- If `collab_handle` is missing for a clip whose featured speaker is not the host, flag it in the publish log rather than silently shipping a non-collab post.

### 3. Sequence The Release

Recommended order:

1. strongest announcement clip
2. next-best insight clip
3. quote-led or guest-led follow-ups
4. remaining supporting clips

### 4. Store Cross-Linking Truth In Metadata

Recommended metadata keys:

- `episode_reference`
- `guest_tags`
- `collab_handle` — IG handle of the guest (or external creator) to invite as Collab Post co-author. One per clip. Null only when the clip is host-only.
- `cross_post_targets` — list of platforms to publish the same vertical asset to (e.g. `["instagram_reels", "youtube_shorts"]`). TikTok stays out by default.
- `posting_schedule`
- `clip_to_episode_map`

### 5. Quality Gate

- every clip points back to the episode,
- guest attribution is correct,
- copy matches the platform,
- the release order reflects actual clip strength,
- every guest-featuring clip has a `collab_handle` (or an explicit reason it is missing),
- every clip's vertical asset is ≤30 seconds for Reels / Shorts targets,
- TikTok is not silently treated as a primary surface.

## Common Pitfalls

- Publishing clips without clear episode references.
- Forgetting to tag or mention the guest when that audience matters.
- Reusing one caption style across every platform.
- Skipping the IG Collab invite — this is the single largest unused growth lever for guest-led podcasts.
- Letting Reels drift past 30 seconds; engagement velocity decays sharply and the algorithm reads the slower velocity as low quality.
- Authoring native TikTok variations as if it were a primary surface for sub-100K accounts in 2026.
