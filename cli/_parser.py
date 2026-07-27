"""Top-level argparse construction for the EASE CLI.

Hermes-style framework: parser construction lives in its own module so
that other modules can introspect the parser structure without running main().

Only the top-level parser lives here. Subcommand parsers are built inline
in the command modules (commands/evolve.py, etc.) via the established
add_parser(subparsers) pattern.
"""

import argparse


_EPILOGUE = """
Examples:
    ease                           Show banner and help
    ease evolve                    Run evolution loop
    ease evolve --quick            Quick 3-generation run
    ease character create <name>   Create a new character
    ease character list            List all characters
    ease status                    Show system status
    ease status --full             Show full system status
    ease config show               View configuration
    ease config set <key> <val>    Set a config value
    ease version                   Show version

For more help on a command:
    ease <command> --help
"""


def build_top_level_parser() -> tuple[argparse.ArgumentParser, argparse._SubParsersAction]:
    """Build the top-level parser with shared flags and subparsers.

    Returns (parser, subparsers). The caller dispatches based on
    args.command and wires each command's run() function.
    """
    parser = argparse.ArgumentParser(
        prog="ease",
        description="Emergent-Stitching Architecture for Evolution — "
                    "ESAE self-evolving agent framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EPILOGUE,
    )

    parser.add_argument(
        "--version", "-V", action="store_true",
        help="Show version and exit",
    )

    parser.add_argument(
        "-v", "--verbose", action="store_true", default=False,
        help="Verbose output",
    )

    parser.add_argument(
        "-q", "--quiet", action="store_true", default=False,
        help="Quiet mode: suppress banner and extra output",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Subparsers are registered by each command module's add_parser().
    # The caller calls subcommand_add_parser(subparsers) for each command.

    return parser, subparsers
