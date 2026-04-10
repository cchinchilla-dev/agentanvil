"""Report — renderable form of a `RunRecord`.

Identical inputs must produce identical outputs across renderers (JSON, HTML,
Markdown, SARIF). The reporter module (added in 0.2.0 #019) populates the
`rendered` map.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from agentanvil.core.run_record import RunRecord


class ReportFormat(StrEnum):
    JSON = "json"
    HTML = "html"
    MARKDOWN = "markdown"
    SARIF = "sarif"


class Report(BaseModel):
    """A renderable view over one `RunRecord`."""

    run_record: RunRecord
    rendered: dict[ReportFormat, str] = Field(default_factory=dict)
