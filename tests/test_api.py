"""
API contract tests with a fake engine (no models or data needed).
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.api.app import create_app


class FakeRetriever:
    def __len__(self):
        return 3


class FakeEngine:
    retriever = FakeRetriever()

    def __init__(self):
        self.calls = []

    def triage(self, text, district=None, crop=None, month=None):
        self.calls.append((text, district, crop, month))
        return {"route": "ANSWER", "reply": "ok", "reasons": [{"code": "RETRIEVED_LOW_RISK", "detail": ""}]}

    def meta(self):
        return {"districts": [{"value": "PUNE", "label": "Pune"}], "crops": ["Wheat"], "kb_records": 3}


@pytest.fixture()
def client():
    engine = FakeEngine()
    with TestClient(create_app(engine=engine)) as c:
        c.engine = engine
        yield c


def test_console_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "KCC Triage Console" in r.text


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok", "kb_records": 3}


def test_meta_includes_probe_examples(client):
    body = client.get("/api/meta").json()
    assert body["districts"][0]["value"] == "PUNE"
    assert len(body["examples"]) > 10
    assert {"text", "lang", "expected", "route"} <= set(body["examples"][0])
    assert body["examples"][0]["route"] == "ANSWER"  # what the (fake) engine actually returned


def test_triage_passes_profile_through(client):
    client.engine.calls.clear()  # start-up already ran the example probes
    r = client.post("/api/triage", json={"text": "Varieties of wheat", "district": "PUNE", "crop": "Wheat", "month": 11})
    assert r.status_code == 200
    assert r.json()["route"] == "ANSWER"
    assert client.engine.calls[-1] == ("Varieties of wheat", "PUNE", "Wheat", 11)


@pytest.mark.parametrize("payload", [
    {"text": "   "},
    {"text": "x", "month": 13},
    {"text": "x" * 1001},
    {},
])
def test_triage_rejects_bad_input(client, payload):
    assert client.post("/api/triage", json=payload).status_code == 422
