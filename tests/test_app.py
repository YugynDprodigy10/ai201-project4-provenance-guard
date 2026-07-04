"""
tests/test_app.py
Run with: pytest tests/
"""

import json
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (
    app,
    compute_stylometric_score,
    compute_confidence,
    get_attribution,
    generate_label,
)

# ── Test client setup ─────────────────────────────────────────────────────────

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c

# ── Stylometric signal tests ──────────────────────────────────────────────────

AI_TEXT = (
    "Artificial intelligence represents a transformative paradigm shift in modern society. "
    "It is important to note that while the benefits of AI are numerous, it is equally "
    "essential to consider the ethical implications. Furthermore, stakeholders across "
    "various sectors must collaborate to ensure responsible deployment of these technologies."
)

HUMAN_TEXT = (
    "ok so i finally tried that new ramen place downtown and honestly? "
    "underwhelming. the broth was fine but they put WAY too much sodium in it and "
    "i was thirsty for like three hours after. my friend got the spicy version and "
    "said it was better. probably won't go back unless someone drags me there lol"
)

def test_stylometric_ai_text_scores_higher():
    ai_score = compute_stylometric_score(AI_TEXT)
    human_score = compute_stylometric_score(HUMAN_TEXT)
    assert ai_score > human_score, (
        f"AI text ({ai_score:.3f}) should score higher than human text ({human_score:.3f})"
    )

def test_stylometric_returns_float_in_range():
    score = compute_stylometric_score(AI_TEXT)
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0

def test_stylometric_short_text_returns_fallback():
    score = compute_stylometric_score("Hello world.")
    assert score == 0.5

def test_stylometric_no_exception_on_empty():
    try:
        score = compute_stylometric_score("")
        assert isinstance(score, float)
    except Exception as e:
        pytest.fail(f"compute_stylometric_score raised an exception on empty string: {e}")

# ── Confidence scoring tests ──────────────────────────────────────────────────

def test_confidence_weighted_correctly():
    score = compute_confidence(1.0, 0.0)
    assert abs(score - 0.65) < 0.01

def test_confidence_both_max():
    score = compute_confidence(1.0, 1.0)
    assert abs(score - 1.0) < 0.01

def test_confidence_both_min():
    score = compute_confidence(0.0, 0.0)
    assert abs(score - 0.0) < 0.01

def test_attribution_thresholds():
    assert get_attribution(0.75) == "likely_ai"
    assert get_attribution(0.70) == "likely_ai"
    assert get_attribution(0.55) == "uncertain"
    assert get_attribution(0.40) == "uncertain"
    assert get_attribution(0.39) == "likely_human"
    assert get_attribution(0.10) == "likely_human"

# ── Label generation tests ────────────────────────────────────────────────────

def test_label_ai_contains_warning():
    label = generate_label("likely_ai", 0.85)
    assert "AI-Generated" in label
    assert "85%" in label

def test_label_uncertain_contains_uncertain():
    label = generate_label("uncertain", 0.55)
    assert "Uncertain" in label

def test_label_human_contains_checkmark():
    label = generate_label("likely_human", 0.20)
    assert "Human-Written" in label

def test_all_three_label_variants_reachable():
    ai_label = generate_label("likely_ai", 0.80)
    uncertain_label = generate_label("uncertain", 0.50)
    human_label = generate_label("likely_human", 0.15)
    assert len(ai_label) > 0
    assert len(uncertain_label) > 0
    assert len(human_label) > 0
    # Verify they are all different
    assert ai_label != uncertain_label
    assert uncertain_label != human_label

# ── API endpoint tests ────────────────────────────────────────────────────────

def test_submit_returns_200(client):
    resp = client.post("/submit", json={
        "text": HUMAN_TEXT,
        "creator_id": "test-user-1"
    })
    assert resp.status_code == 200

def test_submit_returns_required_fields(client):
    resp = client.post("/submit", json={
        "text": AI_TEXT,
        "creator_id": "test-user-2"
    })
    data = resp.get_json()
    for field in ["content_id", "attribution", "confidence", "llm_score",
                  "stylometric_score", "label", "status"]:
        assert field in data, f"Missing field: {field}"

def test_submit_empty_text_returns_400(client):
    resp = client.post("/submit", json={"text": "", "creator_id": "u1"})
    assert resp.status_code == 400

def test_submit_missing_creator_id_returns_400(client):
    resp = client.post("/submit", json={"text": AI_TEXT})
    assert resp.status_code == 400

def test_submit_no_json_returns_400(client):
    resp = client.post("/submit", data="not json", content_type="text/plain")
    assert resp.status_code == 400

def test_appeal_unknown_content_id_returns_404(client):
    resp = client.post("/appeal", json={
        "content_id": "nonexistent-id-xyz",
        "creator_reasoning": "I wrote this myself."
    })
    assert resp.status_code == 404

def test_appeal_workflow(client):
    # Submit first
    submit_resp = client.post("/submit", json={
        "text": AI_TEXT,
        "creator_id": "appeal-test-user"
    })
    content_id = submit_resp.get_json()["content_id"]

    # Appeal it
    appeal_resp = client.post("/appeal", json={
        "content_id": content_id,
        "creator_reasoning": "I wrote this myself as part of an academic essay."
    })
    assert appeal_resp.status_code == 200
    appeal_data = appeal_resp.get_json()
    assert appeal_data["status"] == "under_review"

def test_log_returns_entries(client):
    # Submit something first
    client.post("/submit", json={"text": AI_TEXT, "creator_id": "log-test"})
    resp = client.get("/log")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "entries" in data
    assert "count" in data
    assert data["count"] >= 1
