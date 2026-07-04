# Provenance Guard

A backend API system for AI content attribution on creative writing platforms. Classifies submitted text as likely AI-generated, likely human-written, or uncertain using two independent detection signals, returns a transparency label, supports creator appeals, enforces rate limiting, and maintains a structured audit log.

---

## Setup

```bash
git clone https://github.com/YOUR-USERNAME/ai201-project4-provenance-guard.git
cd ai201-project4-provenance-guard

python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Mac/Linux

pip install flask flask-limiter groq python-dotenv pytest

# Create .env
echo GROQ_API_KEY=your_key_here > .env

python app.py
```

Server runs at `http://localhost:5000`.

---

## Architecture

A submitted piece of text flows through two independent detection signals, a confidence scoring step, a transparency label generator, and an audit log write before the response is returned.

```
POST /submit {text, creator_id}
    │
    ▼
① Generate content_id (UUID)
    │
    ├──► Signal 1: LLM Classifier (Groq llama-3.3-70b-versatile)
    │    Semantic/stylistic holistic assessment → llm_score (0.0–1.0)
    │
    ├──► Signal 2: Stylometric Heuristics (pure Python)
    │    Sentence length variance + TTR + punctuation density → stylometric_score (0.0–1.0)
    │
    ▼
② Confidence = 0.65 × llm_score + 0.35 × stylometric_score
③ Attribution: likely_ai (≥0.70) / uncertain (0.40–0.69) / likely_human (<0.40)
④ Transparency label generated from attribution + confidence
⑤ Decision written to SQLite audit log
⑥ JSON response returned
```

Appeal flow: `POST /appeal {content_id, creator_reasoning}` → status updated to `under_review` → audit log updated → confirmation returned.

---

## API Endpoints

### POST /submit

Classify a piece of text content.

**Request:**
```json
{
  "text": "Your content here...",
  "creator_id": "creator-username"
}
```

**Response:**
```json
{
  "content_id": "3f7a2b1e-...",
  "attribution": "likely_ai",
  "confidence": 0.78,
  "llm_score": 0.82,
  "stylometric_score": 0.69,
  "label": "⚠️ AI-Generated Content\n\nOur system has determined...",
  "status": "classified"
}
```

**Rate limit:** 10 requests/minute, 100 requests/day per IP.

---

### POST /appeal

Contest a classification.

**Request:**
```json
{
  "content_id": "3f7a2b1e-...",
  "creator_reasoning": "I wrote this myself as part of my academic work."
}
```

**Response:**
```json
{
  "content_id": "3f7a2b1e-...",
  "status": "under_review",
  "message": "Your appeal has been received...",
  "original_attribution": "likely_ai",
  "original_confidence": 0.78
}
```

---

### GET /log

Return recent audit log entries.

**Query params:** `?limit=20` (default 20, max 100)

**Response:**
```json
{
  "entries": [...],
  "count": 20
}
```

---

## Detection Signals

### Signal 1: LLM Semantic Classifier

**What it measures:** Holistic semantic and stylistic coherence — whether the text reads as AI-generated based on vocabulary choices, phrasing conventions, hedging language, and overall register. Groq's `llama-3.3-70b-versatile` evaluates the text and returns an `ai_probability` float.

**Why chosen:** LLMs have internalized patterns from both human and AI text at scale. They recognize subtle markers (e.g., "it is important to note that", "furthermore", "in conclusion") that are more common in AI output, as well as natural imperfections and emotional authenticity markers common in human writing.

**What it misses:** Lightly edited AI output that has been humanized. Very formal human writing (academic papers, legal documents) that superficially resembles AI text. The signal makes a holistic judgment, not a fingerprint match.

**Weight:** 0.65 (primary signal)

---

### Signal 2: Stylometric Heuristics

**What it measures:** Three structural statistical properties:

1. **Sentence length variance** — AI text has low variance (sentences cluster around a mean); human writing varies widely. Normalized so low variance → higher AI score.
2. **Type-token ratio (TTR)** — unique words / total words. AI text reuses vocabulary more predictably. Low TTR → higher AI score.
3. **Punctuation density** — AI text uses punctuation moderately and consistently. Very high or very low density suggests human writing.

**Why chosen:** These signals are genuinely independent of the LLM signal — one is semantic, one is structural. Combining them makes the system more robust than either alone. Stylometrics can catch AI text the LLM might classify as uncertain.

**What it misses:** Short texts (under 20 words) — insufficient data for reliable statistics. Formal human writers with low sentence variance. Returns 0.5 fallback for very short texts.

**Weight:** 0.35 (supporting signal)

---

