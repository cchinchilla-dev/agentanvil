"""Faults that the transport proxy injects into a request, before it reaches the upstream (#36).

They run on the request as the client sent it, before the proxy rewrites its seed
and permutes tools and tool results, so the site they pick never depends on those
rewrites. Each returns `None` on a miss.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from agentanvil.record_replay.normalize import JSON, JSONObject
from agentanvil.record_replay.perturb import (
    Change,
    DropInstructionParams,
    Fault,
    ToolErrorParams,
    ToolResultParams,
    UserRewriteParams,
    pick,
)

TOOL_ERRORS = {
    "timeout": "Error: the tool call timed out.",
    "http_500": "Error: HTTP 500 Internal Server Error.",
}


def tool_result(body: JSONObject, fault: Fault, seed: int) -> Change | None:
    """Replace, empty or append to one of the tool results the request delivers."""
    params = ToolResultParams.model_validate(fault.params)

    def change(content: JSON) -> JSON:
        if params.mode == "append":
            return _append(content, params.text)
        return params.text if params.mode == "replace" else ""

    return _tool_result(body, seed, change)


def tool_error(body: JSONObject, fault: Fault, seed: int) -> Change | None:
    """Replace one of the tool results the request delivers with a canonical error."""
    error = TOOL_ERRORS[ToolErrorParams.model_validate(fault.params).error]
    return _tool_result(body, seed, lambda _: error)


def drop_instruction(body: JSONObject, fault: Fault, seed: int) -> Change | None:
    """Remove what the pattern matches from the system (and developer) messages."""
    pattern = re.compile(DropInstructionParams.model_validate(fault.params).pattern)
    messages = body.get("messages")
    if not isinstance(messages, list):
        return None
    out, sites = list(messages), []
    for i, message in enumerate(messages):
        if isinstance(message, dict) and message.get("role") in ("system", "developer"):
            content = _sub(message.get("content"), pattern)
            if content != message.get("content"):
                out[i] = {**message, "content": content}
                sites.append(f"messages[{i}].content")
    return ({**body, "messages": out}, ",".join(sites), {}) if sites else None


def user_rewrite(body: JSONObject, fault: Fault, seed: int) -> Change | None:
    """Replace the text of the last user message."""
    text = UserRewriteParams.model_validate(fault.params).text
    messages = body.get("messages")
    if not isinstance(messages, list):
        return None
    for i in reversed(range(len(messages))):
        if isinstance(message := messages[i], dict) and message.get("role") == "user":
            out = list(messages)
            out[i] = {**message, "content": text}
            return {**body, "messages": out}, f"messages[{i}].content", {}
    return None


REQUEST_OPS: dict[str, Callable[[JSONObject, Fault, int], Change | None]] = {
    "tool_result": tool_result,
    "tool_error": tool_error,
    "drop_instruction": drop_instruction,
    "user_rewrite": user_rewrite,
}


def _tool_result(body: JSONObject, seed: int, change: Callable[[JSON], JSON]) -> Change | None:
    # The results this request delivers: the tool messages it ends with.
    messages = body.get("messages")
    if not isinstance(messages, list):
        return None
    run: list[tuple[int, dict[str, JSON]]] = []
    for i in reversed(range(len(messages))):
        message = messages[i]
        if not (isinstance(message, dict) and message.get("role") == "tool"):
            break
        run.insert(0, (i, message))
    if not run:
        return None
    i, message = run[pick(len(run), seed)]
    out = list(messages)
    out[i] = {**message, "content": change(message.get("content"))}
    return {**body, "messages": out}, f"messages[{i}].content", {}


def _append(content: JSON, text: str) -> JSON:
    if isinstance(content, list):  # content parts: add a text part
        return [*content, {"type": "text", "text": text}]
    return (content if isinstance(content, str) else "") + text


def _sub(content: JSON, pattern: re.Pattern[str]) -> JSON:
    if isinstance(content, str):
        return pattern.sub("", content)
    if isinstance(content, list):
        return [
            {**part, "text": pattern.sub("", text)}
            if isinstance(part, dict) and isinstance(text := part.get("text"), str)
            else part
            for part in content
        ]
    return content
