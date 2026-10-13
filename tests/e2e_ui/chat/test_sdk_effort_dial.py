"""E2E: a claude-sdk session gets the composer's reasoning-effort dial.

A real Claude SDK session exposes the Anthropic effort ladder and persists a
selected value without sending a turn. The composer gate reads the harness's
declared effort family from ``/v1/harnesses`` (``claude-sdk`` → ``anthropic``),
so this runs on the real web SPA against a live server + runner with a real
``claude-sdk`` agent bundle: the catalog supplies the family and the runner
keeps the composer gear live. No LLM turn is needed:

1. the config gear opens and offers an Effort section;
2. the ladder is the anthropic family's (``max`` present — an ``openai`` or the
   base 3-level ladder would not offer it);
3. picking ``max`` persists ``reasoning_effort == "max"`` on the session row.
"""

from __future__ import annotations

import time
import uuid

import httpx
import yaml
from playwright.sync_api import Page, expect

from tests._helpers.session import bind_session_runner, bundle_files, post_session_bundle
from tests.e2e_ui.conftest import _ensure_runner_online, _server_state

_COMPOSER_PLACEHOLDER = "Send a message…"


def _claude_sdk_bundle(name: str, mock_llm_server_url: str) -> bytes:
    """A one-file claude-sdk agent bundle wired at the mock LLM.

    :param name: Agent name (unique per test run).
    :param mock_llm_server_url: Mock server base URL WITHOUT ``/v1``.
    """
    config = {
        "name": name,
        "prompt": "You are a terse assistant.",
        "executor": {
            "harness": "claude-sdk",
            "model": "claude-sonnet-4-6",
            "auth": {"type": "api_key", "api_key": "mock-key", "base_url": mock_llm_server_url},
        },
    }
    return bundle_files({f"{name}.yaml": yaml.safe_dump(config, sort_keys=False).encode()})


def _create_claude_sdk_session(base_url: str, runner_id: str, mock_llm_server_url: str) -> str:
    """Create a runner-bound session for a fresh claude-sdk agent."""
    bundle = _claude_sdk_bundle(f"sdk-effort-{uuid.uuid4().hex[:8]}", mock_llm_server_url)
    create_resp = post_session_bundle(httpx.post, f"{base_url}/v1/sessions", bundle, timeout=30.0)
    create_resp.raise_for_status()
    session_id = create_resp.json()["session_id"]
    bind_session_runner(httpx.patch, base_url, session_id, runner_id, timeout=10.0)
    return session_id


def _wait_for_session_effort(
    base_url: str, session_id: str, expected: str, timeout_s: float = 15.0
):
    """Poll the real session row until its reasoning_effort reaches *expected*."""
    deadline = time.monotonic() + timeout_s
    last: object = None
    while time.monotonic() < deadline:
        resp = httpx.get(f"{base_url}/v1/sessions/{session_id}", timeout=10.0)
        resp.raise_for_status()
        last = resp.json().get("reasoning_effort")
        if last == expected:
            return
        time.sleep(0.25)
    raise AssertionError(
        f"session {session_id} never persisted reasoning_effort={expected!r} (last={last!r})"
    )


def test_claude_sdk_session_offers_the_effort_dial(
    page: Page,
    live_server: str,
    mock_llm_server_url: str,
    tmp_path_factory,
) -> None:
    """A claude-sdk session shows the dial and persists a pick.

    A failure means the SDK gate regressed: the Effort section is missing for a
    non-native harness, the ladder is not the declared anthropic family's, or
    the pick never reached the session's ``reasoning_effort``.
    """
    _ensure_runner_online(live_server, tmp_path_factory)
    runner_id = str(_server_state["runner_id"])
    session_id = _create_claude_sdk_session(live_server, runner_id, mock_llm_server_url)

    page.goto(f"{live_server}/c/{session_id}")
    expect(page.get_by_placeholder(_COMPOSER_PLACEHOLDER)).to_be_visible(timeout=30_000)

    gear = page.get_by_test_id("composer-config-gear")
    expect(gear).to_be_visible(timeout=30_000)
    expect(gear).to_be_enabled(timeout=30_000)
    gear.click()
    page.get_by_test_id("composer-agent-edit").click()
    expect(page.get_by_test_id("composer-agent-config-menu")).to_be_visible()
    expect(page.get_by_test_id("composer-agent-efforts")).to_be_visible()

    # The anthropic ladder carries max; an openai/default ladder would not.
    expect(page.get_by_test_id("composer-agent-effort-max")).to_be_visible()

    page.get_by_test_id("composer-agent-effort-max").click()

    # The durable proof the dial reached the session: the persisted row.
    _wait_for_session_effort(live_server, session_id, "max")
