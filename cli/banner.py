"""EASE banner & logo ASCII art — Hermes-style version info."""
from __future__ import annotations

__version__ = "0.2.0"


BANNER = rf"""
  ╔══════════════════════════════════════╗
  ║                                      ║
  ║     ███████╗ █████╗ ███████╗███████╗ ║
  ║     ██╔════╝██╔══██╗██╔════╝██╔════╝ ║
  ║     █████╗  ███████║███████╗█████╗   ║
  ║     ██╔══╝  ██╔══██║╚════██║██╔══╝   ║
  ║     ███████╗██║  ██║███████║███████╗ ║
  ║     ╚══════╝╚═╝  ╚═╝╚══════╝╚══════╝ ║
  ║                                      ║
  ║   Emergent-Stitching Architecture    ║
  ║         for Evolution v{__version__:<7}         ║
  ║                                      ║
  ╚══════════════════════════════════════╝"""

LOGO_COMPACT = f"""
  ┌─ EASE ─────────────────────────┐
  │  Emergent-Stitching Architecture│
  │  for Evolution  v{__version__:<7}         │
  └─────────────────────────────────┘"""

SYMBOL = "◆ EASE ◆"


def get_version_str() -> str:
    """Version string for CLI display."""
    return f"EASE v{__version__}"


def format_banner_version_label() -> str:
    """Hermes-style version label for the startup banner.

    Returns a formatted string like:
        EASE v0.2.0
    """
    return f"EASE Agent v{__version__}"
