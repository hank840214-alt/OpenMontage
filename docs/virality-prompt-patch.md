# Virality Prompt Patch — Integration Notes

來源：[SamurAIGPT/AI-Youtube-Shorts-Generator](https://github.com/SamurAIGPT/AI-Youtube-Shorts-Generator)
（`shorts_generator/highlights.py`，2026-04-29 fetched）

只抄 prompt 與分類；該 repo 的 cropping/clipping 走 muapi.ai SaaS、整體已 pivot 成 lead-gen、**程式碼本身沒有複製價值**。

---

## TL;DR：實際整合範圍很小

OpenMontage 既有的 viral pipeline 已經比 SamurAIGPT 強（6-dim rubric + Lighthouse audio saliency + 10-type hook taxonomy + ClipsAI 候選擷取），所以這份 patch **只新增 8 類 content-substance signals 到 script-director Step 3**，其餘部分都因 redundancy 不採用。

| 上游給的東西 | OpenMontage 對應 | 採用？ |
|---|---|---|
| 8 類 virality criteria（HOOK / EMOTIONAL PEAK / OPINION BOMB / REVELATION / CONFLICT / QUOTABLE / STORY PEAK / PRACTICAL VALUE）| `script-director.md` Step 3 原本 6 項清單（concise insights / surprising claims / emotional peaks / debates / practical advice / memorable phrasing），缺 OPINION BOMB / STORY PEAK 顯式描述 | ✅ 已採用 |
| Hook-must-open-first-3s rule | `hook_scorer.py` + `viral-scorer.md` Hook Score（已有 10-type taxonomy）| ❌ 已有更強版本 |
| Score 0–100 viral potential | `viral-scorer.md` 6-dim weighted（Topic 25 / Hook 20 / Audio 20 / Silent-Readability 15 / Structure 10 / Multimodal 10）| ❌ 已有更精細版本 |
| 4-segment Hook/Value/Story/CTA | `viral-scorer.md` Structure Score | ❌ 一致，已有 |
| Duration sweet spot 45–90s | `viral-scorer.md` `min/max_duration_s` config | ❌ 已是 config 化 |
| JSON output schema | `viral_ranking` artifact schema | ❌ 已有不同 schema |
| Long-video chunking 1200/1800/60s | OpenMontage 走 ClipsAI segmentation，再過 Lighthouse saliency 全片掃描 | ❌ 不需要 |
| Cross-chunk overlap > 50% dedupe | `viral-scorer.md` `diversify()`（topic diversity + 5-min 視窗節流）| ❌ 已有更聰明版本 |

**結論**：唯一缺口是 SamurAI 的 8 類 content-substance signals 比現有 6 項清單更顯式，所以併入 `script-director.md` Step 3。其他全部 redundant。

---

## 實際 patch（已 apply）

`skills/pipelines/podcast-repurpose/script-director.md` Step 3 從鬆散 6 項擴成嚴謹 8 類：

```
1. HOOK MOMENT
2. EMOTIONAL PEAK
3. OPINION BOMB         (新)
4. REVELATION           (顯式化)
5. CONFLICT / TENSION
6. QUOTABLE ONE-LINER
7. STORY PEAK           (新)
8. PRACTICAL VALUE
```

加附條：
- 強 highlight 通常 hit ≥ 2 signals（單一 signal 要例外執行才扛得住）
- 每個 candidate 在 metadata 記 `virality_signals: [hook, revelation]`，下游 viral-scorer / scene-director 不用重分類

排名是 impact 優先序（HOOK > 後面類型），與 OpenMontage 既有 Hook Score 20% 權重一致。

---

## 沒採用但留記錄的部分

下面這些本來抄了，但與 OpenMontage 既有設計衝突或 redundant，**先不導入**。如果未來 OpenMontage 改 LLM-only 路徑（不走 ClipsAI/Lighthouse），可從這裡撈：

### Highlight system prompt 全文（僅供 LLM-only fallback 參考）

```text
You are an elite short-form video editor who has studied thousands of viral
clips on TikTok, Instagram Reels, and YouTube Shorts. You know exactly what
makes viewers stop scrolling, watch to the end, and share.

{virality_criteria}

Content type: {content_type} | Density: {density}

Your task: identify the most viral-worthy highlights from the transcript.

Rules:
- Every highlight must open with a strong HOOK
- Duration sweet spot: 45-90s. Shorter (20-44s) only for one-liner. Longer
  (91-180s) only when story arc needs context
- Never cut mid-sentence — clips must feel complete
- Clips must not overlap significantly
- Score 0-100 on viral potential (not general quality)
- Generate at least {min_clips} highlights
- Identify the single best "hook_sentence" per clip
- Explain why viral in one sentence ("virality_reason")

Respond ONLY with valid JSON:
{"highlights":[{"title":"...","start_time":float,"end_time":float,
"score":int,"hook_sentence":"...","virality_reason":"..."}]}
```

`min_clips = max(2 if is_chunk else 3, int(duration_seconds / 90))`

### Content-type / density 預檢 prompt（pre-step）

```text
Analyze this video transcript sample and classify the content type.
Choose one: podcast, interview, tutorial, lecture, commentary, debate, vlog, other.
Also estimate content density: low, medium, or high.
Respond with JSON only: {"content_type": "...", "density": "..."}
```

Fallback：`{"content_type": "other", "density": "medium"}`。

### Chunking 常數

```python
CHUNK_SIZE_SECONDS    = 1200   # 20-min chunks
LONG_VIDEO_THRESHOLD  = 1800   # > 30 min 才切
CHUNK_OVERLAP_SECONDS = 60     # avoid 漏跨界 highlight
```

### Cross-chunk overlap > 50% dedupe

```python
def dedupe_highlights(highlights):
    highlights = sorted(highlights, key=lambda x: int(x.get("score", 0)), reverse=True)
    kept = []
    for h in highlights:
        h_start, h_end = float(h["start_time"]), float(h["end_time"])
        h_dur = h_end - h_start
        overlapping = any(
            (overlap := min(h_end, float(k["end_time"])) - max(h_start, float(k["start_time"])))
            > 0 and overlap > 0.5 * h_dur
            for k in kept
        )
        if not overlapping:
            kept.append(h)
    return kept
```

OpenMontage 既有 `diversify()` 做 5-min window 節流 + topic-cluster diversity，比這版更聰明，但若未來簡化就回來抄這段。
