"""Command-line entry point: ``stoetzms-pdf [stoetzms-pdf.yaml]``."""

from __future__ import annotations

import argparse
import logging
import sys
import warnings
from pathlib import Path

# WeasyPrint warns on import when no fonts are installed; the build reports
# that itself as an error with a fix, so the raw warning is only noise.
warnings.filterwarnings("ignore", message="No fonts configured", category=UserWarning)

from . import __version__  # noqa: E402
from .build import BuildResult, build  # noqa: E402
from .errors import Diagnostics, StoetzmsPdfError  # noqa: E402

EXIT_OK = 0  # failures: 1 build failed, 2 invalid config/input, 3 --strict warnings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stoetzms-pdf",
        description="Assemble PDFs and images into one document with a cover, table of contents, "
                    "section dividers, bookmarks and page numbers, as described by a YAML file.",
    )
    parser.add_argument("config", type=Path, nargs="?",
                        help="project file, or a directory containing stoetzms-pdf.yaml "
                             "(default: stoetzms-pdf.yaml in the current directory)")
    parser.add_argument("-o", "--output", type=Path,
                        help="output PDF (overrides document.output; relative to the current "
                             "directory)")
    parser.add_argument("--check", action="store_true",
                        help="validate the configuration, inputs and templates without writing "
                             "a PDF")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="show the page plan and rendering details")
    parser.add_argument("-q", "--quiet", action="store_true", help="only print problems")
    parser.add_argument("--strict", action="store_true",
                        help="treat warnings as errors (exit code 3, previous output kept)")
    parser.add_argument("--version", action="version", version=f"stoetzms-pdf {__version__}")
    return parser


def _print_diagnostics(diag: Diagnostics) -> None:
    for item in diag.items:
        print(item, file=sys.stderr)


def _print_plan(result: BuildResult) -> None:
    labels = result.labels
    rows = []
    for part in result.plan.parts:
        first, last = part.start, part.start + part.page_count - 1
        pages = f"{first + 1}" if first == last else f"{first + 1}-{last + 1}"
        printed = labels.label(first) if first == last else f"{labels.label(first)}-{labels.label(last)}"
        title = part.title
        if part.source is not None:
            title += f"  [{part.source.document.shown}]"
        rows.append((pages, printed, part.kind, title))
    width = max(len(r[0]) for r in rows + [("pages", "", "", "")])
    lwidth = max(len(r[1]) for r in rows + [("", "label", "", "")])
    print(f"  {'pages':<{width}}  {'label':<{lwidth}}  {'kind':<8}  title")
    for pages, printed, kind, title in rows:
        print(f"  {pages:<{width}}  {printed:<{lwidth}}  {kind:<8}  {title}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(format="%(name)s: %(message)s",
                        level=logging.INFO if args.verbose else logging.ERROR)
    # WeasyPrint warnings are collected and reported as our own diagnostics.
    logging.getLogger("weasyprint").propagate = False
    logging.getLogger("fontTools").setLevel(logging.ERROR)

    try:
        result = build(args.config, output=args.output, check_only=args.check,
                       strict=args.strict)
    except StoetzmsPdfError as exc:
        for item in [*exc.warnings, *exc.problems]:
            print(item, file=sys.stderr)
        if args.check:
            print("Check failed.", file=sys.stderr)
        else:
            print("No output was written; the previous output (if any) is unchanged.",
                  file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("Interrupted; the previous output (if any) is unchanged.", file=sys.stderr)
        return 130

    _print_diagnostics(result.diagnostics)
    if args.verbose:
        _print_plan(result)
    if args.quiet:
        return EXIT_OK

    total = result.plan.total_pages
    warnings = len(result.diagnostics.warnings)
    note = f", {warnings} warning(s)" if warnings else ""
    if args.check:
        print(f"OK: {result.project.display_path(result.project.config_path)} is valid; "
              f"the output would have {total} pages{note}.")
    else:
        print(f"Wrote {result.output} ({total} pages{note}).")
    return EXIT_OK
