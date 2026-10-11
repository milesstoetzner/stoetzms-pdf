"""Build orchestration: validate, plan, assemble, verify, replace atomically."""

from __future__ import annotations

import os
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import pikepdf

from .assemble import assemble, save
from .config import Project, load_project
from .errors import BuildError, Diagnostics, StoetzmsPdfError, StrictModeError
from .layout import Plan, build_plan, resolve_toc
from .numbering import PageLabels
from .render import Renderer
from .sources import inspect_sources
from .validate import validate_output


@dataclass
class BuildResult:
    project: Project
    plan: Plan
    labels: PageLabels
    diagnostics: Diagnostics
    output: Path | None  # None for --check


def build(config_path: Path | None = None, output: Path | None = None,
          check_only: bool = False,
          strict: bool = False) -> BuildResult:
    """Run every pass. Raises a StoetzmsPdfError; never writes partial output.

    With ``strict``, any warning aborts the build before the output is replaced.
    """
    # Pass 1: configuration and inputs.
    project = load_project(config_path, output)
    diag = project.diagnostics
    try:
        sources = inspect_sources(project, diag)
        diag.raise_if_errors()

        # Passes 2 and 3: generated pages, positions, and a TOC that fits them.
        renderer = Renderer(project, diag)
        plan = build_plan(project, sources, renderer)
        labels = resolve_toc(project, plan, renderer, diag)

        if check_only:
            _enforce_strict(strict, diag)
            return BuildResult(project, plan, labels, diag, None)

        # Pass 4: assemble, verify, replace.
        _write_atomically(project, plan, labels, renderer, diag, strict)
        return BuildResult(project, plan, labels, diag, project.output)
    except StoetzmsPdfError as exc:
        exc.warnings = diag.warnings
        raise


def _enforce_strict(strict: bool, diag: Diagnostics) -> None:
    if strict and diag.warnings:
        raise StrictModeError(f"{len(diag.warnings)} warning(s) and --strict was given")


def _write_atomically(project: Project, plan: Plan, labels: PageLabels, renderer: Renderer,
                      diag: Diagnostics, strict: bool) -> None:
    target = project.output
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BuildError(f"cannot create output directory {target.parent}: {exc}") from None

    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with ExitStack() as stack:
            out, min_version = assemble(project, plan, labels, renderer, diag, stack)
            try:
                save(out, tmp, min_version)
            except (pikepdf.PdfError, OSError) as exc:
                raise BuildError(f"writing the PDF failed: {exc}") from None
        validate_output(tmp, project, plan, labels, diag)
        _enforce_strict(strict, diag)
        _match_permissions(tmp, target)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()


def _match_permissions(tmp: Path, target: Path) -> None:
    """mkstemp creates 0600 files; give the output normal permissions."""
    if target.exists():
        mode = target.stat().st_mode & 0o777
    else:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    os.chmod(tmp, mode)
