import argparse
import asyncio
import sys

import uvicorn


def configure_event_loop_policy() -> None:
    if sys.platform == "win32" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def selector_loop_factory():
    return asyncio.SelectorEventLoop()


def run(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    log_level: str = "info",
    reload: bool = False,
) -> None:
    configure_event_loop_policy()
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=reload,
        loop=selector_loop_factory,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Agent FastAPI server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    run(
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