## Confidence Scoring

**Formula:**
```
confidence = (0.65 × llm_score) + (0.35 × stylometric_score)
```

**Threshold mapping:**
| Score range | Attribution | Meaning |
|---|---|---|
| 0.70 – 1.00 | `likely_ai` | Both signals agree: high AI likelihood |
| 0.40 – 0.69 | `uncertain` | Signals disagree or both ambiguous |
| 0.00 – 0.39 | `likely_human` | Both signals agree: high human likelihood |

**Why these thresholds:** A false positive (labeling human work as AI) is more harmful than a false negative on a creative platform. The `likely_ai` threshold is deliberately high (0.70) so the system only makes that strong claim when signals agree. The wide uncertain band (0.40–0.69) acknowledges the genuine difficulty of AI detection for borderline cases.

**Example submissions with different confidence scores:**

*High-confidence AI text:*
> "Artificial intelligence represents a transformative paradigm shift in modern society. It is important to note that while the benefits of AI are numerous, it is equally essential to consider the ethical implications."

```json
{
  "llm_score": 0.91,
  "stylometric_score": 0.74,
  "confidence": 0.852,
  "attribution": "likely_ai"
}
```

*Lower-confidence / uncertain text:*
> "ok so i finally tried that new ramen place downtown and honestly? underwhelming. the broth was fine but they put WAY too much sodium in it and i was thirsty for like three hours after."

```json
{
  "llm_score": 0.12,
  "stylometric_score": 0.18,
  "confidence": 0.141,
  "attribution": "likely_human"
}
```

---

## Transparency Labels

All three label variants, exactly as returned by the API:

### High-confidence AI (confidence ≥ 0.70)
```
⚠️ AI-Generated Content

Our system has determined with high confidence (XX%) that this content
was likely generated by an AI writing tool rather than written by a human author.

This classification is based on automated analysis and may not be perfect.
If you are the creator and believe this is incorrect, you can submit an appeal.

Confidence: XX% | Status: Classified
```

### Uncertain (confidence 0.40–0.69)
```
🔍 Authorship Uncertain

Our system could not confidently determine whether this content was written
by a human or generated by an AI tool. The signals we analyzed were mixed
or inconclusive (confidence: XX%).

If you are the creator, you may submit an appeal to provide context about
how this content was created.

Confidence: XX% | Status: Classified
```

### Likely human-written (confidence < 0.40)
```
✓ Likely Human-Written

Our system is confident (XX%) that this content was written by a human author.

Automated analysis can make mistakes. Readers should use their own judgment
when evaluating any content.

Confidence: XX% | Status: Classified
```

*(XX% = confidence × 100 for AI label; (1 − confidence) × 100 for human label)*

---

## Rate Limiting

**Limits:** 10 requests per minute, 100 requests per day per IP address.

**Reasoning:**
- A real creator submitting their own work would rarely need more than a few submissions per session — 10/minute is generous for legitimate use while blocking automated scripts.
- 100/day accommodates a prolific creator submitting multiple works across a full day without restriction, while making large-scale API abuse expensive.
- When the limit is exceeded, the API returns HTTP 429 with a clear message.

**Rate limit test output** (12 rapid requests — first 10 return 200, last 2 return 429):
```
200
200
200
200
200
200
200
200
200
200
429
```

---

## Appeals Workflow

Any creator can contest a classification by submitting `POST /appeal` with their `content_id` and a written explanation. The system:

1. Looks up the content_id in the audit log
2. Updates `status` from `"classified"` to `"under_review"`
3. Appends `appeal_reasoning` and `appeal_timestamp` to the log entry
4. Returns confirmation with the original classification details

No automated re-classification occurs. Appeals are queued for human review. A reviewer accessing `GET /log` sees the full record: original signals, confidence score, attribution, and the creator's reasoning.

---

## Audit Log

Every submission and appeal is logged to SQLite (`provenance.db`). Sample entries from `GET /log`:

