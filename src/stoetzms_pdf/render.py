"""HTML/CSS rendering of generated pages with Jinja2 and WeasyPrint.

Templates are looked up in the project's template directory first, then in
the built-in ``templates`` package directory, so a project can replace any
single file. Rendering is offline: only ``file:`` and ``data:`` URLs load,
and a resource that fails to load stops the build instead of disappearing
from the page.
"""

from __future__ import annotations

import html
import io
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jinja2
import pikepdf
import weasyprint
from weasyprint.text.fonts import FontConfiguration
from weasyprint.urls import FatalURLFetchingError, URLFetcher, URLFetcherResponse

from .config import Project, ResolvedSection, parse_length
from .errors import BuildError, Diagnostics, Location
from .sources import ImageSet

LINK_SCHEME = "stoetzms-pdf:"

# Built-in templates; a plain directory so it also works in the bundled binary.
TEMPLATES = Path(__file__).parent / "templates"

_LEADERS = {"dotted": "leader(dotted)", "solid": "leader(solid)",
            "space": "leader(space)", "none": "leader(space)"}

# Image pages: space between grid cells, and room reserved for the heading
# and for captions (in points).
_MM = 72 / 25.4
IMAGE_GAP = 6 * _MM
IMAGE_HEADING = 14 * _MM
IMAGE_CAPTION = 11 * _MM  # 2mm space, then two lines of 9pt
_MIN_IMAGE_CELL = 15 * _MM
_PX = 0.75  # points per CSS pixel; images are never enlarged beyond 96 dpi

_MIME_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "MPO": "image/jpeg",
               "GIF": "image/gif", "WEBP": "image/webp", "TIFF": "image/tiff",
               "BMP": "image/bmp"}

_MARGIN_BOXES = {
    "bottom-left": "bottom-left", "bottom-center": "bottom-center",
    "bottom-right": "bottom-right", "top-left": "top-left",
    "top-center": "top-center", "top-right": "top-right",
}


class _LocalOnlyFetcher(URLFetcher):
    """Load local files and data URLs; refuse anything that needs a network."""

    def __init__(self) -> None:
        super().__init__(allowed_protocols={"file", "data"}, fail_on_errors=True)
        # file: URL -> (bytes, MIME type) read during inspection; served
        # instead of the file so a change mid-build cannot reach the output.
        self.snapshots: dict[str, tuple[bytes, str]] = {}

    def fetch(self, url: str, headers: Any = None):
        scheme = url.split(":", 1)[0].lower()
        if scheme not in ("file", "data"):
            raise FatalURLFetchingError(
                f"{url} is not a local file; generated pages may only use local "
                "assets (the build runs offline)")
        if url in self.snapshots:
            data, mime = self.snapshots[url]
            return URLFetcherResponse(url, data, {"Content-Type": mime})
        try:
            return super().fetch(url, headers)
        except FileNotFoundError:
            raise FatalURLFetchingError(f"file not found: {url}") from None
        except OSError as exc:
            raise FatalURLFetchingError(f"cannot read {url}: {exc}") from None


def installed_font_count() -> int:
    """Fonts fontconfig can see, as WeasyPrint will when it lays out text."""
    from weasyprint.text.ffi import ffi, fontconfig

    config = fontconfig.FcInitLoadConfigAndFonts()
    try:
        fonts = fontconfig.FcConfigGetFonts(config, 0)  # FcSetSystem
        return 0 if fonts == ffi.NULL else fonts.nfont
    finally:
        fontconfig.FcConfigDestroy(config)


class _WarningCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@dataclass
class RenderedPdf:
    data: bytes
    page_count: int


@dataclass
class PageArea:
    """Where content goes on a generated page, in points from the top left."""

    left: float
    top: float
    width: float
    height: float


