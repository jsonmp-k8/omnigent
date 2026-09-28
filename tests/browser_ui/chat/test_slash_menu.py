"""Browser-only contracts for native slash-menu interaction."""

import time

import pytest
from playwright.sync_api import Page, Route, expect

_ROWS = "[data-testid^='slash-menu-item-']"


def _composer(page: Page):
    return page.get_by_label("Message the agent")


def test_slash_menu_tracks_real_focus_and_wrapping_keyboard_navigation(
    page: Page, chat_session_contract
) -> None:
    page.goto(chat_session_contract.url)
    composer = _composer(page)
    expect(composer).to_be_visible()
    composer.fill("/")

    rows = page.locator(_ROWS)
    assert rows.count() >= 2, "wrap navigation needs at least two matches"
    expect(rows.first).to_have_attribute("data-active", "true")
    composer.press("ArrowUp")
    expect(rows.last).to_have_attribute("data-active", "true")
    composer.press("ArrowDown")
    expect(rows.first).to_have_attribute("data-active", "true")

    composer.blur()
    expect(rows).to_have_count(0)


def test_enter_executes_a_substring_matched_builtin(page: Page, chat_session_contract) -> None:
    page.goto(chat_session_contract.url)
    composer = _composer(page)
    expect(composer).to_be_visible()

    composer.fill("/ontext")
    context_row = page.get_by_test_id("slash-menu-item-context")
    expect(context_row).to_have_attribute("data-active", "true")
    composer.press("Enter")

    expect(composer).to_have_value("")
    expect(page.get_by_text("No usage data yet — send a message first.")).to_be_visible()


@pytest.mark.parametrize("phase", ["discovery", "runner-starting", "sandbox-starting"])
def test_open_menu_accepts_an_async_skill_catalog(
    page: Page, chat_session_contract, phase: str
) -> None:
    if phase != "discovery":
        chat_session_contract.set_health(runner_online=False, host_online=True)
        chat_session_contract.update_session(created_at=time.time())
    if phase == "sandbox-starting":
        chat_session_contract.update_session(sandbox_status={"stage": "provisioning"})
    chat_session_contract.set_skills(
        [{"name": "code-review", "description": "Review the current change"}]
    )
    release_skills = chat_session_contract.hold_skills()
    page.goto(chat_session_contract.url)
    composer = _composer(page)
    expect(composer).to_be_visible()

    composer.fill("/")
    expect(page.get_by_test_id("slash-menu-item-help")).to_be_visible()
    expect(page.get_by_text("Loading skills…", exact=True)).to_be_visible()
    expect(
        page.get_by_text("Skills unavailable while disconnected.", exact=True)
    ).not_to_be_visible()
    composer.fill("/review")
    expect(composer).to_have_value("/review")
    assert len(chat_session_contract.skill_requests) == 1

    release_skills()
    expect(page.get_by_text("Loading skills…", exact=True)).not_to_be_visible()
    skill = page.get_by_test_id("slash-menu-item-code-review")
    expect(skill).to_have_attribute("data-active", "true")
    composer.press("Tab")
    expect(composer).to_have_value("/code-review ")


def test_slash_menu_stops_loading_when_sandbox_launch_fails(
    page: Page, chat_session_contract
) -> None:
    chat_session_contract.set_health(runner_online=False, host_online=True)
    chat_session_contract.update_session(
        created_at=time.time(),
        host_id=None,
        workspace=None,
        sandbox_status={"stage": "provisioning"},
    )
    page.goto(chat_session_contract.url)
    chat_session_contract.wait_for_stream()
    composer = _composer(page)
    expect(composer).to_be_visible()
    composer.fill("/")
    expect(page.get_by_text("Loading skills…", exact=True)).to_be_visible()

    chat_session_contract.emit(
        {
            "event": "session.sandbox_status",
            "data": {
                "type": "session.sandbox_status",
                "conversation_id": chat_session_contract.session_id,
                "stage": "failed",
                "error": "Test sandbox could not start",
            },
        }
    )

    expect(page.get_by_text("Loading skills…", exact=True)).not_to_be_visible()
    expect(page.get_by_text("Skills unavailable while disconnected.", exact=True)).to_be_visible()


def test_read_only_composer_skips_skill_discovery(page: Page, chat_session_contract) -> None:
    chat_session_contract.update_session(permission_level=1)
    page.goto(chat_session_contract.url)

    expect(_composer(page)).to_be_disabled()
    assert chat_session_contract.skill_requests == []


def test_native_file_paste_closes_the_slash_menu(page: Page, chat_session_contract) -> None:
    page.goto(chat_session_contract.url)
    composer = _composer(page)
    expect(composer).to_be_visible()
    composer.fill("/")
    expect(page.locator(_ROWS).first).to_be_visible()

    page.evaluate(
        """
        () => {
          const target = document.querySelector("textarea[aria-label='Message the agent']");
          if (!target) throw new Error("composer not found");
          const transfer = new DataTransfer();
          transfer.items.add(new File(["hello"], "notes.txt", { type: "text/plain" }));
          target.dispatchEvent(
            new ClipboardEvent("paste", {
              clipboardData: transfer,
              bubbles: true,
              cancelable: true,
            }),
          );
        }
        """
    )

    expect(page.get_by_text("notes.txt")).to_be_visible()
    expect(page.locator(_ROWS)).to_have_count(0)
    expect(composer).to_have_value("/")


