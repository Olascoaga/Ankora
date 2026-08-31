"""A Methods section written from what a campaign actually recorded.

Not a template with the numbers dropped in. Every sentence is rendered from a
stored artifact, and where an artifact is missing the text says so in place
rather than leaving a plausible-looking gap — a Methods section is the part of
a paper a reader trusts to be literal, and the failure mode Ankora exists to
prevent is prose that reads as if something was verified when it was not.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MethodsSoftware(BaseModel):
    """One tool, the version that ran, and what it did in this campaign."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    role: str = Field(min_length=1)


class MethodsReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_id: str = Field(min_length=1)
    generated_at: datetime
    engine_label: str = Field(min_length=1)
    markdown: str = Field(min_length=1)

    # What could not be stated, collected so the author sees the holes as a
    # list instead of hunting for them in the prose.
    gaps: list[str] = Field(default_factory=list)
    software: list[MethodsSoftware] = Field(default_factory=list)
