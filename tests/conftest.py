"""Fixture PDFs built on the fly, and helpers to build and inspect projects."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pymupdf
import pytest

from stoetzms_pdf.build import BuildResult, build

A4 = (595.28, 841.89)
LETTER = (612, 792)
A4_LANDSCAPE = (841.89, 595.28)


def make_pdf(path: Path, pages: list[str] | int, size=A4, rotate: int = 0,
             goto_links: list[tuple[int, int]] | None = None,
             toc: list[list] | None = None, sizes: list | None = None) -> Path:
    """Write a PDF whose page N contains the text ``<stem>-p<N>``.

    ``pages`` is a list of page texts or a page count. ``goto_links`` adds
    internal links (from page, to page), 0-based. ``toc`` sets bookmarks in
    PyMuPDF's [level, title, page] form.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(pages, int):
        pages = [f"{path.stem}-p{i + 1}" for i in range(pages)]
    doc = pymupdf.open()
    for index, text in enumerate(pages):
        width, height = sizes[index] if sizes else size
        page = doc.new_page(width=width, height=height)
        page.insert_text((72, 100), text, fontsize=14)
        if rotate:
            page.set_rotation(rotate)
    for source, target in goto_links or []:
        doc[source].insert_link({"kind": pymupdf.LINK_GOTO, "page": target,
                                 "from": pymupdf.Rect(72, 200, 300, 220)})
    if toc:
        doc.set_toc(toc)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def project(tmp_path: Path):
    """Write a project file (dedented YAML) and return its path."""

    def write(yaml_text: str, name: str = "stoetzms-pdf.yaml") -> Path:
        path = tmp_path / name
        path.write_text(textwrap.dedent(yaml_text), encoding="utf-8")
        return path

    return write


def run(config: Path, **kwargs) -> BuildResult:
    return build(config, **kwargs)


def page_texts(path: Path) -> list[str]:
    with pymupdf.open(path) as doc:
        return [page.get_text() for page in doc]


def bookmarks(path: Path) -> list[list]:
    with pymupdf.open(path) as doc:
        return doc.get_toc(simple=True)


def internal_links(path: Path, page_index: int) -> list[int]:
    """Target pages (0-based) of GoTo links on a page, one per text line.

    A TOC line may carry several link rectangles (number, title, leader);
    rectangles on the same line are counted once.
    """
    with pymupdf.open(path) as doc:
        links = [link for link in doc[page_index].get_links()
                 if link["kind"] == pymupdf.LINK_GOTO]
    lines: list[tuple[float, int]] = []  # (vertical centre, target)
    for link in sorted(links, key=lambda link: (link["from"].y0 + link["from"].y1)):
        centre = (link["from"].y0 + link["from"].y1) / 2
        if not lines or abs(centre - lines[-1][0]) > 4:
            lines.append((centre, link["page"]))
    return [target for _, target in lines]


def page_labels(path: Path) -> list[str]:
    with pymupdf.open(path) as doc:
        return [page.get_label() for page in doc]


def bottom_text(path: Path, page_index: int, band: float = 60) -> str:
    """Text in the bottom band of the page as displayed (rotation applied)."""
    with pymupdf.open(path) as doc:
        page = doc[page_index]
        rect = page.rect  # displayed rectangle
        words = []
        for x0, y0, x1, y1, word, *_ in page.get_text("words"):
            box = pymupdf.Rect(x0, y0, x1, y1) * page.rotation_matrix
            if box.y0 > rect.height - band:
                words.append(word)
        return " ".join(words)
