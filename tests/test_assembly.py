"""End-to-end builds: ordering, generated pages, navigation and numbering."""

from __future__ import annotations

import re
from pathlib import Path

import pikepdf
import pymupdf
import yaml

from stoetzms_pdf.build import build
from stoetzms_pdf.cli import main

from conftest import (A4, A4_LANDSCAPE, LETTER, bookmarks, bottom_text, internal_links,
                      make_pdf, page_labels, page_texts)


def three_section_project(tmp_path: Path, project, divider_2=True, **document):
    """Cover, TOC and three sections (2 + 1/3 + 1 source pages); 12 pages."""
    make_pdf(tmp_path / "docs/a.pdf", 2)
    make_pdf(tmp_path / "docs/b.pdf", 1)
    make_pdf(tmp_path / "docs/c.pdf", 3)
    make_pdf(tmp_path / "docs/d.pdf", 1)
    config = {
        "version": 1,
        "document": {"title": "Test Dossier", "output": "out/result.pdf", **document},
        "sections": [
            {"title": "First", "documents": [{"file": "docs/a.pdf", "title": "Doc A"}]},
            {"title": "Second", "divider": divider_2,
             "documents": [{"file": "docs/b.pdf", "title": "Doc B"},
                           {"file": "docs/c.pdf", "title": "Doc C"}]},
            {"title": "Third", "documents": ["docs/d.pdf"]},
        ],
    }
    return project(yaml.safe_dump(config, sort_keys=False))


def kinds(result) -> list[str]:
    return [part.kind for part in result.plan.parts for _ in part.pages]


def test_merges_in_declared_order_with_generated_pages(tmp_path, project):
    result = build(three_section_project(tmp_path, project))
    texts = page_texts(result.output)
    assert len(texts) == 12
    expected_sources = {3: "a-p1", 4: "a-p2", 6: "b-p1", 7: "c-p1", 8: "c-p2", 9: "c-p3",
                        11: "d-p1"}
    for index, marker in expected_sources.items():
        assert marker in texts[index], (index, texts[index])
    assert "Test Dossier" in texts[0]
    assert "Table of Contents" in texts[1]
    # Source pages appear exactly once.
    joined = "\n".join(texts)
    for marker in expected_sources.values():
        assert joined.count(marker) == 1


def test_divider_placement(tmp_path, project):
    result = build(three_section_project(tmp_path, project))
    assert kinds(result) == ["cover", "toc",
                             "divider", "document", "document",
                             "divider", "document", "document", "document", "document",
                             "divider", "document"]
    texts = page_texts(result.output)
    assert "First" in texts[2] and "Second" in texts[5] and "Third" in texts[10]


def test_section_without_divider_starts_with_its_document(tmp_path, project):
    result = build(three_section_project(tmp_path, project, divider_2=False))
    texts = page_texts(result.output)
    assert len(texts) == 11
    assert "b-p1" in texts[5]
    toc = bookmarks(result.output)
    second = next(item for item in toc if item[1] == "Second")
    assert second[2] == 6  # 1-based: the first page of Doc B
    doc_b = next(item for item in toc if item[1] == "Doc B")
    assert doc_b[2] == 6


def test_bookmarks_point_to_final_pages(tmp_path, project):
    result = build(three_section_project(tmp_path, project))
    assert bookmarks(result.output) == [
        [1, "First", 3], [2, "Doc A", 4],
        [1, "Second", 6], [2, "Doc B", 7], [2, "Doc C", 8],
        [1, "Third", 11], [2, "D", 12],
    ]


def test_toc_lists_correct_page_numbers_and_links(tmp_path, project):
    result = build(three_section_project(tmp_path, project))
    toc_text = page_texts(result.output)[1]
    lines = [line.strip() for line in toc_text.splitlines() if line.strip()]
    expected = {"First": "3", "Doc A": "4", "Second": "6", "Doc B": "7", "Doc C": "8",
                "Third": "11", "D": "12"}
    for title, number in expected.items():
        index = lines.index(title)
        # The title is followed by the leader and then the page number.
        following = " ".join(lines[index + 1:index + 3])
        assert re.search(rf"(^|\s|\.){number}(\s|$)", following), (title, following)
    # Links go to the same pages, in TOC order (0-based).
    assert internal_links(result.output, 1) == [2, 3, 5, 6, 7, 10, 11]


def test_toc_sections_only(tmp_path, project):
    config = three_section_project(tmp_path, project,
                                   toc={"include_document_entries": False})
    result = build(config)
    toc_text = page_texts(result.output)[1]
    assert "Doc A" not in toc_text and "First" in toc_text
    assert internal_links(result.output, 1) == [2, 5, 10]


