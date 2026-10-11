"""Check the written PDF against the plan before it replaces the old output.

This re-reads the saved file, so it catches anything lost between the plan
and the bytes on disk: page count and order, page sizes, bookmark targets,
TOC link targets and page labels.
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name

from .assemble import LINK_ANNOT_PREFIX, expected_outline
from .config import Project
from .errors import BuildError, Diagnostics
from .layout import Plan, toc_entries
from .numbering import PageLabels
from .sources import page_geometry


def validate_output(path: Path, project: Project, plan: Plan, labels: PageLabels,
                    diag: Diagnostics) -> None:
    problems: list[str] = []
    try:
        pdf = pikepdf.open(path)
    except pikepdf.PdfError as exc:
        raise BuildError(f"the generated PDF cannot be read back: {exc}") from None

    with pdf:
        if len(pdf.pages) != plan.total_pages:
            raise BuildError(f"the generated PDF has {len(pdf.pages)} pages, "
                             f"expected {plan.total_pages}")
        page_index = {page.obj.objgen: i for i, page in enumerate(pdf.pages)}

        problems += _check_geometry(pdf, project, plan)
        if project.document.bookmarks.enabled:
            problems += _check_outline(pdf, project, plan, page_index)
        if plan.toc_part is not None and project.document.toc.links:
            problems += _check_toc_links(pdf, project, plan, labels, page_index, diag)
        if project.document.page_numbering.page_labels:
            problems += _check_labels(pdf, labels)
        for issue in pdf.check_pdf_syntax():
            diag.warning(f"output PDF check: {issue}")

    if problems:
        shown = problems[:10] + ([f"... and {len(problems) - 10} more"] if len(problems) > 10 else [])
        raise BuildError("the generated PDF failed validation; the previous output was kept:\n  "
                         + "\n  ".join(shown))


def _check_geometry(pdf: pikepdf.Pdf, project: Project, plan: Plan) -> list[str]:
    problems = []
    for part in plan.parts:
        if part.source is None:
            continue
        name = part.source.document.shown
        for offset, expected in enumerate(part.source.pages):
            actual = page_geometry(pdf.pages[part.start + offset])
            if (abs(actual.width - expected.width) > 0.01
                    or abs(actual.height - expected.height) > 0.01
                    or actual.rotate != expected.rotate):
                problems.append(f"page {part.start + offset + 1} should be page {offset + 1} of "
                                f"{name} but its size or rotation differs")
    return problems


def _dest_page(dest, page_index: dict) -> int | None:
    if isinstance(dest, Array) and len(dest) and isinstance(dest[0], Dictionary):
        return page_index.get(dest[0].objgen)
    return None


def _check_outline(pdf: pikepdf.Pdf, project: Project, plan: Plan,
                   page_index: dict) -> list[str]:
    actual: list[tuple[int, str, int | None]] = []

    def walk(items, depth: int) -> None:
        for item in items:
            dest = item.destination
            if dest is None and item.action is not None:
                dest = item.action.get("/D")
            actual.append((depth, item.title, _dest_page(dest, page_index)))
            walk(item.children, depth + 1)

    with pdf.open_outline() as outline:
        walk(outline.root, 0)
    expected = expected_outline(project, plan)
    if [(d, t) for d, t, _ in actual] != [(d, t) for d, t, _ in expected]:
        return ["the bookmark tree does not match the configured structure"]
    problems = []
    for (_, title, got), (_, _, want) in zip(actual, expected):
        if got != want:
            shown = "nothing" if got is None else f"page {got + 1}"
            problems.append(f"bookmark {title!r} points to {shown}, expected page {want + 1}")
    return problems


def _check_toc_links(pdf: pikepdf.Pdf, project: Project, plan: Plan, labels: PageLabels,
                     page_index: dict, diag: Diagnostics) -> list[str]:
    by_id = plan.entry_by_id()
    wanted: list[int] = []

    def walk(items) -> None:
        for item in items:
            wanted.append(item["id"])
            walk(item["children"])

    walk(toc_entries(project, plan, labels))

    found: dict[int, int | None] = {}
    problems = []
    for index in plan.toc_part.pages:
        for annot in pdf.pages[index].obj.get("/Annots", []):
            action = annot.get("/A")
            if isinstance(action, Dictionary) and action.get("/S") == Name.URI \
                    and str(action.get("/URI", "")).startswith("stoetzms-pdf:"):
                problems.append(f"TOC page {index + 1} has an unresolved link {action.URI}")
            name = str(annot.get("/NM", ""))
            if name.startswith(LINK_ANNOT_PREFIX):
                entry_id = int(name[len(LINK_ANNOT_PREFIX):])
                found.setdefault(entry_id, _dest_page(annot.get("/Dest"), page_index))

    missing = [by_id[i].title for i in wanted if i not in found]
    if missing:
        diag.warning("the table of contents template produced no link for: "
                     + ", ".join(repr(t) for t in missing[:5])
                     + (" ..." if len(missing) > 5 else ""))
    for entry_id, got in found.items():
        want = by_id[entry_id].page
        if got != want:
            shown = "nothing" if got is None else f"page {got + 1}"
            problems.append(f"TOC link for {by_id[entry_id].title!r} points to {shown}, "
                            f"expected page {want + 1}")
    return problems


def _check_labels(pdf: pikepdf.Pdf, labels: PageLabels) -> list[str]:
    for index, page in enumerate(pdf.pages):
        if page.label != labels.label(index):
            return [f"page {index + 1} is labelled {page.label!r}, "
                    f"expected {labels.label(index)!r}"]
    return []
