"""Pass 4: assemble the final PDF from the resolved plan.

Pages are copied, never re-rendered: source content streams, fonts, vector
graphics, links and form fields are carried over as they are. Page numbers
are laid over the page as a separate form XObject, wrapped so the original
content's graphics state cannot affect them and vice versa.
"""

from __future__ import annotations

import datetime
import io
from contextlib import ExitStack

import pikepdf
from pikepdf import Array, Dictionary, Name

from . import __version__
from .config import Project
from .errors import BuildError, Diagnostics
from .layout import Entry, Plan
from .numbering import PageLabels, stamp_text
from .render import LINK_SCHEME, Renderer
from .sources import page_geometry

# /NM given to resolved template links, so validation can find them again.
LINK_ANNOT_PREFIX = "stoetzms-pdf-entry-"


def assemble(project: Project, plan: Plan, labels: PageLabels, renderer: Renderer,
             diag: Diagnostics, stack: ExitStack) -> tuple[pikepdf.Pdf, str]:
    """Build the output in memory; returns it and the PDF version it needs.

    Inputs stay open on ``stack``: their streams are copied lazily on save.
    """
    out = stack.enter_context(pikepdf.new())
    versions = []

    for part in plan.parts:
        if part.source is not None:
            src = stack.enter_context(part.source.open())
            name = part.source.document.shown
        else:
            if part.data is None:
                raise BuildError(f"internal error: {part.kind} pages were never rendered")
            src = stack.enter_context(pikepdf.open(io.BytesIO(part.data)))
            name = part.kind
        versions.append(src.pdf_version)

        before = len(out.pages)
        result = out.add_pages_from(src)
        added = len(out.pages) - before
        if added != part.page_count:
            raise BuildError(f"{name}: expected {part.page_count} page(s), copied {added}")
        if result.dropped_dests:
            diag.warning(f"{name}: {len(result.dropped_dests)} internal link target(s) could not "
                         "be carried over")
        if result.partial_fields:
            diag.warning(f"{name}: form fields only partly carried over: "
                         + ", ".join(result.partial_fields[:5]))
        if result.renamed_fields:
            diag.warning(f"{name}: form fields renamed to avoid clashes with other documents: "
                         + ", ".join(f"{a} -> {b}" for a, b in list(result.renamed_fields.items())[:5]))

    _resolve_internal_links(out, plan)
    if project.document.bookmarks.enabled:
        _write_outline(out, project, plan)
    if project.document.page_numbering.page_labels:
        out.Root.PageLabels = labels.pdf_page_labels()
    if project.document.page_numbering.enabled:
        _stamp_page_numbers(out, project, plan, labels, renderer)
    _write_metadata(out, project)
    return out, max(versions, default="1.7")


def save(out: pikepdf.Pdf, path, min_version: str) -> None:
    out.save(
        path,
        deterministic_id=True,
        min_version=max(min_version, "1.7"),
        object_stream_mode=pikepdf.ObjectStreamMode.generate,
    )


# -- links ------------------------------------------------------------------------


def _resolve_internal_links(out: pikepdf.Pdf, plan: Plan) -> None:
    """Turn the ``stoetzms-pdf:entry/<id>`` URIs from templates into GoTo links."""
    by_id = plan.entry_by_id()
    for part in plan.parts:
        if part.source is not None:
            continue
        for index in part.pages:
            page = out.pages[index]
            for annot in page.obj.get("/Annots", []):
                action = annot.get("/A")
                if not isinstance(action, Dictionary) or action.get("/S") != Name.URI:
                    continue
                uri = str(action.get("/URI", ""))
                if not uri.startswith(LINK_SCHEME):
                    continue
                entry = _link_entry(uri, by_id)
                if entry is None:
                    raise BuildError(f"{part.kind} page {index + 1}: link {uri!r} does not name "
                                     "an entry of this document")
                del annot["/A"]
                annot.Dest = Array([out.pages[entry.page].obj, Name.Fit])
                annot.NM = pikepdf.String(f"{LINK_ANNOT_PREFIX}{entry.id}")


def _link_entry(uri: str, by_id: dict[int, Entry]) -> Entry | None:
    rest = uri[len(LINK_SCHEME):]
    if not rest.startswith("entry/"):
        return None
    try:
        return by_id.get(int(rest[len("entry/"):]))
    except ValueError:
        return None


# -- bookmarks ------------------------------------------------------------------


