# Provenance Guard — planning.md
### AI201 · Project 4 · AI Content Attribution System

---

## Architecture Narrative

A piece of text enters the system via POST /submit. It is assigned a unique content_id, then passed through two independent detection signals: an LLM-based semantic classifier (Groq) and a stylometric heuristics analyzer (pure Python). Each signal produces a score between 0.0 and 1.0, where 1.0 means "maximally AI-like." The two scores are combined via weighted average into a single confidence score. That score is mapped to one of three transparency label variants and the full decision — content_id, creator_id, timestamp, both signal scores, combined confidence, attribution result, label text, and status — is written to a structured SQLite audit log. The response returned to the caller includes the content_id, attribution, confidence score, and the full label text.

For appeals: a creator submits POST /appeal with their content_id and reasoning. The system updates that record's status to "under_review" in the audit log, appends the appeal reasoning, and returns a confirmation. No automated re-classification occurs — the appeal is queued for human review.

---

## Detection Signals

### Signal 1: LLM Semantic Classifier (Groq)

**What it measures:** Holistic semantic and stylistic coherence — whether the text "reads" as AI-generated based on vocabulary choices, sentence structure patterns, phrasing conventions, and overall register. The LLM has been trained on both human and AI text and can recognize subtle patterns that are difficult to enumerate as rules.

**Output format:** A float between 0.0 and 1.0. The prompt instructs the model to return only a JSON object `{"ai_probability": 0.XX}`. If parsing fails, the signal returns 0.5 (uncertain fallback).

**What it misses:** The LLM can be fooled by AI text that has been lightly edited by a human, or by very formal human writing (academic papers, legal documents) that superficially resembles AI output. It also has no memory of what current AI models produce specifically — it's making a holistic judgment, not a fingerprint match.

**Weight in combined score:** 0.65 (primary signal — semantic judgment is more informative than structural statistics for short texts)

---

### Signal 2: Stylometric Heuristics

**What it measures:** Statistical structural properties that differ systematically between human and AI writing. AI text tends to be more uniform in sentence length, uses a narrower vocabulary relative to text length, and has more consistent punctuation density. Human writing shows more variance. Three specific metrics:

1. **Sentence length variance** — AI text has low variance (sentences cluster around a mean length); human text has high variance (short punchy sentences mixed with long complex ones). Low variance → higher AI score.
2. **Type-token ratio (TTR)** — vocabulary diversity: unique words / total words. AI text reuses vocabulary more predictably. Low TTR → higher AI score.
3. **Punctuation density** — AI text uses punctuation more consistently and sparingly. Measured as punctuation characters / total characters. Extremely high or extremely low density is a weak AI signal.

**Output format:** A float between 0.0 and 1.0, computed as a weighted average of the three normalized sub-metrics.

**What it misses:** Short texts (under ~100 words) produce unreliable stylometric scores because variance metrics need sufficient sample size. Formal human writers (academics, lawyers) often have low sentence length variance that stylometrics will incorrectly flag as AI-like.

**Weight in combined score:** 0.35 (supporting signal — structural statistics are informative but noisier on short texts)

---

## Uncertainty Representation

**Combined score formula:**
```
confidence = (0.65 × llm_score) + (0.35 × stylometric_score)
```

**What the score means:**
- **0.0** = maximally confident the text is human-written
- **0.5** = genuine uncertainty — signals disagree or both are ambiguous
- **1.0** = maximally confident the text is AI-generated

**Threshold mapping:**
| Score range | Attribution | Label variant |
|---|---|---|
| 0.00 – 0.39 | `likely_human` | High-confidence human label |
| 0.40 – 0.69 | `uncertain` | Uncertain label |
| 0.70 – 1.00 | `likely_ai` | High-confidence AI label |

**Why these thresholds:** A false positive (labeling human work as AI) is more harmful than a false negative on a creative platform — it damages a creator's reputation. The "likely_ai" threshold is deliberately set high (0.70) so the system only makes that strong claim when both signals agree with high confidence. The wide uncertain band (0.40–0.69) acknowledges that AI detection is genuinely hard for borderline cases.

**Calibration approach:** A score of 0.60 means "more AI-like than human-like, but not confident enough to assert it." It produces the uncertain label and explicitly invites the creator to appeal. A score of 0.85 means both signals are strongly in agreement — this is a high-confidence AI assertion.

---

## Transparency Label Design

### High-confidence AI (score ≥ 0.70)
```
⚠️ AI-Generated Content

Our system has determined with high confidence (SCORE%) that this content 
was likely generated by an AI writing tool rather than written by a human author.

This classification is based on automated analysis and may not be perfect.
If you are the creator and believe this is incorrect, you can submit an appeal.

Confidence: SCORE% | Status: Classified
```

### Uncertain (score 0.40–0.69)
```
🔍 Authorship Uncertain

Our system could not confidently determine whether this content was written 
by a human or generated by an AI tool. The signals we analyzed were mixed 
or inconclusive.

If you are the creator, you may submit an appeal to provide context about 
how this content was created.

Confidence: SCORE% | Status: Classified
```

### High-confidence human (score < 0.40)
```
✓ Likely Human-Written

Our system is confident (SCORE%) that this content was written by a human author.

Automated analysis can make mistakes. Readers should use their own judgment 
when evaluating any content.

Confidence: SCORE% | Status: Classified
```

