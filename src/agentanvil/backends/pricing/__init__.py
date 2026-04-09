"""Pinned pricing table for `DirectBackend`.

Single bundled YAML (`pricing.yaml`) keyed by model id with input / output /
optional reasoning USD per 1K tokens. Mirrors the shape of
`agentloom/providers/pricing.yaml` so both repos stay coherent.

Override resolution order for `cost_for`:

1. Explicit `pricing_table=` argument.
2. ``AGENTANVIL_PRICING_FILE`` environment variable.
3. Bundled `pricing.yaml`.

`cost_for` raises `KeyError` on unknown models. Callers can opt out by passing
`default=Decimal(0)`. A trailing-prefix fallback is applied so a dated suffix
(e.g. `gpt-4o-2024-11-20`) gracefully matches a base entry (e.g. `gpt-4o`)
when the dated entry is absent.
"""

from __future__ import annotations

import os
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

_PER_1K = Decimal("1000")
_BUNDLED_PATH = files("agentanvil.backends.pricing").joinpath("pricing.yaml")
_TABLE: dict[str, Any] | None = None


def _load(path: Path | Any) -> dict[str, Any]:
    text = path.read_text() if hasattr(path, "read_text") else Path(path).read_text()
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError(
            f"Pricing YAML must be a mapping of model entries; got {type(raw).__name__}"
        )
    return raw


def _resolve_path() -> Path | Any:
    env = os.environ.get("AGENTANVIL_PRICING_FILE")
    if env:
        return Path(env)
    return _BUNDLED_PATH


def _get_table() -> dict[str, Any]:
    global _TABLE
    if _TABLE is None:
        _TABLE = _load(_resolve_path())
    return _TABLE


def _is_model_entry(key: str, value: Any) -> bool:
    return not key.startswith("_") and isinstance(value, dict)


def cost_for(
    provider: str,
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int = 0,
    default: Decimal | None = None,
    pricing_table: dict[str, Any] | None = None,
) -> Decimal:
    """Compute USD cost for a completion using pinned per-1K-token prices.

    When the model entry omits ``reasoning``, reasoning tokens are billed at
    the model's ``output`` rate. Pass ``reasoning_tokens=0`` for
    non-reasoning callers to avoid this.

    ``provider`` is accepted for API stability across backends and ignored —
    the YAML table is keyed by model id alone.
    """
    del provider  # accepted for compat; not used.
    table = pricing_table or _get_table()
    entry = table.get(model)
    if entry is None or not isinstance(entry, dict):
        # Prefix fallback: dated suffix matches its base entry.
        for key, vals in table.items():
            if not _is_model_entry(key, vals):
                continue
            if model.startswith(key):
                entry = vals
                break
    if entry is None or not isinstance(entry, dict):
        if default is not None:
            return default
        raise KeyError(f"No pricing for {model!r}; update agentanvil/backends/pricing/pricing.yaml")
    input_per_1k = Decimal(str(entry["input"]))
    output_per_1k = Decimal(str(entry["output"]))
    reasoning_per_1k = Decimal(str(entry.get("reasoning", entry["output"])))
    cost = (
        input_per_1k * Decimal(input_tokens)
        + output_per_1k * Decimal(output_tokens)
        + reasoning_per_1k * Decimal(reasoning_tokens)
    ) / _PER_1K
    return cost.quantize(Decimal("0.000001"))


def pricing_table_version(provider: str | None = None) -> str:
    """Read the pricing table version from the YAML ``_meta`` block.

    ``provider`` is accepted for API stability and ignored — the bundled YAML
    is global, not per-provider.
    """
    del provider
    meta = _get_table().get("_meta", {})
    if not isinstance(meta, dict):
        return "unknown"
    return str(meta.get("pricing_table_version", "unknown"))