@pytest.mark.parametrize("busy", [False, True])
def test_tab_completes_compact_and_explicit_send_renders_receipt(
    page: Page, chat_session_contract, busy: bool
) -> None:
    chat = chat_session_contract
    chat.harness = "claude-sdk"
    page.goto(chat.url)
    chat.wait_for_stream()
    composer = _composer(page)
    expect(composer).to_be_visible()
    if busy:
        chat.emit_busy("compact-test-turn")
        expect(page.get_by_role("button", name="Interrupt", exact=True)).to_be_visible()

    composer.fill("/comp")
    composer.press("Tab")
    expect(composer).to_have_value("/compact ")
    expect(composer).to_be_focused()
    assert chat.event_posts == []
    expect(page.get_by_test_id("slash-command-card")).to_have_count(0)

    composer.press("Enter")
    expect(composer).to_have_value("")
    if busy:
        expect(page.get_by_text("/compact", exact=True)).to_be_visible()
        assert chat.event_posts == []
        chat.emit_idle("compact-test-turn")

    bubble = page.locator('[data-role="user"]').filter(has_text="/compact")
    expect(bubble).to_be_visible()
    expect(bubble).to_have_count(1)
    assert [event["body"]["type"] for event in chat.event_posts] == ["compact"]


@pytest.mark.parametrize("harness", ["claude-sdk", "claude-native", "codex-native"])
@pytest.mark.parametrize("always_steer", [False, True])
@pytest.mark.parametrize("http_first", [False, True])
def test_compact_stays_visible_during_active_turn(
    page: Page,
    chat_session_contract,
    always_steer: bool,
    harness: str,
    http_first: bool,
    request: pytest.FixtureRequest,
) -> None:
    chat = chat_session_contract
    chat.harness = harness
    if harness.endswith("-native"):
        chat.update_session(
            labels={
                "omnigent.wrapper": "claude-code-native-ui"
                if harness == "claude-native"
                else "codex-native-ui"
            }
        )
    if harness == "codex-native":
        chat.contract.json(f"/v1/sessions/{chat.session_id}/codex_goal", {"goal": None})
    if always_steer:
        page.add_init_script("localStorage.setItem('omnigent:always-steer', 'true')")
    pending: list[Route] = []
    request.addfinalizer(lambda: [route.abort() for route in pending])

    def hold_compact(route: Route) -> None:
        if route.request.post_data_json.get("type") == "compact":
            pending.append(route)
        else:
            route.fallback()

    chat.contract.route(f"**/v1/sessions/{chat.session_id}/events", hold_compact)
    page.goto(chat.url)
    chat.wait_for_stream()
    chat.emit_busy("compact-active-turn")
    chat.emit(
        {
            "event": "response.created",
            "data": {"id": "compact-active-turn", "status": "in_progress", "output": []},
        }
    )
    chat.emit(
        {
            "event": "response.output_text.delta",
            "data": {"delta": "Still working on the task. " * 12, "message_id": "active-text"},
        }
    )
    expect(page.get_by_text("Still working on the task.", exact=False)).to_be_visible()
    composer = _composer(page)
    composer.fill("/compact")
    composer.press("Enter")
    if not always_steer:
        page.get_by_role("button", name="Send queued message now", exact=True).click()
    bubble = page.locator('[data-role="user"]').filter(has_text="/compact")
    expect(bubble).to_be_visible()
    assert len(pending) == 1
    chat.emit(
        {
            "event": "response.output_text.delta",
            "data": {"delta": "More work in progress. " * 12, "message_id": "active-text"},
        }
    )
    expect(page.get_by_text("More work in progress.", exact=False)).to_be_visible()
    expect(bubble).to_be_visible()
    if http_first:
        pending.pop().fulfill(json={"queued": False, "item_id": "compact-receipt"})
        expect(bubble).to_be_visible()
    chat.emit(
        {
            "event": "response.output_item.done",
            "data": {
                "item": {
                    "id": "compact-receipt",
                    "response_id": "compact-receipt-turn",
                    "type": "slash_command",
                    "kind": "command",
                    "name": "compact",
                    "arguments": "",
                    "model": "omnigent",
                }
            },
        }
    )
    if not http_first:
        pending.pop().fulfill(json={"queued": False, "item_id": "compact-receipt"})
    expect(bubble).to_have_count(1)
    expect(bubble).to_be_visible()
    chat.emit_idle("compact-active-turn")
    expect(bubble).to_be_visible()
    chat.set_items(
        [
            {
                "id": "compact-receipt",
                "response_id": "compact-receipt-turn",
                "type": "slash_command",
                "status": "completed",
                "kind": "command",
                "name": "compact",
                "arguments": "",
                "model": "omnigent",
            }
        ]
    )
    page.reload()
    expect(bubble).to_have_count(1)
    expect(bubble).to_be_visible()
