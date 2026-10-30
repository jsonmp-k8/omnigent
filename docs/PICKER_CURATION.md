# Curating the New Chat picker

A deployment can decide which agents the New Chat picker offers, and which one
a fresh chat starts on, from the server config file:

```yaml
# Only these agents appear in New Chat, in this order.
restrict_to_agent_names:
  - polly
  - claude-native-ui
# A fresh New Chat starts here. Optional, and independent of the restriction.
default_agent_name: polly
```

Both keys are optional. With neither set, the picker behaves exactly as it
always has.

Where the server reads that file depends on how it starts:

- `omnigent server -c <file>` reads `<file>`. A plain `omnigent server`,
  without `-c`, reads no config file for these keys, and ignores both
  `OMNIGENT_CONFIG` and `<data_dir>/config.yaml`.
- The Docker image reads `OMNIGENT_CONFIG` if it is set, else
  `<data_dir>/config.yaml` (`/data/config.yaml` on the volume).

Both values are published on `GET /v1/info`, which needs no authentication,
so the names you put here are visible to anyone who can reach the server.

## What this does and does not do

It is **display only**. It narrows what a fresh New Chat *shows*; it never
changes what exists:

- every agent is still seeded, so nothing is removed from the server;
- a session already bound to an unlisted agent keeps working, and so does
  forking it;
- curation does not further filter `GET /v1/agents`, and an unlisted agent is
  still reachable by id through the API. An agent `OMNIGENT_SEEDED_AGENTS`
  leaves out stays unavailable even when the restriction names it.

Removing an agent from a deployment altogether is a different, server-side
concern, and is configured separately. Reach for this one when every agent
should stay available but only some belong in front of a user.

## How the picker changes

When `restrict_to_agent_names` is set, the menu becomes one flat list of the
named agents in the configured order. The Harnesses heading, the "Other..."
submenus, the "Create custom agent" action and the Smart Routing entry all
disappear, because none of them can lead anywhere the deployment allows. A
returning user's cached picker stays closed while `GET /v1/info` is still
pending, including while the embedded app shows its offline stand-in after
1.5 seconds, so the full roster is never shown ahead of the curation; if that
probe fails outright, the client falls back to the uncurated picker, as it
does for an older server that has no `picker` block. The "Hide unconfigured
harnesses" setting and the per-entry hides in Settings › Appearance apply to
the curated list as they do to the grouped menu. Name exactly one agent and the
picker collapses to that one row. If the names match nothing the menu says so
rather than opening blank, and the server logs a warning at startup naming the
agents it could not find. It also names any agent `OMNIGENT_SEEDED_AGENTS`
leaves out: the env var wins, so New Chat never offers those, even when
`restrict_to_agent_names` lists them.

`default_agent_name` only decides where someone with no history begins: a user
who has picked an agent before still returns to their own pick. A default that
the restriction does not offer is ignored, by both the server and the client,
since it could never be selected.

## What a restriction outranks

A restriction is a constraint on what New Chat may start, so it wins over the
selections it conflicts with:

- **A remembered pick** the restriction leaves out falls back to
  `default_agent_name`, or to the first offered agent. Its run settings do not
  follow it there: the brain harness is the one remembered for the agent that
  actually runs, so its cost-control override and the model and effort that
  hang off that harness are resolved for that agent too. A session never
  starts under a brain stored for an agent the user cannot select. The
  remembered values stay on the device in case the agent is offered again.
- **A project's configured agent** outside the restriction is reported as
  unavailable and the user picks from the offered agents before starting.
  Project settings still lists and stores that agent, and a scheduled task or
  API create bound to it is unaffected; only starting a session from New Chat
  is restricted.
- **A remembered Smart Routing pick** has no row left, so it degrades to the
  configured default, and the create carries no routing override.

An empty menu is not always the deployment's doing: when the agent list fails
to load the picker says so instead of blaming the restriction.

## Reporting

Both values are published on `GET /v1/info` under `picker`:

```json
{"picker": {"restrict_to_agent_names": ["polly"], "default_agent_name": "polly"}}
```

An older server omits the block, which clients read as "no curation".
