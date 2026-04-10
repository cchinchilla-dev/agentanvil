# Runner protocol — stdin/stdout JSON wire format

This document specifies how AgentAnvil communicates with the agent under test
through any concrete `Runner` implementation (`SubprocessRunner`,
`DockerRunner`, `K8sRunner`). Adopting this protocol is the contract every
agent must honour to be testable by AgentAnvil.

The protocol is deliberately **simple** — JSON in, JSON out, plain text on
stderr — so it can be implemented in any language without an SDK.

## Wire format

### Input — sent on `stdin`

A single JSON object, terminated by EOF:

```json
{
  "scenario_id": "s_001",
  "inputs": {
    "...": "scenario-specific payload"
  },
  "context": {
    "agentanvil_version": "0.1.1",
    "run_id": "run_01JA...",
    "seed": 42
  }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `scenario_id` | string | yes | Scenario identifier from the contract. |
| `inputs` | object | yes | Free-form scenario payload. |
| `context.run_id` | string | yes | Unique run identifier (ULID-like). |
| `context.seed` | integer | no | Use to seed any RNG inside the agent. |
| `context.agentanvil_version` | string | yes | For compatibility checks. |

### Output — written to `stdout`

A single JSON object, written before exit:

```json
{
  "response": "Plain text or structured response from the agent.",
  "tool_calls": [
    {"name": "search", "arguments": {"q": "..."}, "result": "..."}
  ],
  "metadata": {
    "duration_ms": 123,
    "...": "..."
  }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `response` | string \| object | yes | Final answer. |
| `tool_calls` | array | no | Optional — list of tool invocations. |
| `metadata` | object | no | Free-form telemetry. |

### Diagnostics — written to `stderr`

Anything not matching the JSON output schema. Logs, debug prints, exception
tracebacks. AgentAnvil captures stderr for failure analysis but does not parse
it.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success. `stdout` contains a valid response object. |
| `> 0` | Agent failed. AgentAnvil records the result as a failure. |
| `-1` | Timeout. AgentAnvil killed the process tree. |

## Timeouts

The runner enforces `timeout_ms` (driven by `contract.constraints.max_latency_ms`).
On timeout the process tree is terminated (best effort) and the result is
flagged `timed_out=True` with `exit_code=-1`.

## Environment

AgentAnvil passes a curated environment to the agent (the caller controls the
exact contents). Agents should read configuration from environment variables
rather than from arguments — `SubprocessRunner` does not pass CLI arguments
beyond the agent path itself.

## Future extensions

- **Multi-agent inter-agent messaging** (0.3.0): the `inputs.peers` array will
  list available peer agents with their A2A endpoints.
- **Streaming responses** (0.3.0): NDJSON on stdout, one JSON object per line.
- **Stateful runs** (0.3.0): `context.session_id` persists across multiple
  scenario invocations.

These extensions are additive — agents that conform to the 0.1.x protocol
remain compatible.
