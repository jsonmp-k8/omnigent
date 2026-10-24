// A deployment can name which agents New Chat offers (server config
// `restrict_to_agent_names`). These cover what that does to the menu: the
// roster, the groups that stop making sense, and the empty case.
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AgentHarnessPicker } from "./NewChatDialog";
import type { AvailableAgent } from "@/hooks/useAvailableAgents";
import type { Host } from "@/hooks/useHosts";
import { CapabilitiesProvider } from "@/lib/CapabilitiesContext";
import { FALLBACK_SERVER_INFO } from "@/lib/capabilities";
import { StoryQueryRouter } from "@/storybook/StoryProviders";
import { TooltipProvider } from "@/components/ui/tooltip";

const agent = (
  overrides: Partial<AvailableAgent> &
    Pick<AvailableAgent, "id" | "name" | "display_name" | "harness">,
): AvailableAgent => ({ description: null, skills: [], builtin: true, ...overrides });

const claude = agent({
  id: "agent-claude",
  name: "claude-native-ui",
  display_name: "Claude Code",
  harness: "claude-native",
});
const codex = agent({
  id: "agent-codex",
  name: "codex-native-ui",
  display_name: "Codex",
  harness: "codex-native",
});
const polly = agent({
  id: "agent-polly",
  name: "polly",
  display_name: "Polly",
  harness: null,
});

const readyHost: Host = {
  host_id: "host-1",
  name: "laptop",
  owner: "me",
  status: "online",
  configured_harnesses: {
    "claude-native": true,
    "codex-native": true,
    "pi-native": true,
  },
};

function renderPicker(props: {
  harnessEntries: AvailableAgent[];
  agentEntries?: AvailableAgent[];
  restrictToAgentNames?: string[];
  defaultAgentName?: string | null;
}) {
  const restrict = props.restrictToAgentNames;
  return render(
    <CapabilitiesProvider
      info={{
        ...FALLBACK_SERVER_INFO,
        picker: {
          restrictToAgentNames: new Set(restrict ?? []),
          defaultAgentName: props.defaultAgentName ?? null,
        },
      }}
    >
      <StoryQueryRouter>
        <TooltipProvider>
          <AgentHarnessPicker
            agentEntries={props.agentEntries ?? []}
            harnessEntries={props.harnessEntries}
            effectiveAgentId={null}
            agentLabel="Picker"
            hasAgents
            host={readyHost}
            onSelectAgent={() => undefined}
            pendingAgent={null}
            pendingAgentId="pending-agent"
            onSelectPending={() => undefined}
            onCreateCustomAgent={() => undefined}
            sandboxSelected={false}
            allowCreateCustomAgent
          />
        </TooltipProvider>
      </StoryQueryRouter>
    </CapabilitiesProvider>,
  );
}

const openPicker = () => userEvent.click(screen.getByTestId("new-chat-landing-agent-select"));

afterEach(cleanup);

describe("a curated New Chat picker", () => {
  it("offers only the named agents, in the configured order", async () => {
    renderPicker({
      harnessEntries: [claude, codex],
      agentEntries: [polly],
      // The deployment's own pick leads, which is the point of configuring it.
      restrictToAgentNames: ["polly", "codex-native-ui"],
    });
    await openPicker();

    const curated = screen.getByTestId("new-chat-landing-curated");
    const labels = [...curated.querySelectorAll("[data-harness-menu-choice-label]")].map(
      (node) => node.textContent,
    );
    expect(labels).toEqual(["Polly", "Codex"]);
    expect(screen.queryByText("Claude Code")).toBeNull();
  });

  it("drops the groups and actions that can no longer lead anywhere", async () => {
    renderPicker({
      harnessEntries: [claude, codex],
      agentEntries: [polly],
      restrictToAgentNames: ["polly", "codex-native-ui"],
    });
    await openPicker();

    // No Harnesses heading: the roster is one list, not a split one.
    expect(screen.queryByText("Harnesses")).toBeNull();
    // Nothing is folded away, so there is no "Other..." to open.
    expect(screen.queryByTestId("new-chat-landing-harness-more")).toBeNull();
    expect(screen.queryByTestId("new-chat-landing-custom-agents")).toBeNull();
    // Creating an agent would produce one the picker then refuses to show.
    expect(screen.queryByTestId("new-chat-landing-create-agent")).toBeNull();
  });

  it("collapses to the single agent a deployment names", async () => {
    renderPicker({
      harnessEntries: [claude, codex],
      agentEntries: [polly],
      restrictToAgentNames: ["polly"],
    });
    await openPicker();

    const curated = screen.getByTestId("new-chat-landing-curated");
    const labels = [...curated.querySelectorAll("[data-harness-menu-choice-label]")].map(
      (node) => node.textContent,
    );
    expect(labels).toEqual(["Polly"]);
    expect(screen.queryByText("Harnesses")).toBeNull();
  });

  it("says so when the restriction matches nothing, rather than opening blank", async () => {
    renderPicker({
      harnessEntries: [claude, codex],
      agentEntries: [polly],
      // A typo, or an agent this server does not have.
      restrictToAgentNames: ["not-installed"],
    });
    await openPicker();

    const empty = screen.getByTestId("new-chat-landing-no-agents");
    expect(empty).toHaveTextContent("No agents are available here");
    expect(empty).toHaveTextContent("limits which agents New Chat offers");
  });

  it("leaves the grouped menu alone when nothing is configured", async () => {
    renderPicker({ harnessEntries: [claude, codex], agentEntries: [polly] });
    await openPicker();

    expect(screen.queryByTestId("new-chat-landing-curated")).toBeNull();
    expect(screen.getByText("Harnesses")).toBeVisible();
    // Creating stays reachable, in the submenu that groups custom agents.
    expect(screen.getByTestId("new-chat-landing-custom-agents")).toBeVisible();
  });
});
