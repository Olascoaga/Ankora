"""Run the development backend on the loopback interface."""

import uvicorn


def main() -> None:
    uvicorn.run(
        "ankora_backend.api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=8765,
        log_level="info",
    )


if __name__ == "__main__":
    main()
