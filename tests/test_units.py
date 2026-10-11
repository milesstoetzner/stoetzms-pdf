"""Unit tests for numbering and the TOC fixed-point loop."""

from __future__ import annotations

import io

import pikepdf
import pytest

from stoetzms_pdf.config import PageNumberingConfig, parse_length
from stoetzms_pdf.errors import BuildError, Diagnostics
from stoetzms_pdf.layout import Part, Plan, resolve_toc
from stoetzms_pdf.numbering import plan_labels, stamp_text, to_roman
from stoetzms_pdf.render import RenderedPdf


def test_roman_numerals():
    assert [to_roman(n) for n in (1, 4, 9, 14, 40, 90, 400, 1994)] == [
        "i", "iv", "ix", "xiv", "xl", "xc", "cd", "mcmxciv"]


def test_labels_whole_document():
    labels = plan_labels(PageNumberingConfig(start_at=3), total_pages=4, front_matter_pages=2)
    assert labels.labels() == ["3", "4", "5", "6"]
    assert labels.main_total() == "6"


def test_labels_front_matter():
    config = PageNumberingConfig(count_from="content", front_matter_style="upper-roman",
                                 style="arabic", format="{page}/{total}")
    labels = plan_labels(config, total_pages=5, front_matter_pages=2)
    assert labels.labels() == ["I", "II", "1", "2", "3"]
    assert stamp_text(config, labels, 3) == "2/3"
    nums = labels.pdf_page_labels().Nums
    assert int(nums[0]) == 0 and nums[1].S == pikepdf.Name.R
    assert int(nums[2]) == 2 and nums[3].S == pikepdf.Name.D


def test_parse_length():
    assert parse_length("72pt") == 72
    assert parse_length("1in") == 72
    assert round(parse_length("25.4mm"), 6) == 72
    assert parse_length("12") is None and parse_length("1em") is None


def _blank_pdf(pages: int) -> bytes:
    pdf = pikepdf.new()
    for _ in range(pages):
        pdf.add_blank_page()
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


class FakeRenderer:
    """Renders a TOC whose length depends on the page count it was laid out for."""

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = []
        self.plan: Plan | None = None

    def render_toc(self, entries):
        laid_out_for = self.plan.toc_part.page_count
        pages = self.behaviour(laid_out_for)
        self.calls.append((laid_out_for, pages))
        return RenderedPdf(_blank_pdf(pages), pages)


class FakeProject:
    class document:
        page_numbering = PageNumberingConfig()

        class toc:
            include_document_entries = True
            max_depth = 2


def _plan(renderer: FakeRenderer) -> Plan:
    toc = Part("toc", "TOC", 1)
    plan = Plan([Part("cover", "Cover", 1, b""), toc, Part("document", "D", 10, b"")], [], toc)
    renderer.plan = plan
    return plan


def test_toc_converges_when_it_grows():
    renderer = FakeRenderer(lambda laid_out_for: 3)
    plan = _plan(renderer)
    labels = resolve_toc(FakeProject, plan, renderer, Diagnostics())
    assert renderer.calls == [(1, 3), (3, 3)]
    assert plan.parts[2].start == 4 and labels.total_pages == 14


def test_toc_oscillation_is_padded_not_wrong():
    # Laid out for 2 pages it fits on 1; laid out for 1 it needs 2.
    renderer = FakeRenderer(lambda laid_out_for: 2 if laid_out_for == 1 else 1)
    plan = _plan(renderer)
    diag = Diagnostics()
    resolve_toc(FakeProject, plan, renderer, diag)
    assert plan.toc_part.page_count == 2
    with pikepdf.open(io.BytesIO(plan.toc_part.data)) as pdf:
        assert len(pdf.pages) == 2
    assert any("padded" in str(w) for w in diag.warnings)


def test_toc_that_never_settles_fails():
    renderer = FakeRenderer(lambda laid_out_for: laid_out_for + 1)
    with pytest.raises(BuildError) as exc:
        resolve_toc(FakeProject, _plan(renderer), renderer, Diagnostics())
    assert "did not settle" in str(exc.value)
