"""CLI entry — `python -m harness <step>`.

Steps:
  inventory   regenerate auto-update catalogs (manual/1*-catalog-*.md)
  walk        drive TUI through manifest, capture per-feature .md
  build       assemble + render PDF
  all         inventory → walk → build, one shot
"""
import argparse
import sys
from pathlib import Path

from .inventory import InventoryGenerator
from .walker import Walker
from .pdf_builder import PDFBuilder

WORKSPACE = Path(__file__).resolve().parent.parent
MANUAL_DIR = WORKSPACE / "manual"
BUILD_DIR = WORKSPACE / "build"


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m harness")
    parser.add_argument(
        "step",
        choices=["inventory", "walk", "build", "all"],
        help="which phase to run",
    )
    parser.add_argument(
        "--socket",
        default="/tmp/jaato.sock",
        help="daemon IPC socket path (default: /tmp/jaato.sock)",
    )
    args = parser.parse_args()

    MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    if args.step in ("inventory", "all"):
        print("=== inventory ===")
        InventoryGenerator(manual_dir=MANUAL_DIR).run()

    if args.step in ("walk", "all"):
        print("=== walk ===")
        Walker(socket=args.socket, manual_dir=MANUAL_DIR).run()

    if args.step in ("build", "all"):
        print("=== build ===")
        PDFBuilder(manual_dir=MANUAL_DIR, build_dir=BUILD_DIR).run()

    return 0


if __name__ == "__main__":
    sys.exit(main())
