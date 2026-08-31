from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ankora_backend.schemas.provenance import ProvenanceEvent, ToolIdentity
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode


def test_stable_warning_schema_rejects_unknown_code() -> None:
    with pytest.raises(ValidationError):
        StructuredWarning(
            code="INVENTED_WARNING",  # type: ignore[arg-type]
            message="Synthetic warning",
            stage="test",
        )


def test_provenance_event_preserves_command_as_argument_array() -> None:
    warning = StructuredWarning(
        code=WarningCode.REC_MISSING_SIDECHAIN,
        message="Synthetic warning fixture",
        stage="receptor_inspection",
    )
    event = ProvenanceEvent(
        event_id="synthetic-event-1",
        event_type="synthetic_test",
        timestamp=datetime.now(UTC),
        tool=ToolIdentity(name="ankora-test", version="0.1.0"),
        warnings=[warning],
        command=["vina.exe", "--config", r"Synthetic\config.txt"],
    )

    assert event.command == ["vina.exe", "--config", r"Synthetic\config.txt"]
    assert event.warnings[0].code == WarningCode.REC_MISSING_SIDECHAIN
