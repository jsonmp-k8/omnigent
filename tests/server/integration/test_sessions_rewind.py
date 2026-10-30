"""Integration tests for moving a Claude session onto a truncated fork.

``POST /v1/sessions/{id}/rewind`` and a claude-sdk ``clear`` control both fork
the session (keeping only the history before a prompt, or none), bind the fork
to the source's host, workspace and live runner, and leave the source a notice
plus a ``session.superseded`` redirect. Real stores; the runner is a registered
tunnel whose HTTP side is a mock transport.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from omnigent.entities import MessageData, NewConversationItem
from omnigent.server.routes import sessions as sessions_module
from omnigent.server.routes.sessions import routes_core
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from tests.server.helpers import create_test_agent, register_test_runner

pytestmark = pytest.mark.asyncio

_RUNNER_ID = "runner_rewind"
_HOST_ID = "a1b2c3d4e5f60718293a4b5c6d7e8f90"


@dataclass
class _Runner:
    """What the fake runner received, and how it answers ``clear``."""

    clear_status: int = 200
    posts: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    superseded: list[tuple[str, str, str]] = field(default_factory=list)


@pytest_asyncio.fixture
async def runner(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[_Runner]:
    """Register a live runner and record what the server sends it."""
    state = _Runner()

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        state.posts.append((request.url.path, body))
        if body.get("type") == "clear":
            return httpx.Response(state.clear_status, json={"error": "busy"})
        return httpx.Response(201 if request.url.path == "/v1/sessions" else 200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://runner")
    register_test_runner(app, _RUNNER_ID)
    monkeypatch.setattr(sessions_module, "_get_runner_client", AsyncMock(return_value=client))
    monkeypatch.setattr(sessions_module, "_ensure_runner_relay_ready", AsyncMock())
    monkeypatch.setattr(
        routes_core,
        "_publish_session_superseded",
        lambda source, target, *, reason: state.superseded.append((source, target, reason)),
    )
    yield state
    app.state.tunnel_registry.deregister(_RUNNER_ID)
    await client.aclose()


def _as_harness(monkeypatch: pytest.MonkeyPatch, harness: str) -> None:
    """Make every session resolve to *harness*."""
    monkeypatch.setattr(sessions_module, "_resolve_harness", lambda *_a, **_k: harness)


async def _claude_session(
    client: httpx.AsyncClient,
    store: SqlAlchemyConversationStore,
    *,
    runner_id: str | None = _RUNNER_ID,
    host: bool = True,
) -> tuple[str, list[str]]:
    """Create a two-turn session with run settings and placement.

    :returns: The session id and its item ids (Q1, A1, Q2, A2).
    """
    agent = await create_test_agent(client)
    resp = await client.post(
        "/v1/sessions",
        json={
            "agent_id": agent["id"],
            "title": "Parser work",
            "labels": {"team": "core"},
            "model_override": "claude-opus-4-7",
            "reasoning_effort": "high",
            "terminal_launch_args": ["--permission-mode", "acceptEdits"],
        },
    )
    assert resp.status_code == 201, resp.text
    session_id = resp.json()["id"]
    for turn in (1, 2):
        store.append(
            session_id,
            [
                NewConversationItem(
                    type="message",
                    response_id=f"resp_{turn}",
                    data=MessageData(
                        role="user", content=[{"type": "input_text", "text": f"Q{turn}"}]
                    ),
                ),
                NewConversationItem(
                    type="message",
                    response_id=f"resp_{turn}",
                    data=MessageData(
                        role="assistant",
                        content=[{"type": "output_text", "text": f"A{turn}"}],
                        agent="test-agent",
                    ),
                ),
            ],
        )
    if host:
        store.set_host_id(session_id, _HOST_ID, "/work/repo", "feature/parser")
    if runner_id is not None:
        store.replace_runner_id(session_id, runner_id)
    return session_id, [item.id for item in store.list_items(session_id).data]


def _texts(store: SqlAlchemyConversationStore, session_id: str) -> list[str]:
    return [
        part["text"]
        for item in store.list_items(session_id).data
        if isinstance(item.data, MessageData)
        for part in item.data.content
    ]


@pytest.mark.parametrize("harness", ["claude-sdk", "claude-native"])
async def test_rewind_continues_on_a_truncated_fork_of_the_same_placement(
    client: httpx.AsyncClient,
    db_uri: str,
    runner: _Runner,
    monkeypatch: pytest.MonkeyPatch,
    harness: str,
) -> None:
    """Rewinding to a prompt forks just before it, on the source's runner and host."""
    _as_harness(monkeypatch, harness)
    store = SqlAlchemyConversationStore(db_uri)
    source_id, items = await _claude_session(client, store)

    resp = await client.post(f"/v1/sessions/{source_id}/rewind", json={"item_id": items[2]})

    assert resp.status_code == 200, resp.text
    new_id = resp.json()["session_id"]
    assert resp.json()["prompt"] == "Q2"
    assert _texts(store, new_id) == ["Q1", "A1"]
    fork = store.get_conversation(new_id)
    assert fork is not None
    assert (fork.runner_id, fork.host_id, fork.workspace, fork.git_branch) == (
        _RUNNER_ID,
        _HOST_ID,
        "/work/repo",
        "feature/parser",
    )
    assert (fork.model_override, fork.reasoning_effort) == ("claude-opus-4-7", "high")
    assert fork.terminal_launch_args == ["--permission-mode", "acceptEdits"]
    assert fork.labels["team"] == "core"
    assert fork.title == "Parser work"
    assert ("/v1/sessions", new_id) in [
        (path, body.get("session_id")) for path, body in runner.posts
    ]
    assert _texts(store, source_id)[:4] == ["Q1", "A1", "Q2", "A2"]
    notice = _texts(store, source_id)[-1]
    assert "/rewind" in notice and f"(/c/{new_id})" in notice
    assert runner.superseded == [(source_id, new_id, "rewind")]