*(SCORE% = (1 - confidence) × 100 for human label, confidence × 100 for AI label, expressed as certainty percentage)*

---

## Appeals Workflow

**Who can appeal:** Any creator who submitted content (identified by creator_id) can appeal any content_id associated with their submissions.

**What they provide:**
- `content_id` (str) — the ID returned by /submit
- `creator_reasoning` (str) — their explanation (e.g., "I wrote this myself; I am a non-native English speaker and my style may appear formal")

**What the system does on appeal:**
1. Looks up the content_id in the audit log
2. Updates `status` from `"classified"` to `"under_review"`
3. Appends `appeal_reasoning` and `appeal_timestamp` to the log entry
4. Returns a confirmation message with the content_id and new status

**What a human reviewer sees in the appeal queue (GET /log filtered by status):**
- Original classification: attribution result, confidence score, both signal scores
- Creator's reasoning text
- Appeal timestamp
- Original submission timestamp

**No automated re-classification** — appeals are queued for human review only.

---

## Anticipated Edge Cases

**Edge case 1: Formal human academic writing**
A PhD student submits a paragraph from their dissertation. Academic writing has low sentence length variance, formal vocabulary, consistent structure, and dense citation patterns — all of which stylometrics will score as AI-like. The LLM signal may also rate it as AI-leaning because it resembles academic AI output. This text would likely land in the uncertain band or a false positive. Mitigation: the wide uncertain band and easy appeals process are designed for exactly this case.

**Edge case 2: Short texts (under 50 words)**
A haiku or a two-sentence poem gives the stylometric signal almost no data to work with. Variance metrics on 3 sentences are meaningless. The stylometric score will be unreliable, and the combined score will rely almost entirely on the LLM signal. Short texts should arguably always land in the uncertain band regardless of LLM score — this is a known limitation not fully addressed in the current implementation.

**Edge case 3: Lightly edited AI output**
A creator uses AI to generate a draft, then rewrites 30% of it. The text will have some human stylometric fingerprints mixed with AI semantic patterns. Both signals will produce mid-range scores. This is genuinely ambiguous content and the uncertain label is the correct output — but the creator may still appeal, since they did contribute meaningfully.

---

## Architecture Diagram

```
POST /submit
  │  {text, creator_id}
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│                    Flask App                            │
│                                                         │
│  ① Generate content_id (UUID)                           │
│         │                                               │
│         ▼                                               │
│  ② Signal 1: LLM Classifier (Groq)                      │
│     send text → llama-3.3-70b-versatile                 │
│     parse {"ai_probability": X}                         │
│     → llm_score (float 0–1)                             │
│         │                                               │
│         ▼                                               │
│  ③ Signal 2: Stylometric Heuristics (pure Python)       │
│     sentence length variance → normalized score         │
│     type-token ratio → normalized score                 │
│     punctuation density → normalized score              │
│     weighted avg → stylometric_score (float 0–1)        │
│         │                                               │
│         ▼                                               │
│  ④ Confidence Scoring                                   │
│     confidence = 0.65×llm + 0.35×stylometric           │
│     attribution = likely_ai / uncertain / likely_human  │
│         │                                               │
│         ▼                                               │
│  ⑤ Transparency Label Generation                        │
│     score ≥ 0.70 → AI label                             │
│     score 0.40–0.69 → Uncertain label                   │
│     score < 0.40 → Human label                          │
│         │                                               │
│         ▼                                               │
│  ⑥ Audit Log Write (SQLite)                             │
│     content_id, creator_id, timestamp, attribution,     │
│     confidence, llm_score, stylometric_score,           │
│     label_text, status="classified"                     │
│         │                                               │
│         ▼                                               │
│  ⑦ Return JSON response                                 │
└─────────────────────────────────────────────────────────┘
  │
  ▼
{content_id, attribution, confidence, label, status}

─────────────────────────────────────────────────────────

POST /appeal
  │  {content_id, creator_reasoning}
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│  ① Look up content_id in audit log                      │
│  ② Update status → "under_review"                       │
│  ③ Append appeal_reasoning + appeal_timestamp           │
│  ④ Write updated entry to audit log                     │
│  ⑤ Return confirmation                                  │
└─────────────────────────────────────────────────────────┘

GET /log → returns recent audit log entries as JSON
```

---

## AI Tool Plan

**Milestone 3 (Flask skeleton + Signal 1):**
Input to AI: Detection Signals section (Signal 1 spec) + Architecture diagram
Request: Flask app skeleton with POST /submit route + `classify_with_llm()` function that calls Groq and returns a float
Verification: Call `classify_with_llm()` directly on 2 test inputs before wiring into endpoint; confirm output is a float between 0 and 1, not a string

**Milestone 4 (Signal 2 + confidence scoring):**
Input to AI: Detection Signals section (Signal 2 spec) + Uncertainty Representation section + Architecture diagram
Request: `compute_stylometric_score()` function + `compute_confidence()` combining function
Verification: Run both signals on clearly AI and clearly human text and confirm scores differ by at least 0.20; print individual signal scores to confirm neither is constant

**Milestone 5 (production layer):**
Input to AI: Transparency Label Design section + Appeals Workflow section + Architecture diagram
Request: `generate_label()` function mapping scores to label text + POST /appeal endpoint
Verification: Submit inputs that produce all three label variants; test /appeal with a content_id and confirm GET /log shows "under_review" status

---

*Last updated: Milestone 2 (pre-implementation)*
