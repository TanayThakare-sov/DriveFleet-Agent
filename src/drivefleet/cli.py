"""Command line: drivefleet setup | serve | ask "question" | chat"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from drivefleet.config import get_settings


def cmd_setup(_args) -> None:
    from drivefleet.seed import build_database
    from drivefleet.train import train

    s = get_settings()
    print(f"Building database at {s.db_path} ...")
    build_database(s.db_path)
    print("Training failure model ...")
    card = train(s.db_path, s.model_dir)
    print(json.dumps(card["metrics"], indent=2))
    print("Done. Try:  drivefleet ask \"Is drive SN00157 at risk?\"")


def cmd_serve(_args) -> None:
    from drivefleet.mcp_server.server import main

    main()


def _require_key() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")


async def _ask(question: str, show_trace: bool) -> None:
    from drivefleet.agent import FleetAgent
    from drivefleet.agent.agent import format_trace

    async with FleetAgent() as agent:
        result = await agent.ask(question)
    if show_trace:
        print("Tool calls:\n" + format_trace(result), file=sys.stderr)
    print(result.answer)


async def _chat() -> None:
    from drivefleet.agent import FleetAgent
    from drivefleet.agent.agent import format_trace

    history: list[dict] = []
    async with FleetAgent() as agent:
        print("DriveFleet Assistant. Type a question (or 'exit').")
        while True:
            try:
                q = input("\nyou> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if q.lower() in {"exit", "quit", ""}:
                break
            result = await agent.ask(q, history)
            print(format_trace(result))
            print(f"\n{result.answer}")


def main() -> None:
    p = argparse.ArgumentParser(prog="drivefleet", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup", help="build the SQLite DB and train the failure model").set_defaults(fn=cmd_setup)
    sub.add_parser("serve", help="run the MCP server (stdio)").set_defaults(fn=cmd_serve)
    ask = sub.add_parser("ask", help="ask the agent one question")
    ask.add_argument("question")
    ask.add_argument("--trace", action="store_true", help="print tool calls to stderr")
    sub.add_parser("chat", help="interactive chat with the agent").set_defaults(fn=None)
    args = p.parse_args()

    if args.cmd in {"ask", "chat"}:
        _require_key()
    if args.cmd == "ask":
        asyncio.run(_ask(args.question, args.trace))
    elif args.cmd == "chat":
        asyncio.run(_chat())
    else:
        args.fn(args)


if __name__ == "__main__":
    main()
