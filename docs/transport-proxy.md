# Transport proxy — record and replay at the HTTP boundary

The transport proxy records and replays LLM calls of **any runtime**, without
code inside it: it sits between the agent and an OpenAI-compatible server
(vLLM, SGLang, a hosted API) and only needs the client to accept a base URL.
It complements the in-process envelope of
[`RecordingBackend` / `MockBackend`](record-replay-envelope.md), which needs the
agent to call AgentAnvil's `LLMBackend`.

Besides recording, it can rewrite the sampling seed of each call and permute
the order of tools and of parallel tool results. A recorded session can be
replayed exactly, replayed only for its first calls and continued live, or
compared with a new run call by call.

## Running it

```bash
agentanvil proxy --log-dir recordings --port 8090
```

| Option | Default | Notes |
|---|---|---|
| `--log-dir` | `recordings` | One JSON Lines log per session. |
| `--host` | `127.0.0.1` | The proxy has no authentication: keep it on localhost (`::1` for IPv6). |
| `--port`, `-p` | `8090` | |
| `--timeout` | `600` | Upstream timeout in seconds; long generations need it. |

Give the client a longer timeout than the proxy's. A client that gives up and
retries first leaves its call running: when that call completes it takes
crossing k, and the retry becomes k+1.

## Sessions and boundaries

A **session** is one run (an episode, a test case). Within it, each **role**
is a boundary with its own base URL, for example an agent and the simulated
user that talks to it:

```
http://127.0.0.1:8090/s/<session>/<role>/v1
```

The k-th **crossing** of a boundary is its k-th completed call. Upstream errors
do not consume a crossing: the client's retry gets the same k. Calls within a
session are serialised, so crossing order never depends on timing.

A driver opens a session before the run and closes it after:

```
POST   /_anvil/sessions          body: session config (JSON)   → 201 {"session_id", "log"}
DELETE /_anvil/sessions/<id>                                     → 200 {"session_id", "log", "missing"}
```

Closing waits for a call in flight, logs a `close` record and returns
`missing`: per role, the reference crossings the run never made (`{}` without a
reference, or when the run made them all). Calls after the close get 404.

```python
import httpx

proxy = httpx.Client(base_url="http://127.0.0.1:8090")
proxy.post("/_anvil/sessions", json={
    "session_id": "case-001-r1",
    "roles": {
        "agent": {"upstream": "http://127.0.0.1:8000/v1", "seed": 1234},
        "user": {"upstream": "http://127.0.0.1:8001/v1", "seed": 99},
    },
}).raise_for_status()
# ... run the agent with base_url=http://127.0.0.1:8090/s/case-001-r1/agent/v1
#     and its simulated user with base_url=.../s/case-001-r1/user/v1 ...
proxy.delete("/_anvil/sessions/case-001-r1")
```

Session ids and role names match `[A-Za-z0-9_-]{1,64}`. A session id whose log
already exists is refused, so two runs never share a log.

### Session config

| Field | Type | Default | Notes |
|---|---|---|---|
| `session_id` | string | — | Also the log file name. |
| `roles` | object | — | Role name → `{"upstream": <base URL>, "seed": <int or null>}`. |
| `roles.*.seed` | integer \| null | `null` | When set, every call's `seed` is rewritten (see below). `null` keeps the client's. |
| `permute_seed` | integer \| null | `null` | When set, tool order is permuted (see below). `null` keeps the client's order. |
| `permute_roles` | list of strings | `["agent"]` | Roles whose tool order is permuted. |
| `reference` | path \| null | `null` | Log of an earlier session to replay from or compare with. |
| `replay_until` | integer | `0` | Crossings whose session-wide index in the reference is below this are replayed. Needs `reference`. |
| `on_divergence` | `"log"` \| `"abort"` | `"log"` | What to do when a crossing differs from its reference. |
| `normalizer` | object | see below | What to erase before hashing. |

## What the proxy does to each call

- **Seed.** With `roles.<role>.seed = s`, the k-th call of that role is sent
  with `seed = derive(s, role, k)`, a 31-bit value from SHA-256. Two sessions
  with the same `s` send the same seeds; a new `s` gives new seeds.
  Whether equal seeds give equal outputs depends on the server (for vLLM,
  batch-invariant kernels).