def test_toc_spanning_several_pages(tmp_path, project):
    sections = []
    for s in range(7):
        documents = []
        for i in range(s * 10, s * 10 + 10):
            make_pdf(tmp_path / f"docs/doc{i:02d}.pdf", 1 + i % 3)
            documents.append({"file": f"docs/doc{i:02d}.pdf", "title": f"Document {i:02d}"})
        sections.append({"title": f"Section {s}", "documents": documents})
    config = project(yaml.safe_dump({"document": {"title": "Long"}, "sections": sections}))
    result = build(config)
    toc_part = result.plan.toc_part
    assert toc_part.page_count >= 2
    out = result.output
    texts = page_texts(out)

    # Every entry's link and printed number point to where its pages are.
    targets = []
    for page in toc_part.pages:
        targets += internal_links(out, page)
    entries = [e for e in result.plan.entries() if e.kind in ("section", "document")]
    assert targets == [e.page for e in entries]
    for entry in entries:
        if entry.kind == "document":
            number = int(entry.title.split()[-1])
            assert f"doc{number:02d}-p1" in texts[entry.page]
    # The last TOC entry's number is printed and correct.
    last = entries[-1]
    toc_text = "".join(texts[p] for p in toc_part.pages)
    assert str(last.page + 1) in toc_text.split(last.title, 1)[1]


def test_mixed_sizes_and_orientations_are_preserved(tmp_path, project):
    make_pdf(tmp_path / "a4.pdf", 1, size=A4)
    make_pdf(tmp_path / "letter.pdf", 1, size=LETTER)
    make_pdf(tmp_path / "landscape.pdf", 1, size=A4_LANDSCAPE)
    make_pdf(tmp_path / "rotated.pdf", 1, size=A4, rotate=90)
    make_pdf(tmp_path / "mixed.pdf", 2, sizes=[A4, A4_LANDSCAPE])
    config = project("""
        document:
          title: Sizes
          cover: false
          toc: false
          page_numbering: {source_documents: true}
        sections:
          - title: All
            divider: false
            documents: [a4.pdf, letter.pdf, landscape.pdf, rotated.pdf, mixed.pdf]
        """)
    result = build(config)
    with pikepdf.open(result.output) as pdf:
        boxes = [[round(float(v), 1) for v in page.mediabox] for page in pdf.pages]
        rotations = [int(page.obj.get("/Rotate", 0)) for page in pdf.pages]
    assert boxes == [[0, 0, 595.3, 841.9], [0, 0, 612, 792], [0, 0, 841.9, 595.3],
                     [0, 0, 595.3, 841.9], [0, 0, 595.3, 841.9], [0, 0, 841.9, 595.3]]
    assert rotations == [0, 0, 0, 90, 0, 0]
    # Page numbers sit upright at the bottom of each page as displayed.
    for index in range(6):
        assert bottom_text(result.output, index) == str(index + 1)
    # Source text stays selectable text, not an image.
    texts = page_texts(result.output)
    assert "rotated-p1" in texts[3]
    with pymupdf.open(result.output) as doc:
        assert all(not page.get_images() for page in doc)


def test_page_numbers_skip_cover_and_dividers(tmp_path, project):
    config = three_section_project(tmp_path, project, page_numbering={
        "cover": False, "toc": True, "dividers": False, "source_documents": True,
        "format": "Page {page} of {total}"})
    result = build(config)
    plan_kinds = kinds(result)
    for index, kind in enumerate(plan_kinds):
        text = bottom_text(result.output, index)
        if kind in ("cover", "divider"):
            assert text == "", (index, kind, text)
        else:
            assert text == f"Page {index + 1} of {len(plan_kinds)}"


def test_front_matter_roman_and_content_from_one(tmp_path, project):
    config = three_section_project(tmp_path, project, page_numbering={
        "count_from": "content", "front_matter_style": "lower-roman", "start_at": 1,
        "source_documents": True})
    result = build(config)
    labels = page_labels(result.output)
    assert labels[:4] == ["i", "ii", "1", "2"]
    assert labels[-1] == "10"
    assert bottom_text(result.output, 1) == "ii"  # TOC
    assert bottom_text(result.output, 3) == "2"  # first page of Doc A
    # The TOC prints printed numbers, not physical positions.
    toc_lines = [l.strip() for l in page_texts(result.output)[1].splitlines() if l.strip()]
    first = toc_lines.index("First")
    assert "1" in " ".join(toc_lines[first + 1:first + 3])
    assert "10" in " ".join(toc_lines[toc_lines.index("D") + 1:][:2])


def test_numbering_disabled_still_labels_pages(tmp_path, project):
    config = three_section_project(tmp_path, project,
                                   page_numbering={"enabled": False, "start_at": 5})
    result = build(config)
    assert all(bottom_text(result.output, i) == "" for i in range(12))
    assert page_labels(result.output)[:3] == ["5", "6", "7"]


