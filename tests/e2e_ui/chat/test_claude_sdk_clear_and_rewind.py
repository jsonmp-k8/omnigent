"""E2E: ``/rewind`` and ``/clear`` in a claude-sdk session's composer.

A real Claude CLI (via the Agent SDK) answers from the mock LLM on the shared
runner. ``/rewind`` lists the session's prompts; choosing the second one moves
the view to a new session holding only the first turn, with the chosen prompt
back in the composer, while the original keeps a notice linking to it.
``/clear`` then moves to an empty session on the same runner.
"""

from __future__ import annotations

import re
import uuid

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e_ui.chat.test_claude_sdk_terminated_cli_recovery import (
    _create_claude_sdk_session,
)
from tests.e2e_ui.conftest import _ensure_runner_online, _server_state, configure_mock_llm

_ASSISTANT = '[data-testid="message-bubble"][data-role="assistant"]'
_USER = '[data-testid="message-bubble"][data-role="user"]'
_WORKING = '[data-testid="working-indicator"]'


def _send(page: Page, text: str) -> None:
    """Send *text* from the composer and wait for the turn to settle."""
    composer = page.get_by_placeholder("Send a message…")
    composer.fill(text)
    page.get_by_role("button", name="Send", exact=True).click()


def _run_command(page: Page, typed: str, command: str) -> None:
    """Type *typed* and pick *command* from the slash menu."""
    page.get_by_placeholder("Send a message…").fill(typed)
    page.get_by_test_id(f"slash-menu-item-{command}").click()


@pytest.mark.timeout(600)
def test_claude_sdk_rewind_then_clear_follow_the_new_sessions(
    page: Page,
    live_server: str,
    mock_llm_server_url: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Rewind to the second prompt, then clear, from the composer."""
    _ensure_runner_online(live_server, tmp_path_factory)
    runner_id = str(_server_state["runner_id"])
    source_id, _agent_name = _create_claude_sdk_session(
        live_server, runner_id, mock_llm_server_url
    )
    uid = uuid.uuid4().hex[:6]
    first, second = f"first-prompt-{uid}", f"second-prompt-{uid}"
    for token, reply in ((first, "ack one"), (second, "ack two")):
        configure_mock_llm(
            mock_llm_server_url, [{"text": reply}] * 20, key=f"rewind-{token}", match=token
        )

    page.goto(f"{live_server}/c/{source_id}")
    _send(page, f"Say ack. {first}")
    expect(page.locator(_ASSISTANT).filter(has_text="ack one")).to_be_visible(timeout=180_000)
    expect(page.locator(_WORKING)).to_have_count(0, timeout=180_000)
    _send(page, f"Say ack. {second}")
    expect(page.locator(_ASSISTANT).filter(has_text="ack two")).to_be_visible(timeout=180_000)
    expect(page.locator(_WORKING)).to_have_count(0, timeout=180_000)

    _run_command(page, "/rew", "rewind")
    rows = page.get_by_test_id("rewind-prompt")
    expect(rows).to_have_count(2)
    expect(rows.first).to_contain_text(second)
    rows.first.click()

    expect(page).not_to_have_url(re.compile(f"/c/{source_id}$"), timeout=30_000)
    rewound_id = page.url.rsplit("/c/", 1)[1]
    expect(page.get_by_placeholder("Send a message…")).to_have_value(f"Say ack. {second}")
    expect(page.locator(_USER).filter(has_text=first)).to_be_visible()
    expect(page.locator(_USER).filter(has_text=second)).to_have_count(0)
    source_items = httpx.get(
        f"{live_server}/v1/sessions/{source_id}/items", params={"order": "desc", "limit": 5}
    ).json()["data"]
    assert any(
        f"/c/{rewound_id}" in part.get("text", "")
        for item in source_items
        for part in item.get("content", [])
    ), source_items

    _run_command(page, "/cle", "clear")
    expect(page).not_to_have_url(re.compile(f"/c/{rewound_id}$"), timeout=30_000)
    cleared_id = page.url.rsplit("/c/", 1)[1]
    assert cleared_id != source_id
    expect(page.locator(_USER)).to_have_count(0)
    cleared = httpx.get(f"{live_server}/v1/sessions/{cleared_id}").json()
    assert cleared["runner_id"] == runner_id