```json
{
  "entries": [
    {
      "content_id": "3f7a2b1e-4c5d-...",
      "creator_id": "writer-123",
      "timestamp": "2026-06-19T14:32:10.123Z",
      "text_preview": "Artificial intelligence represents a transformative...",
      "attribution": "likely_ai",
      "confidence": 0.852,
      "llm_score": 0.91,
      "stylometric_score": 0.74,
      "label_text": "⚠️ AI-Generated Content...",
      "status": "under_review",
      "appeal_reasoning": "I wrote this myself as part of my academic work.",
      "appeal_timestamp": "2026-06-19T14:35:22.456Z"
    },
    {
      "content_id": "8a1b2c3d-...",
      "creator_id": "poet-456",
      "timestamp": "2026-06-19T14:28:05.789Z",
      "text_preview": "ok so i finally tried that new ramen place...",
      "attribution": "likely_human",
      "confidence": 0.141,
      "llm_score": 0.12,
      "stylometric_score": 0.18,
      "label_text": "✓ Likely Human-Written...",
      "status": "classified",
      "appeal_reasoning": null,
      "appeal_timestamp": null
    },
    {
      "content_id": "9c4e5f6a-...",
      "creator_id": "blogger-789",
      "timestamp": "2026-06-19T14:20:11.321Z",
      "text_preview": "I've been thinking a lot about remote work lately...",
      "attribution": "uncertain",
      "confidence": 0.512,
      "llm_score": 0.54,
      "stylometric_score": 0.46,
      "label_text": "🔍 Authorship Uncertain...",
      "status": "classified",
      "appeal_reasoning": null,
      "appeal_timestamp": null
    }
  ],
  "count": 3
}
```

---

## Known Limitations

**1. Formal human academic writing produces false positives.** A PhD dissertation paragraph has low sentence length variance, formal vocabulary, and consistent structure — all of which the stylometric signal will score as AI-like. The LLM signal may compound this if the writing resembles academic AI output. These texts will frequently land in the uncertain band or trigger a false positive `likely_ai` classification. The wide uncertain threshold and appeals workflow are the primary mitigations.

**2. Short texts (under 50 words) are unreliable.** The stylometric signal requires sufficient sample size to compute meaningful variance statistics. A haiku or two-sentence post gives almost no data. For short texts, the system falls back to relying entirely on the LLM signal, which itself has lower confidence on minimal content. Short texts should arguably always return `uncertain` — this is not currently enforced.

---

## Spec Reflection

**One way the spec helped:** The requirement to write out all three transparency label variants in plain English before building forced a crucial design decision upfront — specifically, what "confidence" means to a non-technical reader. Writing the labels first revealed that a raw score like "0.78" is meaningless without context, which led to converting scores to percentage phrasing ("Our system is 78% confident...") in the label text. The labels written in planning.md were used almost verbatim in implementation.

**One way implementation diverged:** The spec suggested storing the audit log in SQLite or structured JSON. The implementation uses SQLite with a proper schema and primary key on content_id. This was better than flat JSON because it makes the `UPDATE` operation for appeals trivial and prevents duplicate entries — but it added complexity that wasn't anticipated in planning. The `/log` endpoint required a `row_factory` to convert SQLite rows to dicts, which was not in the original plan.

---

## AI Usage

**Instance 1 — Flask skeleton and LLM signal:**
Claude was given the Detection Signals section (Signal 1 spec) and the architecture diagram from planning.md and asked to generate the Flask app skeleton with POST /submit and the `classify_with_llm()` function. The generated prompt for Groq asked the model to return "AI or human" as a string — this was revised before use to request a JSON object `{"ai_probability": 0.XX}` for reliable parsing. The regex fallback for parsing was added manually after observing that the LLM occasionally adds explanation text before the JSON.

**Instance 2 — Stylometric signal and confidence scoring:**
Claude was given the Signal 2 spec (three metrics with their normalization approach) and the Uncertainty Representation section and asked to generate `compute_stylometric_score()` and `compute_confidence()`. The generated sentence length variance normalization used a hard cap at std_dev=10 — this was adjusted to std_dev=12 after testing on real academic text showed the original cap was too aggressive, classifying even moderately varied human writing as AI-like. The TTR normalization thresholds were also revised from the generated values after testing on the four example inputs from Milestone 4.

---

## Testing

```bash
pytest tests/
```

```bash
# Test submission
curl -s -X POST http://localhost:5000/submit \
  -H "Content-Type: application/json" \
  -d '{"text": "Artificial intelligence represents a transformative paradigm shift.", "creator_id": "test-1"}' \
  | python -m json.tool

# Test appeal (use content_id from submit response)
curl -s -X POST http://localhost:5000/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "PASTE-ID-HERE", "creator_reasoning": "I wrote this myself."}' \
  | python -m json.tool

# View audit log
curl -s http://localhost:5000/log | python -m json.tool
```

---

## Repository Contents

```
├── app.py               # Flask API — all endpoints and detection logic
├── planning.md          # Architecture, signal specs, label design, AI tool plan
├── tests/
│   └── test_app.py      # pytest tests for signals, scoring, labels, endpoints
├── provenance.db        # SQLite audit log (auto-created on first run)
├── .env                 # API key (not committed)
├── .gitignore
└── README.md
```
