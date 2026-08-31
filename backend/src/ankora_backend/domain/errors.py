"""Domain errors translated to the stable local API error model."""


class AnkoraDomainError(Exception):
    def __init__(
        self,
        *,
        code: str,
        stage: str,
        message: str,
        status_code: int,
        details: dict[str, object] | None = None,
        recoverable: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.recoverable = recoverable