def expected_outline(project: Project, plan: Plan) -> list[tuple[int, str, int]]:
    """(depth, title, page) for every bookmark, in order."""
    bookmarks = project.document.bookmarks
    rows: list[tuple[int, str, int]] = []

    def walk(entries: list[Entry], depth: int) -> None:
        for entry in entries:
            if entry.kind == "subsection" and not bookmarks.include_subsections:
                continue
            rows.append((depth, entry.display_title, entry.page))
            walk(entry.children, depth + 1)

    walk(plan.sections, 0)
    return rows


def _write_outline(out: pikepdf.Pdf, project: Project, plan: Plan) -> None:
    bookmarks = project.document.bookmarks

    def convert(entries: list[Entry]) -> list[pikepdf.OutlineItem]:
        items = []
        for entry in entries:
            if entry.kind == "subsection" and not bookmarks.include_subsections:
                continue
            item = pikepdf.OutlineItem(entry.display_title, entry.page, pikepdf.PageLocation.Fit)
            item.children.extend(convert(entry.children))
            item.is_closed = not (entry.kind == "section" and bookmarks.expand_sections)
            items.append(item)
        return items

    with out.open_outline() as outline:
        outline.root.extend(convert(plan.sections))
    out.Root.PageMode = Name.UseOutlines


# -- page numbers -----------------------------------------------------------------


def stamped_pages(project: Project, plan: Plan) -> list[int]:
    numbering = project.document.page_numbering
    if not numbering.enabled:
        return []
    wanted = {"cover": numbering.cover, "toc": numbering.toc,
              "divider": numbering.dividers, "document": numbering.source_documents}
    return [index for part in plan.parts if wanted[part.kind] for index in part.pages]


def _display_matrix(page: pikepdf.Page) -> tuple[float, ...]:
    """Map display space (the page as viewed, origin bottom-left) to user space."""
    x0, y0, x1, y1 = (float(v) for v in page.cropbox)
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    rotate = int(page.obj.get("/Rotate", 0)) % 360
    return {
        0: (1, 0, 0, 1, x0, y0),
        90: (0, 1, -1, 0, x1, y0),
        180: (-1, 0, 0, -1, x1, y1),
        270: (0, -1, 1, 0, x0, y1),
    }[rotate]


def _stamp_page_numbers(out: pikepdf.Pdf, project: Project, plan: Plan, labels: PageLabels,
                        renderer: Renderer) -> None:
    targets = stamped_pages(project, plan)
    if not targets:
        return
    numbering = project.document.page_numbering
    requests = []
    for index in targets:
        geometry = page_geometry(out.pages[index])
        requests.append((geometry.width, geometry.height, stamp_text(numbering, labels, index)))
    rendered = renderer.render_page_numbers(requests)

    with pikepdf.open(io.BytesIO(rendered.data)) as stamps:
        for index, stamp_page in zip(targets, stamps.pages):
            page = out.pages[index]
            xobject = out.copy_foreign(stamp_page.as_form_xobject())
            name = _free_xobject_name(page, f"/StoetzmsPdfNum{index + 1}")
            page.add_resource(xobject, Name.XObject, name)
            matrix = " ".join(_num(v) for v in _display_matrix(page))
            page.contents_add(out.make_stream(b"q\n"), prepend=True)
            page.contents_add(out.make_stream(
                f"\nQ\nq {matrix} cm {name} Do Q\n".encode("ascii")))


def _free_xobject_name(page: pikepdf.Page, base: str) -> Name:
    """A resource name not used by the page; deterministic, unlike a random prefix."""
    existing = page.resources.get("/XObject", Dictionary())
    name, suffix = base, 1
    while name in existing:
        suffix += 1
        name = f"{base}_{suffix}"
    return Name(name)


def _num(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


# -- metadata -------------------------------------------------------------------


def _write_metadata(out: pikepdf.Pdf, project: Project) -> None:
    doc = project.document
    creator = f"pdf.stoetz.ms {__version__}"
    with out.open_metadata(set_pikepdf_as_editor=False, update_docinfo=True) as meta:
        meta["dc:title"] = doc.title
        if doc.author:
            meta["dc:creator"] = [doc.author]
        if doc.subject:
            meta["dc:description"] = doc.subject
        if doc.keywords:
            meta["pdf:Keywords"] = ", ".join(doc.keywords)
        meta["xmp:CreatorTool"] = creator
        meta["pdf:Producer"] = creator
        meta["dc:language"] = [doc.language]
        if doc.timestamp:
            now = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(
                timespec="seconds")
            meta["xmp:CreateDate"] = now
            meta["xmp:ModifyDate"] = now
    out.Root.Lang = pikepdf.String(doc.language)
    out.Root.ViewerPreferences = Dictionary(DisplayDocTitle=True)
