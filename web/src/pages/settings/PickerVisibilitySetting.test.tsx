import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type * as AvailableAgentsModule from "@/hooks/useAvailableAgents";
import type { AvailableAgent } from "@/hooks/useAvailableAgents";
import {
  HIDDEN_PICKER_AGENTS_STORAGE_KEY,
  readHiddenPickerAgents,
  writeHiddenPickerAgents,
} from "@/lib/pickerEntryVisibility";
import { testAgent } from "@/test/agentFixtures";
import { PickerVisibilitySetting, pickerVisibilitySummary } from "./PickerVisibilitySetting";

const catalog = vi.hoisted(() => ({
  data: undefined as AvailableAgent[] | undefined,
  isLoading: false,
}));
vi.mock("@/hooks/useAvailableAgents", async (importOriginal) => ({
  ...(await importOriginal<typeof AvailableAgentsModule>()),
  useAgentCatalog: () => catalog,
}));

const claude = testAgent("agent-claude", "claude-native-ui", {
  display_name: "Claude Code",
  harness: "claude-native",
  builtin: true,
});
const codex = testAgent("agent-codex", "codex-native-ui", {
  display_name: "Codex",
  harness: "codex-native",
  builtin: true,
});
const polly = testAgent("agent-polly", "polly", {
  display_name: "Polly",
  harness: "claude-sdk",
  builtin: true,
});
const debby = testAgent("agent-debby", "debby", {
  display_name: "Debby",
  harness: "claude-sdk",
  builtin: true,
});

afterEach(() => {
  cleanup();
  window.localStorage.removeItem(HIDDEN_PICKER_AGENTS_STORAGE_KEY);
  catalog.data = undefined;
  catalog.isLoading = false;
});

describe("pickerVisibilitySummary", () => {
  const entries = [claude, codex, polly, debby];
  it.each([
    ["nothing hidden", [], "Showing all 4."],
    ["two hidden", ["debby", "codex-native-ui"], "Showing 2 of 4. Hidden: Codex and Debby."],
    ["a stale name only", ["removed-agent"], "Showing all 4."],
    [
      "more than three hidden",
      ["claude-native-ui", "codex-native-ui", "polly", "debby"],
      "Showing 0 of 4. Hidden: Claude Code, Codex, Polly, and 1 more.",
    ],
  ])("%s", (_label, hidden, expected) => {
    expect(pickerVisibilitySummary(entries, new Set(hidden))).toBe(expected);
  });
});

describe("PickerVisibilitySetting", () => {
  const option = (name: string) => screen.getByTestId(`picker-visibility-toggle-${name}`);
  const summary = () => screen.getByTestId("picker-visibility-summary");

  it("toggles an entry from the filterable checklist", () => {
    catalog.data = [claude, codex, polly];
    render(<PickerVisibilitySetting />);
    expect(summary()).toHaveTextContent("Showing all 3.");
    expect(screen.getByTestId("picker-visibility-reset")).toBeDisabled();

    fireEvent.click(screen.getByTestId("picker-visibility-edit"));
    expect(screen.getByText("Harnesses")).toBeInTheDocument();
    expect(screen.getByText("Agents")).toBeInTheDocument();
    expect(option("codex-native-ui")).toHaveAttribute("data-checked", "true");

    fireEvent.click(option("codex-native-ui"));
    expect(readHiddenPickerAgents()).toEqual(new Set(["codex-native-ui"]));
    expect(option("codex-native-ui")).toHaveAttribute("data-checked", "false");
    expect(summary()).toHaveTextContent("Showing 2 of 3. Hidden: Codex.");

    fireEvent.change(screen.getByPlaceholderText("Filter harnesses and agents…"), {
      target: { value: "poll" },
    });
    expect(screen.getByRole("option", { name: "Polly" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Codex" })).toBeNull();
  });

  it("restores every entry with Show all", () => {
    catalog.data = [claude, debby];
    writeHiddenPickerAgents(new Set(["debby"]));
    render(<PickerVisibilitySetting />);
    expect(summary()).toHaveTextContent("Showing 1 of 2. Hidden: Debby.");

    fireEvent.click(screen.getByTestId("picker-visibility-reset"));
    expect(readHiddenPickerAgents().size).toBe(0);
    expect(summary()).toHaveTextContent("Showing all 2.");
  });

  it("follows a change made outside the control", () => {
    catalog.data = [claude, codex];
    render(<PickerVisibilitySetting />);
    act(() => writeHiddenPickerAgents(new Set(["claude-native-ui"])));
    expect(summary()).toHaveTextContent("Showing 1 of 2. Hidden: Claude Code.");
  });

  it.each([
    ["while the catalog loads", true, "Loading agents…"],
    ["for an empty catalog", false, "No agents available on this server yet."],
  ])("explains the empty list %s", (_label, isLoading, expected) => {
    catalog.isLoading = isLoading;
    render(<PickerVisibilitySetting />);
    expect(summary()).toHaveTextContent(expected);
    expect(screen.getByTestId("picker-visibility-edit")).toBeDisabled();
  });
});
