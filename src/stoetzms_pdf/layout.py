"""Passes 2 and 3: the document plan and the table-of-contents fixed point.

The plan is the ordered list of parts (cover, TOC, dividers, source
documents) plus the navigation tree (sections > documents > subsections)
whose entries point into those parts. Page positions are always derived from
part sizes, never entered by hand.

The TOC's own length affects every page number after it, and the page
numbers it prints can affect its length. :func:`resolve_toc` renders it
until the page count it was laid out for equals the page count it produces.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

import pikepdf

from .config import Project, ResolvedDocument, ResolvedSection, Subsection
from .errors import BuildError, Diagnostics
from .numbering import PageLabels, plan_labels
from .render import LINK_SCHEME, Renderer
from .sources import ImageSet, OutlineNode, SourcePdf

MAX_TOC_PASSES = 8


@dataclass(eq=False)
class Part:
    kind: str  # "cover" | "toc" | "divider" | "document"
    title: str
    page_count: int
    data: bytes | None = None  # rendered pages; source documents use `source`
    source: SourcePdf | None = None
    section: ResolvedSection | None = None
    document: ResolvedDocument | None = None
    start: int = 0  # physical 0-based index of the first page

    @property
    def pages(self) -> range:
        return range(self.start, self.start + self.page_count)


@dataclass(eq=False)
class Entry:
    id: int
    kind: str  # "section" | "document" | "subsection" | "source-bookmark"
    level: int
    title: str
    part: Part
    offset: int = 0  # page within the part
    number: str | None = None
    children: list[Entry] = field(default_factory=list)

    @property
    def page(self) -> int:
        return self.part.start + self.offset

    @property
    def display_title(self) -> str:
        return f"{self.number} {self.title}" if self.number else self.title


@dataclass
class Plan:
    parts: list[Part]
    sections: list[Entry]
    toc_part: Part | None = None

    def layout(self) -> None:
        position = 0
        for part in self.parts:
            part.start = position
            position += part.page_count

    @property
    def total_pages(self) -> int:
        return sum(part.page_count for part in self.parts)

    @property
    def front_matter_pages(self) -> int:
        """Cover and TOC pages: everything before the first section."""
        count = 0
        for part in self.parts:
            if part.kind not in ("cover", "toc"):
                break
            count += part.page_count
        return count

    def entries(self) -> list[Entry]:
        found: list[Entry] = []

        def walk(items: list[Entry]) -> None:
            for item in items:
                found.append(item)
                walk(item.children)

        walk(self.sections)
        return found

    def entry_by_id(self) -> dict[int, Entry]:
        return {entry.id: entry for entry in self.entries()}


def build_plan(project: Project, sources: dict[int, SourcePdf | ImageSet],
               renderer: Renderer) -> Plan:
    doc = project.document
    parts: list[Part] = []
    sections: list[Entry] = []
    next_id = iter(range(1, 1_000_000))

    if doc.cover.enabled:
        cover = renderer.render_cover()
        parts.append(Part("cover", doc.cover.title or doc.title, cover.page_count, cover.data))

    toc_part = None
    if doc.toc.enabled:
        toc_part = Part("toc", doc.toc.title or project.labels["toc_title"], 1)
        parts.append(toc_part)

    for section in project.sections:
        number = f"{section.number}." if doc.number_sections else None
        section_parts: list[Part] = []
        if section.divider is not None:
            rendered = renderer.render_divider(section)
            section_parts.append(Part("divider", section.title, rendered.page_count,
                                      rendered.data, section=section))
        document_entries = []
        for document in section.documents:
            source = sources[id(document)]
            if isinstance(source, ImageSet):
                source = source.to_source(renderer.render_images(source).data)
            part = Part("document", document.title, source.page_count, source=source,
                        section=section, document=document)
            section_parts.append(part)
            entry = Entry(next(next_id), "document", 2, document.title, part)
            entry.children = _subsection_entries(document.entry.subsections, part, 3, next_id)
            if document.source_bookmarks:
                entry.children += _outline_entries(source.outline, part, 3, next_id)
            document_entries.append(entry)
        parts.extend(section_parts)
        sections.append(Entry(next(next_id), "section", 1, section.title, section_parts[0],
                              number=number, children=document_entries))

    plan = Plan(parts, sections, toc_part)
    plan.layout()
    return plan


def _subsection_entries(subsections: list[Subsection], part: Part, level: int,
                        next_id) -> list[Entry]:
    return [
        Entry(next(next_id), "subsection", level, sub.title, part, sub.page - 1,
              children=_subsection_entries(sub.subsections, part, level + 1, next_id))
        for sub in subsections
    ]


def _outline_entries(nodes: list[OutlineNode], part: Part, level: int, next_id) -> list[Entry]:
    return [
        Entry(next(next_id), "source-bookmark", level, node.title, part, node.page,
              children=_outline_entries(node.children, part, level + 1, next_id))
        for node in nodes
    ]


def toc_entries(project: Project, plan: Plan, labels: PageLabels) -> list[dict[str, Any]]:
    """The TOC tree as template data, filtered by max_depth and entry options."""
    toc = project.document.toc
    max_depth = toc.max_depth if toc.include_document_entries else 1

    def convert(entries: list[Entry]) -> list[dict[str, Any]]:
        result = []
        for entry in entries:
            if entry.level > max_depth or entry.kind == "source-bookmark":
                continue
            result.append({
                "id": entry.id,
                "level": entry.level,
                "kind": entry.kind,
                "number": entry.number,
                "title": entry.title,
                "page": entry.page + 1,
                "label": labels.label(entry.page),
                "href": f"{LINK_SCHEME}entry/{entry.id}",
                "children": convert(entry.children),
            })
        return result

    return convert(plan.sections)


def toc_link_targets(project: Project, plan: Plan) -> list[int]:
    """Physical pages the TOC links point to, in document order."""
    if not project.document.toc.links:
        return []
    labels = plan_labels(project.document.page_numbering, plan.total_pages,
                         plan.front_matter_pages)
    ids = []

    def walk(items: list[dict[str, Any]]) -> None:
        for item in items:
            ids.append(item["id"])
            walk(item["children"])

    walk(toc_entries(project, plan, labels))
    by_id = plan.entry_by_id()
    return [by_id[i].page for i in ids]


def resolve_toc(project: Project, plan: Plan, renderer: Renderer,
                diag: Diagnostics) -> PageLabels:
    """Render the TOC until its page count is stable; return the final labels."""
    numbering = project.document.page_numbering
    toc_part = plan.toc_part
    if toc_part is None:
        plan.layout()
        return plan_labels(numbering, plan.total_pages, plan.front_matter_pages)

    attempts: list[tuple[int, int]] = []  # (pages laid out for, pages produced)
    guess = 1
    for _ in range(MAX_TOC_PASSES):
        toc_part.page_count = guess
        plan.layout()
        labels = plan_labels(numbering, plan.total_pages, plan.front_matter_pages)
        rendered = renderer.render_toc(toc_entries(project, plan, labels))
        attempts.append((guess, rendered.page_count))

        if rendered.page_count == guess:
            toc_part.data = rendered.data
            return labels

        tried = {laid_out for laid_out, _ in attempts}
        if rendered.page_count < guess and rendered.page_count in tried:
            # Oscillating: laid out for N it needs fewer pages, laid out for
            # fewer it needs N. Keep the layout for N and pad with blank
            # pages, so every printed number stays correct.
            toc_part.data = _pad_pages(rendered.data, guess - rendered.page_count)
            diag.warning(f"the table of contents was padded with "
                         f"{guess - rendered.page_count} blank page(s) to keep its page "
                         "numbers stable")
            return labels
        guess = rendered.page_count

    history = ", ".join(f"laid out for {a} -> rendered {b}" for a, b in attempts)
    raise BuildError("the table of contents did not settle on a page count "
                     f"after {MAX_TOC_PASSES} passes ({history}); page references would "
                     "be wrong, so no output was written")


def _pad_pages(data: bytes, count: int) -> bytes:
    with pikepdf.open(io.BytesIO(data)) as pdf:
        last = pdf.pages[-1]
        box = [float(v) for v in last.mediabox]
        size = (box[2] - box[0], box[3] - box[1])
        for _ in range(count):
            pdf.add_blank_page(page_size=size)
        out = io.BytesIO()
        pdf.save(out, deterministic_id=True)
        return out.getvalue()
