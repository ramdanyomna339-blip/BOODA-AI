"""Windows-friendly UTF-8 console setup for Arabic CLI output."""

import sys


def configure_utf8_console():
    """Use UTF-8 for CLI input/output when the stream supports reconfiguration."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # Captured/test streams and detached consoles may not be reconfigurable.
            continue