class Renderer:
    def __init__(self, project: Project, diag: Diagnostics):
        self.project = project
        self.diag = diag
        loaders: list[jinja2.BaseLoader] = []
        if project.template_dir:
            loaders.append(jinja2.FileSystemLoader(str(project.template_dir)))
        loaders.append(jinja2.FileSystemLoader(str(TEMPLATES)))
        self.env = jinja2.Environment(
            loader=jinja2.ChoiceLoader(loaders),
            autoescape=jinja2.select_autoescape(["html", "htm", "xml"]),
            undefined=jinja2.StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        if installed_font_count() == 0:
            # Pango crashes the process when it has no font at all to fall back to.
            raise BuildError("no fonts are installed on this system; generated pages need "
                             "at least one (on Debian or Ubuntu: apt install fonts-dejavu-core)")
        self.font_config = FontConfiguration()
        self.fetcher = _LocalOnlyFetcher()
        self.base_url = project.root.as_uri() + "/"
        self._stylesheets: list[weasyprint.CSS] | None = None
        self._page_areas: dict[str | None, PageArea] = {}

    # -- template plumbing ----------------------------------------------------

    def _template(self, name: str, location: Location | None = None) -> jinja2.Template:
        try:
            template = self.env.get_template(name)
        except jinja2.TemplateNotFound as exc:
            where = f" in {self.project.template_dir} or the built-in templates" \
                if self.project.template_dir else ""
            raise BuildError(f"template not found: {exc.name}{where}") from None
        except jinja2.TemplateSyntaxError as exc:
            raise BuildError(f"template {exc.filename or name}:{exc.lineno}: {exc.message}") from None
        return template

    def _render_template(self, name: str, context: dict[str, Any]) -> str:
        template = self._template(name)
        try:
            return template.render(**self._common_context(), **context)
        except jinja2.UndefinedError as exc:
            raise BuildError(f"template {name}: {exc.message}") from None
        except jinja2.TemplateError as exc:
            raise BuildError(f"template {name}: {exc}") from None

    def _common_context(self) -> dict[str, Any]:
        doc = self.project.document
        return {
            "document": doc,
            "style": doc.style,
            "labels": self.project.labels,
            "sections": [self._section_summary(s) for s in self.project.sections],
        }

    @staticmethod
    def _section_summary(section: ResolvedSection) -> dict[str, Any]:
        return {
            "number": section.number,
            "title": section.title,
            "documents": [{"title": d.title} for d in section.documents],
        }

    def stylesheets(self) -> list[weasyprint.CSS]:
        if self._stylesheets is None:
            style = self.project.document.style
            css = self._render_template("default.css", {
                "heading_font_family": style.heading_font_family or style.font_family,
                "toc": self.project.document.toc,
                "toc_leader": _LEADERS[self.project.document.toc.leader],
            })
            sheets = [self._css("default.css", string=css, base_url=self.base_url)]
            for path in self.project.stylesheets:
                sheets.append(self._css(self.project.display_path(path), filename=str(path)))
            self._stylesheets = sheets
        return self._stylesheets

    def _css(self, what: str, **kwargs: Any) -> weasyprint.CSS:
        try:
            return weasyprint.CSS(url_fetcher=self.fetcher, font_config=self.font_config,
                                  **kwargs)
        except FatalURLFetchingError as exc:
            raise BuildError(f"stylesheet {what}: {exc}") from None
        except Exception as exc:
            raise BuildError(f"stylesheet {what}: {exc}") from exc

    def _write_pdf(self, html_text: str, what: str,
                   stylesheets: list[weasyprint.CSS] | None = None) -> RenderedPdf:
        data = self._weasyprint(html_text, what, stylesheets, lambda doc: doc.write_pdf())
        with pikepdf.open(io.BytesIO(data)) as pdf:
            page_count = len(pdf.pages)
        if page_count == 0:
            raise BuildError(f"{what}: the template produced no pages")
        return RenderedPdf(data, page_count)

    def _weasyprint(self, html_text: str, what: str,
                    stylesheets: list[weasyprint.CSS] | None, use: Any) -> Any:
        """Lay out ``html_text`` and pass the document to ``use``."""
        if stylesheets is None:
            stylesheets = self.stylesheets()
        collector = _WarningCollector()
        logger = logging.getLogger("weasyprint")
        logger.addHandler(collector)
        try:
            document = weasyprint.HTML(string=html_text, base_url=self.base_url,
                                       url_fetcher=self.fetcher)
            result = use(document.render(stylesheets=stylesheets, font_config=self.font_config))
        except FatalURLFetchingError as exc:
            raise BuildError(f"{what}: {exc}") from None
        except Exception as exc:  # WeasyPrint raises a wide range of errors
            raise BuildError(f"{what}: rendering failed: {exc}") from exc
        finally:
            logger.removeHandler(collector)
        for message in collector.messages:
            self.diag.warning(f"{what}: {message}")
        return result

    # -- pages -------------------------------------------------------------------

    def render_cover(self) -> RenderedPdf:
        doc = self.project.document
        cover = doc.cover
        context = {
            "cover": {
                "title": cover.title or doc.title,
                "subtitle": cover.subtitle if cover.subtitle is not None else doc.subtitle,
                "author": cover.author if cover.author is not None else doc.author,
                "date": self.project.cover_date,
                "logo": self.project.cover_logo.as_uri() if self.project.cover_logo else None,
                "details": cover.details,
                "accent_bar": cover.accent_bar,
            }
        }
        return self._write_pdf(self._render_template(cover.template, context), "cover")

    def render_divider(self, section: ResolvedSection) -> RenderedPdf:
        divider = section.divider
        assert divider is not None
        context = {
            "section": self._section_summary(section),
            "divider": {
                "title": divider.title,
                "subtitle": divider.subtitle,
                "description": divider.description,
                "logo": divider.logo.as_uri() if divider.logo else None,
                "number": section.number if divider.show_number else None,
                "label": divider.label,
                "list_documents": divider.list_documents,
                "documents": [{"title": d.title} for d in section.documents],
            },
        }
        return self._write_pdf(self._render_template(divider.template, context),
                               f"divider for section {section.title!r}")

    def render_toc(self, entries: list[dict[str, Any]]) -> RenderedPdf:
        toc = self.project.document.toc
        context = {
            "toc": {
                "title": toc.title or self.project.labels["toc_title"],
                "include_page_numbers": toc.include_page_numbers,
                "links": toc.links,
                "max_depth": toc.max_depth,
            },
            "entries": entries,
        }
        return self._write_pdf(self._render_template(toc.template, context),
                               "table of contents")

    def render_page_numbers(self, pages: list[tuple[float, float, str]]) -> RenderedPdf:
        """One page per entry (display width, display height, text)."""
        pn = self.project.document.page_numbering
        style = self.project.document.style
        offset = parse_length(pn.margin) or 34.0
        sizes: dict[tuple[float, float], str] = {}
        for width, height, _ in pages:
            key = (round(width, 3), round(height, 3))
            sizes.setdefault(key, f"size{len(sizes)}")
        css = self._render_template("page-number.css", {
            "page_numbering": pn,
            "font_family": pn.font_family or style.font_family,
            "color": pn.color or style.muted_color,
            "vertical_margin": round(offset * 2, 3),
            "horizontal_margin": round(offset, 3),
            "margin_box": _MARGIN_BOXES[pn.position],
            "sizes": [{"name": name, "width": w, "height": h} for (w, h), name in sizes.items()],
        })
        body = "\n".join(
            f'<div class="stamp" style="page: {sizes[(round(w, 3), round(h, 3))]}" '
            f'data-text="{html.escape(text, quote=True)}"></div>'
            for w, h, text in pages
        )
        document = (f'<!DOCTYPE html><html lang="{html.escape(self.project.document.language)}">'
                    f"<head><meta charset=\"utf-8\"></head><body>{body}</body></html>")
        sheet = self._css("page-number.css", string=css, base_url=self.base_url)
        rendered = self._write_pdf(document, "page numbers", stylesheets=[sheet])
        if rendered.page_count != len(pages):
            raise BuildError(f"page numbers: expected {len(pages)} page(s) from page-number.css, "
                             f"got {rendered.page_count}")
        return rendered

    # -- image documents ---------------------------------------------------------

    def page_area(self, page_size: str | None, what: str) -> PageArea:
        """The content box of an image page, measured with the real stylesheets.

        Margins can come from document.style or any user stylesheet, so they
        are measured rather than parsed: a probe page reports where its
        content box starts and ends.
        """
        if page_size not in self._page_areas:
            probe = (f'<!DOCTYPE html><html><head>{_image_page_style(page_size)}</head>'
                     '<body style="margin: 0"><div style="page: image-page">'
                     '<div id="pa-start"></div>'
                     '<div id="pa-end" style="position: absolute; right: 0; bottom: 0; '
                     'width: 0; height: 0"></div></div></body></html>')

            def measure(document):
                anchors = document.pages[0].anchors
                return anchors["pa-start"], anchors["pa-end"]

            start, end = self._weasyprint(probe, what, None, measure)
            self._page_areas[page_size] = PageArea(
                left=start[0] * _PX, top=start[1] * _PX,
                width=(end[0] - start[0]) * _PX, height=(end[1] - start[1]) * _PX)
        return self._page_areas[page_size]

    def render_images(self, image_set: ImageSet) -> RenderedPdf:
        document = image_set.document
        entry = document.entry
        what = f"images of {document.title!r}"
        area = self.page_area(entry.page_size, what)
        layout = image_grid(area, entry.per_page, entry.columns, entry.show_title,
                            any(image.title for image in image_set.images))
        if layout.cell_width < _MIN_IMAGE_CELL or layout.image_height < _MIN_IMAGE_CELL:
            raise BuildError(f"{what}: {entry.per_page} images per page in "
                             f"{layout.columns} column(s) leave too little room for each "
                             "image; use fewer per page or a larger page_size")

        pages = []
        for first in range(0, len(image_set.images), entry.per_page):
            cells = []
            for index, image in enumerate(image_set.images[first:first + entry.per_page]):
                uri = image.path.as_uri()
                self.fetcher.snapshots[uri] = (image.data, _MIME_TYPES[image.format])
                left, top = layout.cell_origin(index)
                width, height = layout.fit(image.width, image.height)
                cells.append({
                    "src": uri,
                    "title": image.title,
                    "left": round(left, 3),
                    "top": round(top, 3),
                    "cell_width": round(layout.cell_width, 3),
                    "width": round(width, 3),
                    "height": round(height, 3),
                })
            pages.append(cells)

        context = {
            "images": {
                "title": document.title,
                "show_title": entry.show_title,
                "page_style": _image_page_style(entry.page_size),
                "area_height": round(area.height - 1, 3),  # 1pt slack against rounding
                "heading_height": round(layout.heading, 3),
                "caption_height": round(max(layout.caption - 2 * _MM, 0), 3),
                "pages": pages,
            }
        }
        rendered = self._write_pdf(self._render_template("images.html", context), what)
        if rendered.page_count != len(pages):
            raise BuildError(f"{what}: expected {len(pages)} page(s), the template produced "
                             f"{rendered.page_count}; a custom images.html or stylesheet "
                             "must keep each page's images on one page")
        return rendered


def _image_page_style(page_size: str | None) -> str:
    if page_size is None:
        return ""
    return f"<style>@page image-page {{ size: {html.escape(page_size)} }}</style>"


@dataclass
class ImageGrid:
    """Cells of an image page, relative to the top left of its content box."""

    columns: int
    rows: int
    cell_width: float
    cell_height: float
    heading: float
    caption: float

    @property
    def image_height(self) -> float:
        return self.cell_height - self.caption

    def cell_origin(self, index: int) -> tuple[float, float]:
        row, column = divmod(index, self.columns)
        return (column * (self.cell_width + IMAGE_GAP),
                self.heading + row * (self.cell_height + IMAGE_GAP))

    def fit(self, width: int, height: int) -> tuple[float, float]:
        """Scale an image to fit its cell, keeping its proportions."""
        scale = min(self.cell_width / width, self.image_height / height, _PX)
        return width * scale, height * scale


def image_grid(area: PageArea, per_page: int, columns: int | None, heading: bool,
               captions: bool) -> ImageGrid:
    if columns is None:
        # Fill portrait pages top to bottom first, landscape pages left to right.
        short_side = max(1, math.isqrt(per_page))
        columns = short_side if area.height >= area.width else math.ceil(per_page / short_side)
    rows = math.ceil(per_page / columns)
    heading_height = IMAGE_HEADING if heading else 0.0
    return ImageGrid(
        columns=columns,
        rows=rows,
        cell_width=(area.width - IMAGE_GAP * (columns - 1)) / columns,
        cell_height=(area.height - heading_height - IMAGE_GAP * (rows - 1)) / rows,
        heading=heading_height,
        caption=IMAGE_CAPTION if captions else 0.0,
    )
