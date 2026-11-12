"""Contracts for the Linux offline GNINA 1.3.3 + CUDA 12 / cuDNN 9 pack."""

from pydantic import Field

from ankora_backend.schemas.system import ContractModel


class ImportGninaPackRequest(ContractModel):
    archive_path: str = Field(min_length=1, max_length=4096)


class GninaPackStatus(ContractModel):
    supported: bool
    installed: bool
    pack_id: str
    gnina_version: str
    install_dir: str | None = None
    executable_path: str | None = None
    executable_sha256: str | None = None
    shared_library_count: int = 0
    imported_at: str | None = None
    verification_error: str | None = None
