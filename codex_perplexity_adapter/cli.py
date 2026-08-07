"""Command-line entry point for the standalone adapter."""

from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

import uvicorn

from .app import Settings, create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Codex–Perplexity adapter")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4000)
    parser.add_argument("--model-alias", default="gpt-5.6-sol")
    parser.add_argument("--upstream-model", default="openai/gpt-5.6-sol")
    parser.add_argument("--upstream-url", default="https://api.perplexity.ai/v1/responses")
    parser.add_argument("--local-token", default=os.getenv("ADAPTER_LOCAL_TOKEN", "local-litellm"))
    parser.add_argument("--pid-file", help="write the running server PID to this file")
    parser.add_argument("--prompt-key", action="store_true", help="securely prompt for the Perplexity API key")
    parser.add_argument("--log-level", default="info", choices=("critical", "error", "warning", "info", "debug"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    api_key = os.getenv("PERPLEXITY_API_KEY", "")
    if args.prompt_key or not api_key:
        api_key = getpass.getpass("Perplexity API key: ")
    if not api_key:
        raise SystemExit("PERPLEXITY_API_KEY is required (or use --prompt-key).")

    settings = Settings(
        api_key=api_key,
        model_alias=args.model_alias,
        upstream_model=args.upstream_model,
        upstream_url=args.upstream_url,
        local_token=args.local_token,
    )
    pid_file = Path(args.pid_file).expanduser() if args.pid_file else None
    if pid_file:
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
    try:
        uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level=args.log_level)
    finally:
        if pid_file:
            try:
                if pid_file.read_text(encoding="utf-8").strip() == str(os.getpid()):
                    pid_file.unlink()
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    main()
