"""Minimum traceable scientific action contract."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ankora_backend.schemas.warnings import StructuredWarning


class ToolIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class ProvenanceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    timestamp: datetime
    input_artifacts: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)
    tool: ToolIdentity
    parameters: dict[str, object] = Field(default_factory=dict)
    warnings: list[StructuredWarning] = Field(default_factory=list)
    command: list[str] | None = None
