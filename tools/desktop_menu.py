"""Start Booda with workspace-local optional desktop dependencies."""
import sys
import site
from pathlib import Path


def main():
    deps = Path(__file__).resolve().parents[1] / ".desktop-deps"
    if deps.is_dir():
        sys.path.insert(0, str(deps))
        site.addsitedir(str(deps))
    from core.main import main as application
    application()


if __name__ == "__main__":
    main()