def test_relative_paths_resolve_against_config_directory(tmp_path, project, monkeypatch):
    three_section_project(tmp_path, project)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    result = build(Path("../stoetzms-pdf.yaml"))
    assert result.output == tmp_path / "out" / "result.pdf"
    assert result.output.exists()
    assert not (elsewhere / "out").exists()


def test_cli_output_override_is_relative_to_cwd(tmp_path, project, monkeypatch, capsys):
    config = three_section_project(tmp_path, project)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    assert main([str(config), "--output", "custom.pdf"]) == 0
    assert (work / "custom.pdf").exists()
    assert "Wrote" in capsys.readouterr().out


def test_source_internal_links_and_uri_links_survive(tmp_path, project):
    make_pdf(tmp_path / "linked.pdf", 3, goto_links=[(0, 2)])
    doc = pymupdf.open(tmp_path / "linked.pdf")
    doc[1].insert_link({"kind": pymupdf.LINK_URI, "uri": "https://example.org/",
                        "from": pymupdf.Rect(72, 300, 300, 320)})
    doc.saveIncr()
    doc.close()
    config = project("""
        document: {title: Links}
        sections:
          - title: S
            documents: [linked.pdf]
        """)
    result = build(config)
    start = result.plan.parts[-1].start
    assert internal_links(result.output, start) == [start + 2]
    with pymupdf.open(result.output) as out:
        uris = [l["uri"] for l in out[start + 1].get_links() if l["kind"] == pymupdf.LINK_URI]
    assert uris == ["https://example.org/"]


def test_subsections_and_source_bookmarks(tmp_path, project):
    make_pdf(tmp_path / "guide.pdf", 4, toc=[[1, "Intro", 1], [1, "Details", 3], [2, "Deep", 4]])
    config = project("""
        document:
          title: Nesting
          toc: {max_depth: 3}
        sections:
          - title: S
            documents:
              - file: guide.pdf
                title: Guide
                source_bookmarks: true
                subsections:
                  - {title: Appendix, page: 4}
        """)
    result = build(config)
    start = result.plan.parts[-1].start + 1  # 1-based
    assert bookmarks(result.output) == [
        [1, "S", 3], [2, "Guide", start],
        [3, "Appendix", start + 3],
        [3, "Intro", start], [3, "Details", start + 2], [4, "Deep", start + 3],
    ]
    toc_text = page_texts(result.output)[1]
    assert "Appendix" in toc_text and "Intro" not in toc_text


def test_repeat_builds_are_byte_identical(tmp_path, project):
    config = three_section_project(tmp_path, project)
    first = build(config).output.read_bytes()
    second = build(config).output.read_bytes()
    assert first == second


def test_changed_source_is_picked_up(tmp_path, project):
    config = three_section_project(tmp_path, project)
    before = build(config)
    assert before.plan.total_pages == 12
    make_pdf(tmp_path / "docs/b.pdf", ["replaced-1", "replaced-2", "replaced-3"])
    after = build(config)
    assert after.plan.total_pages == 14
    texts = page_texts(after.output)
    assert "replaced-1" in texts[6]
    assert bookmarks(after.output)[4] == [2, "Doc C", 10]


def test_sources_are_not_modified(tmp_path, project):
    config = three_section_project(tmp_path, project,
                                   page_numbering={"source_documents": True})
    sources = sorted((tmp_path / "docs").glob("*.pdf"))
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in sources}
    build(config)
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in sources} == before


def test_metadata_and_no_timestamp_by_default(tmp_path, project):
    config = three_section_project(tmp_path, project)
    result = build(config)
    with pikepdf.open(result.output) as pdf:
        assert str(pdf.docinfo["/Title"]) == "Test Dossier"
        assert "/CreationDate" not in pdf.docinfo and "/ModDate" not in pdf.docinfo
        assert str(pdf.Root.Lang) == "en"
        meta = pdf.open_metadata()
        assert "xmp:ModifyDate" not in meta and "xmp:CreateDate" not in meta


def test_forms_survive_merge(tmp_path, project):
    path = tmp_path / "form.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    widget = pymupdf.Widget()
    widget.field_name = "applicant_name"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.rect = pymupdf.Rect(72, 72, 300, 92)
    widget.field_value = "Alex"
    page.add_widget(widget)
    doc.save(path)
    config = project("""
        document: {title: Forms}
        sections:
          - title: S
            documents: [form.pdf]
        """)
    result = build(config)
    with pymupdf.open(result.output) as out:
        widgets = [w for p in out for w in p.widgets()]
    assert [(w.field_name, w.field_value) for w in widgets] == [("applicant_name", "Alex")]
