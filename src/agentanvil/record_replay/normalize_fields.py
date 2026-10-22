"""Fields the transport-proxy normaliser drops before hashing, as paths.

A path names a field: `timings` is a top-level key, `choices[].meta_info` a key of
every element of `choices` (`[]` means each element of a list). The defaults are
the fields that servers mint per call; `Normalizer.ignore_request` and
`ignore_response` add more.
"""

from __future__ import annotations

import functools
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentanvil.record_replay.normalize import JSON, JSONObject

FIELD_PATH = re.compile(r"(?:[\w-]+(?:\[\])?\.)*[\w-]+")

REQUEST_IGNORED = frozenset(
    {
        "seed",
        "stream",
        "stream_options",
        "num_retries",
        "timeout",
        "user",
        "metadata",
        # minted per call by the server and sent back by the client in later turns
        "messages[].tool_calls[].extra_content",
        "messages[].reasoning_details[].id",
        "messages[].reasoning_details[].signature",
        "messages[].reasoning_details[].data",
        "messages[].audio.id",
    }
)
# Minted per call; docs/transport-proxy.md says which server sends which.
RESPONSE_IGNORED = frozenset(
    {
        # any OpenAI-compatible server
        "id",
        "created",
        "system_fingerprint",
        "usage",
        "service_tier",
        # self-hosted servers: llama.cpp, vLLM, SGLang, LM Studio, TensorRT-LLM
        "timings",
        "__verbose",
        "metrics",
        "kv_transfer_params",
        "ec_transfer_params",
        "sglext",
        "metadata",
        "stats",
        "model_info",
        "runtime",
        "choices[].meta_info",
        "choices[].speculative_decoding",
        "choices[].avg_decoded_tokens_per_iter",
        "choices[].disaggregated_params",
        "choices[].mm_embedding_handle",
        # hosted APIs: Groq, Cerebras, Fireworks, OpenRouter, Together, Gemini, OpenAI
        "x_groq",
        "usage_breakdown",
        "time_info",
        "perf_metrics",
        "openrouter_metadata",
        "provider",
        "choices[].seed",
        "choices[].message.tool_calls[].extra_content",
        "choices[].message.reasoning_details[].id",
        "choices[].message.reasoning_details[].signature",
        "choices[].message.reasoning_details[].data",
        "choices[].message.audio.id",
        "choices[].message.audio.expires_at",
    }
)


def drop(body: JSONObject, paths: frozenset[str]) -> JSONObject:
    """Copy of `body` without the fields at `paths`; only what lies on a path is copied."""
    out = dict(body)
    for path in paths:
        head, *rest = _parse(path)  # a path starts with a key, never with []
        if head in out:
            if rest:
                out[head] = _without(out[head], tuple(rest))
            else:
                del out[head]
    return out


@functools.cache
def _parse(path: str) -> tuple[str, ...]:
    """`choices[].meta_info` -> ("choices", "[]", "meta_info")."""
    return tuple(
        part
        for seg in path.split(".")
        for part in ((seg[:-2], "[]") if seg.endswith("[]") else (seg,))
    )


def _without(node: JSON, path: tuple[str, ...]) -> JSON:
    head, rest = path[0], path[1:]
    if head == "[]":
        return [_without(x, rest) for x in node] if isinstance(node, list) else node
    if not isinstance(node, dict) or head not in node:
        return node
    if not rest:
        return {k: v for k, v in node.items() if k != head}
    return {**node, head: _without(node[head], rest)}
