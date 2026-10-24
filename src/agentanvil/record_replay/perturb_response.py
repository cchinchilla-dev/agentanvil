"""Faults that the transport proxy injects into a response, before it reaches the client (#36).

Same contract as the request operators in `perturb`: pure functions of the
response, the client's request, the fault and a seed, returning `None` on a miss.
They act on the first choice's message. `delay` and `upstream_error` change no
JSON and are applied by the session (`proxy_faults`).
"""

from __future__ import annotations

import json
from collections.abc import Callable

from agentanvil.record_replay.normalize import JSON, JSONObject
from agentanvil.record_replay.perturb import (
    Change,
    Fault,
    InflateParams,
    OutputRewriteParams,
    ToolCallParams,
    pick,
)
from agentanvil.record_replay.proxy_layers import derive_seed

Previous = list[JSON]
"""Tool calls of the role's previous crossing, as its client received them."""

Found = tuple[list[JSON], dict[str, JSON], dict[str, JSON]]
"""A response's choices, its first choice and that choice's message."""


def tool_call(
    response: JSONObject, request: JSONObject, fault: Fault, seed: int, previous: Previous
) -> Change | None:
    """Rename one tool call to another tool, or change one of its arguments."""
    params = ToolCallParams.model_validate(fault.params)
    found = _message(response)
    calls = found[2].get("tool_calls") if found else None
    if found is None or not isinstance(calls, list) or not calls:
        return None
    i = pick(len(calls), seed)
    call = calls[i]
    if not isinstance(call, dict) or not isinstance(function := call.get("function"), dict):
        return None
    path = f"choices[0].message.tool_calls[{i}].function"
    choices: dict[str, JSON] = {}
    if params.argument is not None:
        raw = function.get("arguments")
        try:
            arguments = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            return None
        if not isinstance(arguments, dict):
            return None
        arguments = {**arguments, params.argument: params.value}
        changed = json.dumps(arguments, ensure_ascii=False) if isinstance(raw, str) else arguments
        new, site = {**function, "arguments": changed}, f"{path}.arguments"
    else:
        target = params.rename_to
        if target is None:
            others = [n for n in _tool_names(request) if n != function.get("name")]
            if not others:
                return None
            target = others[pick(len(others), derive_seed(seed, "rename"))]
        new, site, choices = {**function, "name": target}, f"{path}.name", {"rename_to": target}
    out = list(calls)
    out[i] = {**call, "function": new}
    return _with_message(response, found, {**found[2], "tool_calls": out}), site, choices


def output_rewrite(
    response: JSONObject, request: JSONObject, fault: Fault, seed: int, previous: Previous
) -> Change | None:
    """Replace the answer's text, or one field of a JSON answer."""
    params = OutputRewriteParams.model_validate(fault.params)
    found = _message(response)
    content = found[2].get("content") if found else None
    if found is None or not isinstance(content, str):
        return None
    site = "choices[0].message.content"
    if params.text is not None:
        text = params.text
    else:
        try:
            data = json.loads(content)
        except ValueError:
            return None
        if not _set_field(data, str(params.field).split("."), params.value):
            return None
        text, site = json.dumps(data, ensure_ascii=False), f"{site}.{params.field}"
    return _with_message(response, found, {**found[2], "content": text}), site, {}


def inflate(
    response: JSONObject, request: JSONObject, fault: Fault, seed: int, previous: Previous
) -> Change | None:
    """Repeat the answer's text `factor` times and raise the completion tokens to match."""
    factor = InflateParams.model_validate(fault.params).factor
    found = _message(response)
    content = found[2].get("content") if found else None
    if found is None or not isinstance(content, str) or not content:
        return None
    out = _with_message(response, found, {**found[2], "content": "\n\n".join([content] * factor)})
    site = "choices[0].message.content"
    usage = response.get("usage")
    if isinstance(usage, dict) and isinstance(completion := usage.get("completion_tokens"), int):
        raised: dict[str, JSON] = {**usage, "completion_tokens": completion * factor}
        if isinstance(prompt := usage.get("prompt_tokens"), int):
            raised["total_tokens"] = prompt + completion * factor
        out["usage"], site = raised, f"{site},usage"
    return out, site, {}


def loop(
    response: JSONObject, request: JSONObject, fault: Fault, seed: int, previous: Previous
) -> Change | None:
    """Answer with the tool calls of the role's previous crossing again, under new ids."""
    found = _message(response)
    if found is None or not previous or not all(isinstance(c, dict) for c in previous):
        return None
    calls: list[JSON] = [
        {**c, "id": f"call_{seed:08x}_{i}"} for i, c in enumerate(previous) if isinstance(c, dict)
    ]
    message = {**found[2], "content": None, "tool_calls": calls}
    out = _with_message(response, found, message, finish_reason="tool_calls")
    site = "choices[0].message.content,choices[0].message.tool_calls,choices[0].finish_reason"
    return out, site, {}


RESPONSE_OPS: dict[str, Callable[[JSONObject, JSONObject, Fault, int, Previous], Change | None]] = {
    "tool_call": tool_call,
    "output_rewrite": output_rewrite,
    "inflate": inflate,
    "loop": loop,
}


def tool_calls_of(response: JSONObject) -> Previous:
    """The tool calls of a response's first choice; `[]` when it has none."""
    found = _message(response)
    calls = found[2].get("tool_calls") if found else None
    return calls if isinstance(calls, list) else []


def _message(response: JSONObject) -> Found | None:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choice := choices[0], dict):
        return None
    message = choice.get("message")
    return (choices, choice, message) if isinstance(message, dict) else None


def _with_message(
    response: JSONObject, found: Found, message: JSONObject, **fields: JSON
) -> JSONObject:
    choices, choice, _ = found
    return {**response, "choices": [{**choice, "message": message, **fields}, *choices[1:]]}


def _tool_names(request: JSONObject) -> list[str]:
    tools = request.get("tools")
    names = []
    for tool in tools if isinstance(tools, list) else []:
        function = tool.get("function") if isinstance(tool, dict) else None
        if isinstance(function, dict) and isinstance(name := function.get("name"), str):
            names.append(name)
    return names


def _set_field(data: JSON, path: list[str], value: JSON) -> bool:
    # Changes a field that exists; a missing one is a miss, not an addition.
    for key in path[:-1]:
        if not isinstance(data, dict) or key not in data:
            return False
        data = data[key]
    if not isinstance(data, dict) or path[-1] not in data:
        return False
    data[path[-1]] = value
    return True
