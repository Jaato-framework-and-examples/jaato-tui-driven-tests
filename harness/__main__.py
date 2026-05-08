"""CLI entry — `python -m harness <step>`.

Steps:
  doctor      probe every system + python dep, print availability table
  inventory   regenerate auto-update catalogs (manual/1*-catalog-*.md)
  walk        drive TUI through manifest, capture per-feature .md
  build       assemble + render PDF
  all         inventory → walk → build, one shot
"""
import argparse
import sys
from pathlib import Path

from . import deps as _deps
from .inventory import InventoryGenerator
from .walker import Walker
from .pdf_builder import PDFBuilder

WORKSPACE = Path(__file__).resolve().parent.parent
MANUAL_DIR = WORKSPACE / "manual"
BUILD_DIR = WORKSPACE / "build"


def _run_doctor() -> int:
    """Print a doctor-style report covering every harness dep.

    Returns 0 if all deps are present, 1 otherwise.  Suitable for
    bug-report attachments and CI gates.
    """
    statuses = _deps.check(_deps.ALL_DEPS)
    print("=== doctor ===")
    print(_deps.report(statuses))
    missing = sum(1 for s in statuses if not s.present)
    if missing:
        print()
        print(f"  {missing} of {len(statuses)} deps missing.")
        return 1
    print()
    print(f"  all {len(statuses)} deps present.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m harness")
    parser.add_argument(
        "step",
        choices=["doctor", "inventory", "walk", "build", "all"],
        help="which phase to run",
    )
    parser.add_argument(
        "--socket",
        default="/tmp/jaato.sock",
        help="daemon IPC socket path (default: /tmp/jaato.sock)",
    )
    args = parser.parse_args()

    if args.step == "doctor":
        return _run_doctor()

    MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    if args.step in ("inventory", "all"):
        _deps.gate(_deps.INVENTORY_DEPS, phase="inventory")
        print("=== inventory ===")
        InventoryGenerator(manual_dir=MANUAL_DIR).run()

    if args.step in ("walk", "all"):
        _deps.gate(_deps.WALK_DEPS, phase="walk")
        print("=== walk ===")
        Walker(socket=args.socket, manual_dir=MANUAL_DIR).run()

    if args.step in ("build", "all"):
        _deps.gate(_deps.BUILD_DEPS, phase="build")
        print("=== build ===")
        PDFBuilder(manual_dir=MANUAL_DIR, build_dir=BUILD_DIR).run()

    return 0


if __name__ == "__main__":
    sys.exit(main())
