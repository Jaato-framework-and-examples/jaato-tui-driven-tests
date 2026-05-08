"""Dependency probes used by ``harness doctor`` and per-phase gates.

The harness has three classes of external dependency:

* **Python modules** — ``jaato_sdk`` (the SDK package shipped from
  ``Jaato-framework-and-examples/jaato/jaato-sdk``) and ``yaml``
  (``pyyaml`` on PyPI).  Pip-installable.
* **System binaries** — ``tmux`` (walk), ``pandoc`` and ``xelatex``
  (build), plus ``fc-list`` / ``kpsewhich`` used internally to verify
  fonts and TeX packages.  OS-level installs.
* **TeX assets** — fonts (DejaVu family, FreeMono) and LaTeX packages
  (``ucharclasses.sty``, ``fontspec.sty``).  Bundled with the
  ``texlive-*`` packages.

Each phase declares the subset it requires.  The ``doctor`` subcommand
runs the union of all of them.

The probes are deliberately simple: shell out to ``which`` /
``fc-list`` / ``kpsewhich`` / ``importlib.import_module`` and report
present/absent.  No version checking — the harness historically tracks
which versions matter via memory, and an over-eager version pin would
just generate noise.
"""

from __future__ import annotations

import importlib
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, List, Optional


# ----------------------------------------------------------------------
# Probe primitives
# ----------------------------------------------------------------------


def _has_binary(name: str) -> bool:
    return shutil.which(name) is not None


def _has_font(family: str) -> bool:
    if not _has_binary("fc-list"):
        return False
    try:
        out = subprocess.run(
            ["fc-list", ":family"], capture_output=True, text=True,
            timeout=5, check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return family.lower() in out.stdout.lower()


def _has_texpkg(filename: str) -> bool:
    if not _has_binary("kpsewhich"):
        return False
    try:
        out = subprocess.run(
            ["kpsewhich", filename], capture_output=True, text=True,
            timeout=5, check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return out.returncode == 0 and bool(out.stdout.strip())


def _has_python(module: str) -> bool:
    try:
        importlib.import_module(module)
        return True
    except ImportError:
        return False


# ----------------------------------------------------------------------
# Dep declarations
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Dep:
    """A single check.

    Attributes:
        name:    Display name (what the user sees).
        kind:    One of {"binary", "font", "texpkg", "python"}.
        probe:   Zero-arg callable returning True if available.
        hint:    One-line install instruction for when ``probe()`` is False.
    """

    name: str
    kind: str
    probe: Callable[[], bool]
    hint: str


@dataclass
class DepStatus:
    dep: Dep
    present: bool


# ---- Python -----------------------------------------------------------

PY_JAATO_SDK = Dep(
    name="jaato_sdk", kind="python",
    probe=lambda: _has_python("jaato_sdk"),
    hint="pip install -e ../jaato/jaato-sdk  (editable install from sibling repo)",
)

PY_YAML = Dep(
    name="pyyaml", kind="python",
    probe=lambda: _has_python("yaml"),
    hint="pip install pyyaml",
)

# ---- Binaries ---------------------------------------------------------

BIN_TMUX = Dep(
    name="tmux", kind="binary",
    probe=lambda: _has_binary("tmux"),
    hint="apt install tmux",
)

BIN_PANDOC = Dep(
    name="pandoc", kind="binary",
    probe=lambda: _has_binary("pandoc"),
    hint="apt install pandoc",
)

BIN_XELATEX = Dep(
    name="xelatex", kind="binary",
    probe=lambda: _has_binary("xelatex"),
    hint="apt install texlive-xetex",
)

# ---- Fonts ------------------------------------------------------------

FONT_DEJAVU_MONO = Dep(
    name="DejaVu Sans Mono", kind="font",
    probe=lambda: _has_font("DejaVu Sans Mono"),
    hint="apt install fonts-dejavu-core",
)

FONT_DEJAVU_SANS = Dep(
    name="DejaVu Sans", kind="font",
    probe=lambda: _has_font("DejaVu Sans"),
    hint="apt install fonts-dejavu-core",
)

FONT_DEJAVU_SERIF = Dep(
    name="DejaVu Serif", kind="font",
    probe=lambda: _has_font("DejaVu Serif"),
    hint="apt install fonts-dejavu-core",
)

FONT_FREEMONO = Dep(
    name="FreeMono", kind="font",
    probe=lambda: _has_font("FreeMono"),
    hint="apt install fonts-freefont-ttf",
)

# ---- TeX packages -----------------------------------------------------

TEX_UCHARCLASSES = Dep(
    name="ucharclasses.sty", kind="texpkg",
    probe=lambda: _has_texpkg("ucharclasses.sty"),
    hint="apt install texlive-fonts-extra",
)

TEX_FONTSPEC = Dep(
    name="fontspec.sty", kind="texpkg",
    probe=lambda: _has_texpkg("fontspec.sty"),
    hint="apt install texlive-xetex",
)


# ----------------------------------------------------------------------
# Phase groupings
# ----------------------------------------------------------------------

INVENTORY_DEPS: List[Dep] = [PY_JAATO_SDK, PY_YAML]

WALK_DEPS: List[Dep] = [PY_JAATO_SDK, PY_YAML, BIN_TMUX]

BUILD_DEPS: List[Dep] = [
    PY_YAML,
    BIN_PANDOC, BIN_XELATEX,
    FONT_DEJAVU_MONO, FONT_DEJAVU_SANS, FONT_DEJAVU_SERIF, FONT_FREEMONO,
    TEX_UCHARCLASSES, TEX_FONTSPEC,
]

ALL_DEPS: List[Dep] = list({
    id(d): d for d in (INVENTORY_DEPS + WALK_DEPS + BUILD_DEPS)
}.values())


# ----------------------------------------------------------------------
# Reporting + gating
# ----------------------------------------------------------------------


def check(deps: List[Dep]) -> List[DepStatus]:
    return [DepStatus(dep=d, present=d.probe()) for d in deps]


def report(statuses: List[DepStatus]) -> str:
    """Render a doctor-style table."""
    rows: List[str] = []
    width = max(len(s.dep.name) for s in statuses)
    for status in statuses:
        mark = "✓" if status.present else "✗"
        rows.append(
            f"  {mark}  {status.dep.name:<{width}}  ({status.dep.kind})"
        )
        if not status.present:
            rows.append(f"        → {status.dep.hint}")
    return "\n".join(rows)


def gate(deps: List[Dep], phase: str) -> None:
    """Raise SystemExit with install hints if any required dep is missing.

    Used at the top of each phase command — the user gets a single
    consolidated error rather than a confusing failure mid-run.
    """
    statuses = check(deps)
    missing = [s for s in statuses if not s.present]
    if not missing:
        return

    lines = [
        f"=== {phase}: missing {len(missing)} of {len(deps)} dependencies ===",
    ]
    for status in missing:
        lines.append(f"  ✗  {status.dep.name}  ({status.dep.kind})")
        lines.append(f"      → {status.dep.hint}")
    lines.append("")
    lines.append(
        "Run `python -m harness doctor` for a full environment report."
    )
    raise SystemExit("\n".join(lines))
