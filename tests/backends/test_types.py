"""Round-trip and validation tests for backend Pydantic primitives."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from agentanvil.backends.types import (
    ContentBlock,
    LLMResponse,
    Message,
    ToolCall,
    Usage,
)


def test_message_round_trip() -> None:
    msg = Message(role="user", content="hello")
    dumped = msg.model_dump()
    assert Message.model_validate(dumped) == msg


def test_message_with_tool_calls_round_trip() -> None:
    msg = Message(
        role="assistant",
        content="I'll look that up.",
        tool_calls=[ToolCall(id="call_1", name="search", arguments={"q": "foo"})],
    )
    dumped = msg.model_dump()
    assert Message.model_validate(dumped) == msg


def test_llm_response_round_trip() -> None:
    resp = LLMResponse(
        content="ok",
        usage=Usage(input_tokens=10, output_tokens=4),
        finish_reason="stop",
        latency_ms=123,
        cost_usd=Decimal("0.0001"),
        model="gpt-4o-2024-11-20",
        provider="openai",
    )
    dumped = resp.model_dump()
    assert LLMResponse.model_validate(dumped) == resp


def test_usage_defaults_reasoning_tokens_zero() -> None:
    u = Usage(input_tokens=1, output_tokens=2)
    assert u.reasoning_tokens == 0
    assert u.cached_tokens == 0


def test_tool_call_arguments_are_a_dict() -> None:
    tc = ToolCall(id="x", name="lookup", arguments={"k": 1})
    assert isinstance(tc.arguments, dict)


def test_content_block_image_data_or_url_not_both() -> None:
    with pytest.raises(ValidationError):
        ContentBlock(type="image", image_url="https://example.com/x.png", image_data=b"raw")


def test_content_block_image_requires_one_source() -> None:
    with pytest.raises(ValidationError):
        ContentBlock(type="image")


def test_content_block_text_round_trip() -> None:
    block = ContentBlock(type="text", text="hi")
    assert ContentBlock.model_validate(block.model_dump()) == block