- **Order.** With `permute_seed = p`, `tools` is permuted once per session and
  role, and each run of two or more consecutive tool results is permuted by
  where it starts in the conversation, so the history the model sees stays the
  same from one call to the next as it grows. Permutations sort by SHA-256 and
  do not depend on Python's `random`.
- **Replay.** With a `reference`, the k-th crossing of a role is paired with the
  k-th crossing of that role in the reference. If the reference crossing's
  session-wide index is below `replay_until`, the proxy returns its recorded
  response without calling upstream; later crossings go live.
- **Divergence.** With a `reference`, every crossing is compared with its pair
  by request hash and, when live, by response hash; a crossing the reference
  does not have is `extra`, and a run that stops short shows in `missing` at
  close. The reference's hashes are recomputed under the session's
  `normalizer`, so it does not matter which one recorded it. Divergences are
  always logged. With `on_divergence = "abort"`, the first divergence returns
  HTTP 409 and every later call of the session gets 409 too.

The proxy forwards `Authorization` headers upstream and never writes them to
the log. Only `POST .../v1/chat/completions` is proxied; streaming requests are
refused.

## Normalisation and hashes

Request and response hashes are `"sha256:" + sha256(canonical JSON)` over a
normalised copy, taken on the request **as the client sent it**, before the
proxy rewrites seed or order:

- `seed` is dropped, since the proxy rewrites it (the crossing logs the value
  it sent), and so are the request fields that do not change the completion:
  `stream`, `stream_options`, `num_retries`, `timeout`, `user`, `metadata`;
- response fields minted per call are dropped: `id`, `created`,
  `system_fingerprint`, `usage`, `service_tier`;
- tool-call ids become ordinals in order of first appearance (`call_0`, ...);
- tool-call arguments are parsed and re-serialised with sorted keys
  (malformed arguments are kept verbatim).

| `normalizer` field | Default | Erases |
|---|---|---|
| `tool_call_ids` | `true` | Tool-call ids, as above. |
| `timestamps` | `false` | ISO-8601 timestamps inside message text. |
| `uuids` | `false` | UUIDs inside message text. |
| `whitespace` | `false` | Runs of whitespace inside message text. |

Timestamps, UUIDs and whitespace are off by default: in many tasks dates and
identifiers are data, not noise.

## Log format

JSON Lines, UTF-8, keys sorted, one record per line, flushed per line: a crash
loses at most the line being written. A lone surrogate in a message (tool
output decoded with `surrogateescape`) is written as its escape. Four kinds of
record:

| `kind` | When | Main fields |
|---|---|---|
| `session` | First line | `config`: the session config. |
| `crossing` | Each completed call | `role`, `k`, `index` (session-wide), `source` (`live` or `replay`), `seed` and `tools_order` applied, `request_hash`, `response_hash`, `request` (as the client sent it), `response`, `latency_ms`, `divergence` (`[]`, `["request"]`, `["response"]`, both, or `["extra"]`). |
| `failure` | Upstream error or abort | `reason` (`upstream` or `divergence`), `role`, `k`, `status`, `request_hash`, `divergence`, `response`. |
| `close` | Session closed | `crossings` and `missing`, per role. |

A log used as `reference` must be complete: a log that does not end with its
`close` record (the session never closed), a truncated line or a gap in k is
an error, since replaying it would shift every later crossing.

## Status codes

| Code | Meaning |
|---|---|
| 200 | Completion, live or replayed. |
| 201 | Session opened. |
| 400 | Body is not a JSON object, invalid `Content-Length`, or the request asks for streaming. |
| 403 | Request from a browser: it carries an `Origin` header. |
| 404 | Unknown route, session or role, or a session already closed. |
| 409 | Session already open, its log exists or its reference is unreadable or incomplete; or the session aborted on divergence. |
| 413 | Body larger than 64 MB. |
| 422 | Invalid session config, including an upstream that is not an `http(s)` URL. |
| 500 | Unexpected proxy error, such as a full disk; the connection is closed. |
| 502 | Upstream unreachable or not returning a JSON object. |
| other | The upstream's own status, passed through and logged as a `failure`. |

## Limitations

- Chat completions only, without streaming.
- No authentication: anyone who can reach the port can open sessions. Requests
  with an `Origin` header are refused, so a web page cannot drive the proxy.
- Each crossing stores the full request, so logs grow with the square of the
  conversation length; compress them when a session closes.
