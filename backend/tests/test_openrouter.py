"""OpenRouter assistant backend, tested with a fake HTTP client (no network, no cost)."""
import json

from sqlalchemy import select

from app.config import get_settings
from app.models import User
from app.services import assistant
from app.services.assistant import OpenRouterBackend, ToolBox


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class FakeClient:
    """Asks for one tool, then answers using the tool result."""

    def __init__(self, fail=False):
        self.requests, self.fail = [], fail

    def post(self, url, json=None):
        if self.fail:
            raise ConnectionError("network down")
        self.requests.append(json)
        if len(self.requests) == 1:
            return FakeResponse({"model": "anthropic/claude-haiku-5.5", "usage": {"cost": 0.0001},
                                 "choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [
                                     {"id": "call_1", "type": "function",
                                      "function": {"name": "get_mock_test_summary", "arguments": "{}"}}]}}]})
        return FakeResponse({"choices": [{"finish_reason": "stop",
                                          "message": {"content": "Physics is your weakest subject."}}]})


def _student(db):
    return db.scalar(select(User).where(User.email == "student@demo.test"))


def test_tool_loop_and_request_shape(db):
    client = FakeClient()
    reply = OpenRouterBackend(client=client).reply(ToolBox(db, _student(db)), [{"role": "user", "content": "weak subject?"}],
                                                   voice=True)
    assert reply.content == "Physics is your weakest subject." and reply.backend == "openrouter"
    assert [c["tool"] for c in reply.tool_calls] == ["get_mock_test_summary"]

    first, second = client.requests
    s = get_settings()
    assert first["models"][0] == s.openrouter_model and len(first["models"]) >= 2  # fallbacks
    assert first["provider"] == {"data_collection": "deny"}  # no providers that store/train on prompts
    assert first["max_tokens"] == 600  # voice replies stay short
    system = first["messages"][0]["content"][0]["text"]
    assert "read aloud" in system and "No markdown" in system
    assert {t["function"]["name"] for t in first["tools"]} >= {"predict_colleges", "search_documents"}
    tool_msg = second["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "call_1"
    assert "subjects" in json.loads(tool_msg["content"]) or "count" in json.loads(tool_msg["content"])


def test_bad_tool_arguments_are_reported_to_the_model(db):
    class BadArgs(FakeClient):
        def post(self, url, json=None):
            self.requests.append(json)
            if len(self.requests) == 1:
                return FakeResponse({"choices": [{"message": {"tool_calls": [
                    {"id": "c", "function": {"name": "estimate_cost", "arguments": "{not json"}}]}}]})
            return FakeResponse({"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]})
    client = BadArgs()
    OpenRouterBackend(client=client).reply(ToolBox(db, _student(db)), [{"role": "user", "content": "x"}])
    assert "Invalid tool call" in client.requests[1]["messages"][-1]["content"]


def test_provider_failure_falls_back_to_grounded_rules(db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "openrouter")
    monkeypatch.setattr(s, "openrouter_api_key", "test-key")
    monkeypatch.setattr(assistant, "OpenRouterBackend", lambda: OpenRouterBackend(client=FakeClient(fail=True)))
    reply = assistant.answer(db, _student(db), [{"role": "user", "content": "What documents do I need for counselling?"}],
                             voice=True)
    assert reply.backend == "rules" and reply.content


def test_voice_flag_accepted_by_api(student):
    r = student.post("/api/assistant/messages", json={"content": "How does AIQ differ from state quota?", "voice": True})
    assert r.status_code == 200 and r.json()["message"]["content"]
