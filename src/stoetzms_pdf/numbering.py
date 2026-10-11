"""Printed page numbers.

A page has a physical position (its index in the PDF) and a printed label.
Every page is counted, but only some kinds of pages get the label stamped
on them; the table of contents always shows labels, and PDF page labels make
viewers display the same values.
"""

from __future__ import annotations

from dataclasses import dataclass

import pikepdf

from .config import PageNumberingConfig

_ROMAN = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
          (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]

_PDF_STYLE = {"arabic": pikepdf.Name.D, "lower-roman": pikepdf.Name.r,
              "upper-roman": pikepdf.Name.R}


def to_roman(number: int) -> str:
    if number < 1:
        raise ValueError("roman numerals start at 1")
    out = []
    for value, letters in _ROMAN:
        count, number = divmod(number, value)
        out.append(letters * count)
    return "".join(out)


def format_number(number: int, style: str) -> str:
    if style == "lower-roman":
        return to_roman(number)
    if style == "upper-roman":
        return to_roman(number).upper()
    return str(number)


@dataclass(frozen=True)
class LabelRange:
    first_page: int  # physical, 0-based
    style: str
    start: int


@dataclass
class PageLabels:
    """Printed labels for every page of the assembled document."""

    ranges: list[LabelRange]
    total_pages: int

    def number(self, page: int) -> tuple[int, str]:
        current = self.ranges[0]
        for label_range in self.ranges:
            if label_range.first_page <= page:
                current = label_range
        return current.start + page - current.first_page, current.style

    def label(self, page: int) -> str:
        number, style = self.number(page)
        return format_number(number, style)

    def labels(self) -> list[str]:
        return [self.label(i) for i in range(self.total_pages)]

    def main_total(self) -> str:
        """The last number of the main sequence, for "{total}"."""
        return self.label(self.total_pages - 1)

    def pdf_page_labels(self) -> pikepdf.Dictionary:
        nums = []
        for label_range in self.ranges:
            entry = pikepdf.Dictionary(S=_PDF_STYLE[label_range.style])
            if label_range.start != 1:
                entry.St = label_range.start
            nums.extend([label_range.first_page, entry])
        return pikepdf.Dictionary(Nums=pikepdf.Array(nums))


def plan_labels(config: PageNumberingConfig, total_pages: int,
                front_matter_pages: int) -> PageLabels:
    if config.count_from == "content" and 0 < front_matter_pages < total_pages:
        ranges = [LabelRange(0, config.front_matter_style, 1),
                  LabelRange(front_matter_pages, config.style, config.start_at)]
    else:
        ranges = [LabelRange(0, config.style, config.start_at)]
    return PageLabels(ranges, total_pages)


def stamp_text(config: PageNumberingConfig, labels: PageLabels, page: int) -> str:
    return config.format.format(page=labels.label(page), total=labels.main_total())
