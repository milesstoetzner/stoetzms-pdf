"""Pass 1: read and check every source PDF and image.

Each file is read into memory once. Its page count and page geometry come
from that snapshot, and the same bytes are used later for assembly, so
a file changing mid-build cannot produce a mismatched output.
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf
from PIL import Image, ImageFile, UnidentifiedImageError

from .config import Project, ResolvedDocument, ResolvedImage, Subsection
from .errors import Diagnostics, Location


@dataclass
class PageGeometry:
    width: float  # visible (crop box) size as displayed, after /Rotate
    height: float
    rotate: int

    @property
    def orientation(self) -> str:
        return "landscape" if self.width > self.height else "portrait"


@dataclass
class OutlineNode:
    title: str
    page: int  # 0-based within the source
    children: list[OutlineNode] = field(default_factory=list)


@dataclass
class SourceImage:
    path: Path
    title: str | None
    data: bytes
    width: int  # pixels, as displayed (after the EXIF orientation)
    height: int
    format: str


@dataclass
class ImageSet:
    """An image document before its pages are rendered."""

    document: ResolvedDocument
    images: list[SourceImage]

    @property
    def page_count(self) -> int:
        return self.document.image_page_count

    def to_source(self, data: bytes) -> SourcePdf:
        """The rendered pages, as a source like any PDF."""
        with pikepdf.open(io.BytesIO(data)) as pdf:
            pages = [page_geometry(page) for page in pdf.pages]
        return SourcePdf(self.document, data, len(pages), pages, None, images=self.images)


@dataclass
class SourcePdf:
    document: ResolvedDocument
    data: bytes
    page_count: int
    pages: list[PageGeometry]
    password: str | None
    signed: bool = False
    outline: list[OutlineNode] = field(default_factory=list)
    images: list[SourceImage] = field(default_factory=list)  # for image documents

    def open(self) -> pikepdf.Pdf:
        return pikepdf.open(io.BytesIO(self.data), password=self.password or "")


def page_geometry(page: pikepdf.Page) -> PageGeometry:
    box = page.cropbox
    x0, y0, x1, y1 = (float(v) for v in box)
    width, height = abs(x1 - x0), abs(y1 - y0)
    rotate = int(page.obj.get("/Rotate", 0)) % 360
    if rotate in (90, 270):
        width, height = height, width
    return PageGeometry(width, height, rotate)


def inspect_sources(project: Project, diag: Diagnostics) -> dict[int, SourcePdf | ImageSet]:
    """Inspect every included document, keyed by ``id(ResolvedDocument)``."""
    sources: dict[int, SourcePdf | ImageSet] = {}
    for section in project.sections:
        for document in section.documents:
            if document.images:
                source = inspect_images(project, document, diag)
            else:
                source = inspect_source(project, document, diag)
            if source is not None:
                sources[id(document)] = source
    return sources


def _read(path: Path, shown: str, loc: Location | None, diag: Diagnostics) -> bytes | None:
    if not path.exists():
        diag.error(f"source file not found: {shown}", loc)
        return None
    if not path.is_file():
        diag.error(f"source path is not a file: {shown}", loc)
        return None
    try:
        return path.read_bytes()
    except OSError as exc:
        diag.error(f"cannot read {shown}: {exc.strerror or exc}", loc)
        return None


# Formats WeasyPrint embeds (through Pillow). MPO is the JPEG variant many
# cameras write.
IMAGE_FORMATS = {"PNG", "JPEG", "MPO", "GIF", "WEBP", "TIFF", "BMP"}
_EXIF_ORIENTATION = 0x0112


def inspect_images(project: Project, document: ResolvedDocument,
                   diag: Diagnostics) -> ImageSet | None:
    images = [inspect_image(project, image, diag) for image in document.images]
    if any(image is None for image in images):
        return None
    return ImageSet(document, images)


def inspect_image(project: Project, image: ResolvedImage,
                  diag: Diagnostics) -> SourceImage | None:
    path, loc = image.path, image.location
    shown = project.display_path(path)
    data = _read(path, shown, loc, diag)
    if data is None:
        return None
    # WeasyPrint makes Pillow accept truncated images; a damaged file must
    # fail here instead of showing up half grey in the output.
    lenient, ImageFile.LOAD_TRUNCATED_IMAGES = ImageFile.LOAD_TRUNCATED_IMAGES, False
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format or "unknown"
            if fmt not in IMAGE_FORMATS:
                diag.error(f"{shown}: {fmt} images are not supported; use PNG, JPEG, GIF, "
                           "WebP, TIFF or BMP", loc)
                return None
            img.load()  # decode fully so a truncated file fails now
            width, height = img.size
            if img.getexif().get(_EXIF_ORIENTATION, 1) in (5, 6, 7, 8):
                width, height = height, width
            if getattr(img, "n_frames", 1) > 1 and fmt != "MPO":
                diag.warning(f"{shown} has {img.n_frames} frames; only the first is shown", loc)
    except Image.DecompressionBombError:
        diag.error(f"{shown} is too large to embed (more than "
                   f"{Image.MAX_IMAGE_PIXELS * 2:,} pixels)", loc)
        return None
    except UnidentifiedImageError:
        if b"%PDF-" in data[:1024]:
            diag.error(f"{shown} is a PDF; images and PDFs are separate documents", loc)
        else:
            diag.error(f"{shown} is not an image file (supported: PNG, JPEG, GIF, WebP, TIFF, "
                       "BMP)", loc)
        return None
    except (OSError, SyntaxError, ValueError) as exc:
        diag.error(f"{shown} is damaged and cannot be read: {exc}", loc)
        return None
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = lenient
    return SourceImage(path, image.title, data, width, height, fmt)


def inspect_source(project: Project, document: ResolvedDocument,
                   diag: Diagnostics) -> SourcePdf | None:
    path, loc = document.path, document.location
    shown = project.display_path(path)
    entry = document.entry

    data = _read(path, shown, loc, diag)
    if data is None:
        return None
    if b"%PDF-" not in data[:1024]:
        diag.error(f"{shown} is not a PDF file (no %PDF header)", loc)
        return None

    password = None
    if entry.password_env:
        password = os.environ.get(entry.password_env)
        if password is None:
            diag.error(f"environment variable {entry.password_env} (password for {shown}) "
                       "is not set", loc)
            return None

    try:
        pdf = pikepdf.open(io.BytesIO(data), password=password or "")
    except pikepdf.PasswordError:
        if password is None:
            diag.error(f"{shown} is password-protected; set password_env to the name of an "
                       "environment variable holding its password", loc)
        else:
            diag.error(f"the password in {entry.password_env} does not open {shown}", loc)
        return None
    except pikepdf.PdfError as exc:
        diag.error(f"{shown} is not a valid PDF: {_clean(exc)}", loc)
        return None

    with pdf:
        if pdf.is_encrypted and password is None and not entry.allow_restricted:
            diag.error(f"{shown} is encrypted with usage restrictions (owner password). "
                       "Restrictions are not carried into the output; set allow_restricted: true "
                       "if you are entitled to assemble it, or decrypt a copy first", loc)
            return None
        if pdf.is_encrypted:
            diag.warning(f"{shown} is encrypted; the assembled output is not", loc)

        try:
            page_count = len(pdf.pages)
            pages = [page_geometry(page) for page in pdf.pages]
            # Touch every content stream so damage surfaces now, not mid-build.
            for page in pdf.pages:
                for stream in _content_streams(page):
                    stream.read_bytes()
        except (pikepdf.PdfError, ValueError, TypeError, KeyError) as exc:
            diag.error(f"{shown} is damaged and cannot be read: {_clean(exc)}", loc)
            return None

        if page_count == 0:
            diag.error(f"{shown} has no pages", loc)
            return None

        repairs = [w for w in pdf.get_warnings() if w]
        if repairs:
            detail = "; ".join(_clean(w) for w in repairs[:3])
            more = f" (+{len(repairs) - 3} more)" if len(repairs) > 3 else ""
            diag.warning(f"{shown} is damaged and was repaired while reading: {detail}{more}. "
                         "Check its pages in the output", loc)

        for page in pages:
            if page.rotate % 90:
                diag.error(f"{shown} has an invalid page rotation ({page.rotate})", loc)
                return None
        if any("/UserUnit" in page.obj for page in pdf.pages):
            diag.warning(f"{shown} uses /UserUnit page scaling; page numbers may be misplaced",
                         loc)

        signed = _has_signature(pdf)
        if signed:
            diag.warning(
                f"{shown} is digitally signed. Merging it into another PDF invalidates the "
                "signature for the assembled document; the output must not be presented as "
                "carrying a valid signature. Submit the original file where a valid signature "
                "is required", loc)
        if "/OCProperties" in pdf.Root:
            diag.warning(f"{shown} uses optional content (layers); layer visibility settings "
                         "are not carried over and all layers may be shown", loc)

        outline: list[OutlineNode] = []
        if document.source_bookmarks:
            outline = _read_outline(pdf, shown, loc, diag)

    for sub in _flatten(document.entry.subsections):
        if sub.page > page_count:
            diag.error(f"subsection {sub.title!r} points to page {sub.page}, but {shown} has "
                       f"{page_count} page(s)", getattr(sub, "_field_locs", {}).get("page", loc))

    return SourcePdf(
        document=document,
        data=data,
        page_count=page_count,
        pages=pages,
        password=password,
        signed=signed,
        outline=outline,
    )


def _clean(problem: object) -> str:
    """qpdf messages name the in-memory stream; drop that noise."""
    return re.sub(r"^(stream )?<_io\.BytesIO object at 0x[0-9a-f]+>:?\s*", "", str(problem))


def _content_streams(page: pikepdf.Page):
    contents = page.obj.get("/Contents")
    if contents is None:
        return []
    if isinstance(contents, pikepdf.Array):
        return [c for c in contents if isinstance(c, pikepdf.Stream)]
    return [contents] if isinstance(contents, pikepdf.Stream) else []


def _flatten(subsections: list[Subsection]):
    for sub in subsections:
        yield sub
        yield from _flatten(sub.subsections)


def _has_signature(pdf: pikepdf.Pdf) -> bool:
    if "/Perms" in pdf.Root:
        return True
    acroform = pdf.Root.get("/AcroForm")
    if acroform is None:
        return False
    if int(acroform.get("/SigFlags", 0)) & 1:
        return True

    stack = list(acroform.get("/Fields", []))
    seen = 0
    while stack and seen < 10000:
        seen += 1
        field_obj = stack.pop()
        if not isinstance(field_obj, pikepdf.Dictionary):
            continue
        if field_obj.get("/FT") == pikepdf.Name.Sig and "/V" in field_obj:
            return True
        stack.extend(field_obj.get("/Kids", []))
    return False


def _read_outline(pdf: pikepdf.Pdf, shown: str, loc: Location | None,
                  diag: Diagnostics) -> list[OutlineNode]:
    page_index = {page.obj.objgen: i for i, page in enumerate(pdf.pages)}
    named = _named_destinations(pdf)
    skipped = 0

    def target(item: pikepdf.OutlineItem) -> int | None:
        dest = item.destination
        if dest is None and item.action is not None and item.action.get("/S") == pikepdf.Name.GoTo:
            dest = item.action.get("/D")
        if isinstance(dest, (pikepdf.Name, pikepdf.String)):
            dest = named.get(str(dest))
        if isinstance(dest, pikepdf.Dictionary):
            dest = dest.get("/D")
        if isinstance(dest, pikepdf.Array) and len(dest) and isinstance(dest[0], pikepdf.Dictionary):
            return page_index.get(dest[0].objgen)
        if isinstance(dest, int):
            return dest
        return None

    def convert(items) -> list[OutlineNode]:
        nonlocal skipped
        nodes = []
        for item in items:
            children = convert(item.children)
            page = target(item)
            if page is None:
                skipped += 1
                nodes.extend(children)
                continue
            nodes.append(OutlineNode(item.title or "", page, children))
        return nodes

    try:
        with pdf.open_outline() as outline:
            nodes = convert(outline.root)
    except (pikepdf.OutlineStructureError, pikepdf.PdfError) as exc:
        diag.warning(f"cannot read the bookmarks of {shown}: {exc}", loc)
        return []
    if skipped:
        diag.warning(f"{skipped} bookmark(s) in {shown} do not point to a page and were left out",
                     loc)
    return nodes


def _named_destinations(pdf: pikepdf.Pdf) -> dict[str, pikepdf.Object]:
    named: dict[str, pikepdf.Object] = {}
    legacy = pdf.Root.get("/Dests")
    if isinstance(legacy, pikepdf.Dictionary):
        for key, value in legacy.items():
            named[key[1:]] = value
            named[key] = value
    names = pdf.Root.get("/Names")
    if isinstance(names, pikepdf.Dictionary) and "/Dests" in names:
        try:
            tree = pikepdf.NameTree(names.Dests)
            for key, value in tree.items():
                named[str(key)] = value
        except (pikepdf.PdfError, TypeError, ValueError):
            pass
    return named


def describe_pages(source: SourcePdf) -> str:
    sizes = {(round(p.width), round(p.height)) for p in source.pages}
    shape = ", ".join(f"{w}x{h}pt" for w, h in sorted(sizes))
    return f"{source.page_count} page(s), {shape}"
