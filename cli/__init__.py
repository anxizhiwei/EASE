"""EASE CLI — Unified command-line interface for EASE.

Hermes-style framework (argparse, banner, output helpers) with EASE-specific
commands.

Subcommands:
    ease evolve                      Run evolution loop
    ease character {create,show,list}  Character management
    ease status                      Show system status
    ease config {show,set}           Configuration management
    ease version                     Show version
"""

from __future__ import annotations

import sys

from cli._parser import build_top_level_parser
from cli.banner import BANNER, __version__, get_version_str
from cli.commands.evolve import add_parser as add_evolve
from cli.commands.character import add_parser as add_character
from cli.commands.status import add_parser as add_status
from cli.commands.config import add_parser as add_config


def main() -> None:
    """Main entry point for the EASE CLI.

    Architecture mirrors Hermes CLI:
      1. Build parser via _parser.build_top_level_parser()
      2. Register subcommands from each command module's add_parser()
      3. Dispatch to the matching command's run() function
    """
    parser, subparsers = build_top_level_parser()

    # ─── Register commands ───────────────────────────────────────────────
    add_evolve(subparsers)
    add_character(subparsers)
    add_status(subparsers)
    add_config(subparsers)

    # Standalone version subcommand
    p_version = subparsers.add_parser("version", help="显示版本信息")

    # ─── Dispatch ────────────────────────────────────────────────────────
    # No args → show banner + help
    if len(sys.argv) == 1:
        print(BANNER)
        print()
        parser.print_help()
        return

    args = parser.parse_args()

    # --version / -V flag
    if getattr(args, "version", False):
        print(get_version_str())
        return

    cmd = args.command

    if cmd == "evolve":
        from cli.commands.evolve import run as run_evolve
        run_evolve(args)
    elif cmd == "character":
        from cli.commands.character import run as run_character
        run_character(args)
    elif cmd == "status":
        from cli.commands.status import run as run_status
        run_status(args)
    elif cmd == "config":
        from cli.commands.config import run as run_config
        run_config(args)
    elif cmd == "version":
        print(get_version_str())
    else:
        print(BANNER)
        print()
        parser.print_help()


if __name__ == "__main__":
    main()