async def test_rewind_to_the_first_prompt_starts_empty(
    client: httpx.AsyncClient,
    db_uri: str,
    runner: _Runner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing precedes the first prompt, so the fork starts like a /clear."""
    _as_harness(monkeypatch, "claude-sdk")
    store = SqlAlchemyConversationStore(db_uri)
    source_id, items = await _claude_session(client, store)

    resp = await client.post(f"/v1/sessions/{source_id}/rewind", json={"item_id": items[0]})

    assert resp.status_code == 200, resp.text
    assert resp.json()["prompt"] == "Q1"
    assert _texts(store, resp.json()["session_id"]) == []


async def test_rewind_with_an_offline_runner_binds_the_host_only(
    client: httpx.AsyncClient,
    db_uri: str,
    runner: _Runner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stopped runner leaves the fork on the host, which relaunches it on send."""
    _as_harness(monkeypatch, "claude-sdk")
    store = SqlAlchemyConversationStore(db_uri)
    source_id, items = await _claude_session(client, store, runner_id="runner_gone")

    resp = await client.post(f"/v1/sessions/{source_id}/rewind", json={"item_id": items[2]})

    assert resp.status_code == 200, resp.text
    fork = store.get_conversation(resp.json()["session_id"])
    assert fork is not None
    assert (fork.runner_id, fork.host_id, fork.workspace) == (None, _HOST_ID, "/work/repo")


@pytest.mark.parametrize(
    ("harness", "item_index", "placement", "status", "message"),
    [
        ("openai-agents", 2, "runner", 400, "/rewind is not available"),
        ("claude-sdk", 1, "runner", 400, "needs one of this session's prompts"),
        ("claude-sdk", None, "runner", 400, "needs one of this session's prompts"),
        ("claude-sdk", 2, "none", 503, "runner is offline"),
        ("claude-sdk", 2, "running", 400, "Stop the current turn"),
    ],
)
async def test_rewind_refusals_create_no_session(
    client: httpx.AsyncClient,
    db_uri: str,
    runner: _Runner,
    monkeypatch: pytest.MonkeyPatch,
    harness: str,
    item_index: int | None,
    placement: str,
    status: int,
    message: str,
) -> None:
    """Unsupported harnesses, non-prompts, no placement and busy turns are refused."""
    _as_harness(monkeypatch, harness)
    store = SqlAlchemyConversationStore(db_uri)
    source_id, items = await _claude_session(
        client,
        store,
        runner_id=None if placement == "none" else _RUNNER_ID,
        host=placement != "none",
    )
    if placement == "running":
        monkeypatch.setitem(sessions_module._session_status_cache, source_id, "running")
    before = len((await client.get("/v1/sessions")).json()["data"])

    resp = await client.post(
        f"/v1/sessions/{source_id}/rewind",
        json={"item_id": items[item_index] if item_index is not None else "msg_bogus"},
    )

    assert resp.status_code == status, resp.text
    assert message in resp.text
    assert len((await client.get("/v1/sessions")).json()["data"]) == before
    assert runner.superseded == []


async def test_claude_sdk_clear_moves_to_a_fresh_session(
    client: httpx.AsyncClient,
    db_uri: str,
    runner: _Runner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``clear`` frees the old SDK client, then continues in an empty bound session."""
    _as_harness(monkeypatch, "claude-sdk")
    store = SqlAlchemyConversationStore(db_uri)
    source_id, _items = await _claude_session(client, store)

    resp = await client.post(
        f"/v1/sessions/{source_id}/events", json={"type": "clear", "data": {}}
    )

    assert resp.status_code == 202, resp.text
    new_id = resp.json()["session_id"]
    sent = [(path, body.get("type") or body.get("session_id")) for path, body in runner.posts]
    # The old session's client is freed before the new session is initialized.
    assert sent.index((f"/v1/sessions/{source_id}/events", "clear")) < sent.index(
        ("/v1/sessions", new_id)
    )
    assert _texts(store, new_id) == []
    fork = store.get_conversation(new_id)
    assert fork is not None
    assert (fork.runner_id, fork.host_id, fork.model_override) == (
        _RUNNER_ID,
        _HOST_ID,
        "claude-opus-4-7",
    )
    # Untitled, so the first message names it like any new chat.
    assert fork.title is None
    assert "ended by `/clear`" in _texts(store, source_id)[-1]
    assert runner.superseded == [(source_id, new_id, "clear")]


async def test_claude_sdk_clear_refuses_while_the_runner_has_a_turn(
    client: httpx.AsyncClient,
    db_uri: str,
    runner: _Runner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A runner busy with a turn (409) refuses ``clear`` without creating a session."""
    _as_harness(monkeypatch, "claude-sdk")
    runner.clear_status = 409
    store = SqlAlchemyConversationStore(db_uri)
    source_id, _items = await _claude_session(client, store)

    resp = await client.post(
        f"/v1/sessions/{source_id}/events", json={"type": "clear", "data": {}}
    )

    assert resp.status_code == 400, resp.text
    assert "Stop the current turn" in resp.text
    assert runner.superseded == []
