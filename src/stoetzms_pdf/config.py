"""Configuration schema, defaults and semantic validation.

The dataclasses below *are* the schema: every option a project file may use
is a field here, with its default. :func:`load_project` parses the YAML,
checks it and resolves all paths relative to the configuration file.
"""

from __future__ import annotations

import datetime
import math
import os
import re
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .errors import Diagnostics, Location, ValidationError
from .schema import SchemaParser, loc_of, was_given
from .yamlload import YamlLoadError, load_yaml

Align = Literal["left", "center", "right"]
NumberStyle = Literal["arabic", "lower-roman", "upper-roman"]
Position = Literal[
    "bottom-left", "bottom-center", "bottom-right", "top-left", "top-center", "top-right"
]

# File extensions read as images rather than PDFs.
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".bmp"}

# Default wording for generated pages, by language prefix.
LABELS: dict[str, dict[str, str]] = {
    "en": {"toc_title": "Table of Contents", "section": "Section", "contents": "Contents"},
    "de": {"toc_title": "Inhaltsverzeichnis", "section": "Abschnitt", "contents": "Inhalt"},
    "fr": {"toc_title": "Table des matières", "section": "Section", "contents": "Contenu"},
}


def _bool_shorthand(cls: type, value: Any) -> dict | None:
    return {"enabled": value} if isinstance(value, bool) else None


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------


@dataclass
class DetailItem:
    label: str
    value: str


@dataclass
class CoverConfig:
    enabled: bool = True
    title: str | None = None  # defaults to document.title
    subtitle: str | None = None  # defaults to document.subtitle
    author: str | None = None  # defaults to document.author
    date: datetime.date | str | None = None  # "today" uses the build date
    date_format: str | None = None  # strftime pattern, e.g. "%d %B %Y"
    logo: str | None = None
    details: list[DetailItem] = field(default_factory=list)
    accent_bar: bool = False  # short rule above the title
    template: str = "cover.html"

    from_shorthand = classmethod(_bool_shorthand)


@dataclass
class TocConfig:
    enabled: bool = True
    title: str | None = None  # defaults by document.language
    include_page_numbers: bool = True
    include_document_entries: bool = True
    max_depth: int = 2  # 1 = sections, 2 = + documents, 3 = + subsections
    indent: str = "1.6em"
    leader: Literal["dotted", "solid", "space", "none"] = "dotted"
    links: bool = True
    template: str = "toc.html"

    from_shorthand = classmethod(_bool_shorthand)


@dataclass
class BookmarksConfig:
    enabled: bool = True
    include_subsections: bool = True
    include_source_bookmarks: bool = False
    expand_sections: bool = True

    from_shorthand = classmethod(_bool_shorthand)


@dataclass
class PageNumberingConfig:
    enabled: bool = True
    position: Position = "bottom-center"
    start_at: int = 1
    style: NumberStyle = "arabic"
    # "document": physical page 1 carries number `start_at`.
    # "content":  cover and TOC form a separate front-matter sequence and the
    #             first section starts at `start_at`.
    count_from: Literal["document", "content"] = "document"
    front_matter_style: NumberStyle = "lower-roman"
    format: str = "{page}"  # placeholders: {page}, {total}
    # Which kinds of pages get a printed number (all pages are counted).
    cover: bool = False
    toc: bool = True
    dividers: bool = False
    source_documents: bool = False
    font_family: str | None = None  # defaults to style.font_family
    font_size: str = "9pt"
    color: str | None = None  # defaults to style.muted_color
    margin: str = "12mm"  # distance from the page edge to the number
    page_labels: bool = True  # make PDF viewers show the same numbers

    from_shorthand = classmethod(_bool_shorthand)


@dataclass
class DividerConfig:
    """Divider settings; at document level (``dividers``) they are defaults."""

    enabled: bool | None = None
    title: str | None = None  # section-level only; defaults to the section title
    subtitle: str | None = None  # section-level only
    description: str | None = None  # section-level only
    logo: str | None = None
    show_number: bool | None = None
    list_documents: bool | None = None
    label: str | None = None  # word before the number, e.g. "Section"
    template: str | None = None

    from_shorthand = classmethod(_bool_shorthand)


@dataclass
class StyleConfig:
    page_size: str = "A4"
    margin: str = "25mm"
    font_family: str = (
        '"Helvetica Neue", Helvetica, Arial, "Liberation Sans", "DejaVu Sans", sans-serif'
    )
    heading_font_family: str | None = None
    base_font_size: str = "10.5pt"
    text_color: str = "#000000"
    muted_color: str = "#000000"
    accent_color: str = "#000000"
    rule_color: str = "#000000"
    cover_align: Align = "left"
    divider_align: Align = "left"


@dataclass
class TemplatesConfig:
    directory: str | None = None  # searched before the built-in templates
    stylesheets: list[str] = field(default_factory=list)  # applied after default.css


@dataclass
class Subsection:
    title: str
    page: int  # 1-based page within the source document
    subsections: list[Subsection] = field(default_factory=list)


@dataclass
class ImageItem:
    file: str
    title: str | None = None  # caption under the image

    @classmethod
    def from_shorthand(cls, value: Any) -> dict | None:
        return {"file": value} if isinstance(value, str) else None


@dataclass
class DocumentEntry:
    file: str | None = None  # a PDF, or a single image
    images: list[ImageItem] = field(default_factory=list)  # instead of file
    title: str | None = None  # defaults to the file name
    enabled: bool = True
    subsections: list[Subsection] = field(default_factory=list)
    # PDF documents only
    source_bookmarks: bool | None = None  # defaults to bookmarks.include_source_bookmarks
    password_env: str | None = None  # environment variable holding the password
    allow_restricted: bool = False  # accept PDFs with owner-password restrictions
    # Image documents only
    per_page: int = 1
    columns: int | None = None  # defaults by per_page and page orientation
    show_title: bool = True  # print the title above the images
    page_size: str | None = None  # defaults to style.page_size

    @classmethod
    def from_shorthand(cls, value: Any) -> dict | None:
        return {"file": value} if isinstance(value, str) else None


@dataclass
class SectionConfig:
    title: str
    enabled: bool = True
    divider: DividerConfig = field(default_factory=DividerConfig)
    documents: list[DocumentEntry] = field(default_factory=list)


@dataclass
class DocumentConfig:
    title: str
    subtitle: str | None = None
    author: str | None = None
    subject: str | None = None
    keywords: list[str] = field(default_factory=list)
    language: str = "en"
    output: str | None = None  # defaults to output/<slugified title>.pdf
    number_sections: bool = False
    timestamp: bool = False  # embed the build time in the PDF metadata
    cover: CoverConfig = field(default_factory=CoverConfig)
    toc: TocConfig = field(default_factory=TocConfig)
    bookmarks: BookmarksConfig = field(default_factory=BookmarksConfig)
    page_numbering: PageNumberingConfig = field(default_factory=PageNumberingConfig)
    dividers: DividerConfig = field(default_factory=DividerConfig)
    style: StyleConfig = field(default_factory=StyleConfig)
    templates: TemplatesConfig = field(default_factory=TemplatesConfig)


@dataclass
class ProjectConfig:
    document: DocumentConfig
    sections: list[SectionConfig]
    version: int = 1


# --------------------------------------------------------------------------
# Resolved model
# --------------------------------------------------------------------------


@dataclass
class ResolvedDivider:
    title: str
    subtitle: str | None
    description: str | None
    logo: Path | None
    show_number: bool
    list_documents: bool
    label: str
    template: str


@dataclass
class ResolvedImage:
    path: Path
    title: str | None
    location: Location | None


@dataclass
class ResolvedDocument:
    path: Path | None  # the source PDF; None for image documents
    title: str
    entry: DocumentEntry
    source_bookmarks: bool
    location: Location | None
    images: list[ResolvedImage] = field(default_factory=list)
    shown: str = ""  # source file(s) as named in messages

    @property
    def files(self) -> list[Path]:
        return [image.path for image in self.images] if self.images else [self.path]

    @property
    def image_page_count(self) -> int:
        return math.ceil(len(self.images) / self.entry.per_page)


@dataclass
class ResolvedSection:
    number: int  # 1-based among included sections
    title: str
    divider: ResolvedDivider | None
    documents: list[ResolvedDocument]
    location: Location | None


@dataclass
class Project:
    config_path: Path
    root: Path
    config: ProjectConfig
    output: Path
    sections: list[ResolvedSection]
    labels: dict[str, str]
    cover_date: str | None
    cover_logo: Path | None
    template_dir: Path | None
    stylesheets: list[Path]
    diagnostics: Diagnostics

    @property
    def document(self) -> DocumentConfig:
        return self.config.document

    def display_path(self, path: Path) -> str:
        """A path relative to the project root when possible, for messages."""
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return str(path)


# --------------------------------------------------------------------------
# Loading and validation
# --------------------------------------------------------------------------

_LENGTH_RE = re.compile(r"^\s*(\d+(?:\.\d+)?|\.\d+)\s*(mm|cm|in|pt|px|pc)\s*$")
_LENGTH_FACTORS = {"pt": 1.0, "mm": 72 / 25.4, "cm": 72 / 2.54, "in": 72.0, "px": 0.75, "pc": 12.0}


def parse_length(text: str) -> float | None:
    """Convert a CSS absolute length ("12mm", "0.5in", "10pt") to points."""
    match = _LENGTH_RE.match(text)
    if not match:
        return None
    return float(match.group(1)) * _LENGTH_FACTORS[match.group(2)]


def slugify(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return slug or "document"


def title_from_filename(path: Path) -> str:
    words = re.sub(r"[_\-]+", " ", path.stem).strip()
    return words[:1].upper() + words[1:] if words else path.name


def _resolve(root: Path, value: str) -> Path:
    path = Path(os.path.expanduser(value))
    if not path.is_absolute():
        path = root / path
    return Path(os.path.abspath(path))


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.exists() and b.exists() and os.path.samefile(a, b)
    except OSError:
        return False


def _check_format(fmt: str, diag: Diagnostics, loc: Location | None) -> None:
    try:
        names = [name for _, name, _, _ in string.Formatter().parse(fmt) if name is not None]
    except ValueError as exc:
        diag.error(f"invalid format string: {exc}", loc)
        return
    for name in names:
        if name not in ("page", "total"):
            diag.error(f"unknown placeholder {{{name}}}; use {{page}} and {{total}}", loc)
    if "page" not in names:
        diag.warning("format does not contain {page}; no page number will be printed", loc)


# Project file names looked for in a directory.
CONFIG_NAMES = ("stoetzms-pdf.yaml", "stoetzms-pdf.yml")


def find_config(path: Path | None = None) -> Path:
    """The project file: ``path`` itself, or the default file in ``path`` or the cwd."""
    directory = Path.cwd() if path is None else Path(path)
    if path is not None and not directory.is_dir():
        return directory
    found = [directory / name for name in CONFIG_NAMES if (directory / name).is_file()]
    if len(found) > 1:
        raise ValidationError(f"both {found[0].name} and {found[1].name} exist in {directory}; "
                              "keep one")
    if not found:
        raise ValidationError(f"no {CONFIG_NAMES[0]} in {directory}; create one or pass the path "
                              "of a project file")
    return found[0]


def load_project(config_path: Path | None = None,
                 output_override: Path | None = None) -> Project:
    """Parse and validate a project file. Raises ValidationError on problems.

    ``config_path`` may also be a directory, or None for the current one; the
    default project file is looked up there.
    """
    config_path = Path(os.path.abspath(find_config(config_path)))
    diag = Diagnostics()
    shown_name = config_path.name

    if not config_path.is_file():
        raise ValidationError(f"configuration file not found: {config_path}")
    try:
        text = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValidationError(f"cannot read configuration file {config_path}: {exc}") from None

    try:
        data = load_yaml(text)
    except YamlLoadError as exc:
        diag.error(exc.message, Location(shown_name, exc.line))
        diag.raise_if_errors()
    if not isinstance(data, dict):
        diag.error("the configuration must be a mapping with 'document' and 'sections'",
                   Location(shown_name, 1))
        diag.raise_if_errors()

    parser = SchemaParser(shown_name, diag)
    config: ProjectConfig | None = parser.parse(ProjectConfig, data)
    diag.raise_if_errors()
    assert config is not None

    root = config_path.parent
    doc = config.document
    labels = dict(LABELS.get(doc.language.split("-")[0].lower(), LABELS["en"]))

    if config.version != 1:
        diag.error(f"unsupported configuration version {config.version}; this tool reads version 1",
                   loc_of(config, "version"))

    # -- templates and style ----------------------------------------------
    template_dir = None
    if doc.templates.directory:
        template_dir = _resolve(root, doc.templates.directory)
        if not template_dir.is_dir():
            diag.error(f"template directory not found: {template_dir}",
                       loc_of(doc.templates, "directory"))
    stylesheets = []
    for index, sheet in enumerate(doc.templates.stylesheets):
        path = _resolve(root, sheet)
        if not path.is_file():
            diag.error(f"stylesheet not found: {path}",
                       Location(shown_name, None, f"document.templates.stylesheets[{index}]"))
        stylesheets.append(path)

    pn = doc.page_numbering
    if pn.start_at < 1:
        diag.error("start_at must be 1 or greater", loc_of(pn, "start_at"))
    _check_format(pn.format, diag, loc_of(pn, "format"))
    if parse_length(pn.margin) is None:
        diag.error(f"margin must be a length such as '12mm' or '0.5in', got {pn.margin!r}",
                   loc_of(pn, "margin"))
    if not 1 <= doc.toc.max_depth <= 3:
        diag.error("max_depth must be 1 (sections), 2 (documents) or 3 (subsections)",
                   loc_of(doc.toc, "max_depth"))

    # -- cover --------------------------------------------------------------
    cover_logo = None
    cover_date = None
    if doc.cover.logo:
        cover_logo = _resolve(root, doc.cover.logo)
        if doc.cover.enabled and not cover_logo.is_file():
            diag.error(f"logo not found: {cover_logo}", loc_of(doc.cover, "logo"))
    date_value = doc.cover.date
    if date_value == "today":
        date_value = datetime.date.today()
    if isinstance(date_value, datetime.date):
        cover_date = (date_value.strftime(doc.cover.date_format) if doc.cover.date_format
                      else date_value.isoformat())
    elif date_value is not None:
        cover_date = date_value
        if doc.cover.date_format:
            diag.warning("date_format only applies to dates written as YYYY-MM-DD or 'today'",
                         loc_of(doc.cover, "date_format"))

    # -- divider defaults ---------------------------------------------------
    for name in ("title", "subtitle", "description"):
        if was_given(doc.dividers, name):
            diag.error(f"'{name}' is set per section (sections[n].divider.{name}), "
                       "not in document.dividers", loc_of(doc.dividers, name))
    default_divider_logo = None
    if doc.dividers.logo:
        default_divider_logo = _resolve(root, doc.dividers.logo)
        if not default_divider_logo.is_file():
            diag.error(f"logo not found: {default_divider_logo}", loc_of(doc.dividers, "logo"))

    # -- sections -----------------------------------------------------------
    if not config.sections:
        diag.error("no sections defined", loc_of(config, "sections"))

    sections: list[ResolvedSection] = []
    seen_files: dict[Path, Location | None] = {}
    seen_titles: set[str] = set()
    for s_index, section in enumerate(config.sections):
        s_path = f"sections[{s_index}]"
        s_loc = loc_of(section)
        if not section.enabled:
            continue
        if not section.title.strip():
            diag.error("section title must not be empty", loc_of(section, "title"))
        if section.title in seen_titles:
            diag.warning(f"more than one section is titled {section.title!r}", s_loc)
        seen_titles.add(section.title)

        if not section.documents:
            diag.error(f"section {section.title!r} has no documents", s_loc)
            continue

        documents: list[ResolvedDocument] = []
        for d_index, entry in enumerate(section.documents):
            d_path = f"{s_path}.documents[{d_index}]"
            d_loc = loc_of(entry, "file") or loc_of(entry) or Location(shown_name, None, d_path)
            if not entry.enabled:
                continue
            document = _resolve_document(entry, d_path, d_loc, root, doc, diag)
            if document is None:
                continue
            for path, loc in zip(document.files, _file_locations(document)):
                if path in seen_files:
                    first = seen_files[path]
                    diag.warning(f"{_display(root, path)} is included more than once"
                                 + (f" (also at {first})" if first else ""), loc)
                seen_files.setdefault(path, loc)
            documents.append(document)

        if not documents:
            diag.warning(f"every document in section {section.title!r} is disabled; "
                         "the section is left out", s_loc)
            continue

        number = len(sections) + 1
        divider = _resolve_divider(section, doc, root, labels, default_divider_logo, diag)
        sections.append(ResolvedSection(number, section.title, divider, documents, s_loc))

    if config.sections and not sections and not diag.errors:
        diag.error("no enabled documents; there is nothing to assemble", loc_of(config, "sections"))

    # -- output -------------------------------------------------------------
    if output_override is not None:
        output = Path(os.path.abspath(output_override))
        output_loc = Location("--output")
    else:
        output = _resolve(root, doc.output or f"output/{slugify(doc.title)}.pdf")
        output_loc = loc_of(doc, "output")
    _check_output(output, output_loc, config_path, seen_files, cover_logo, stylesheets,
                  template_dir, diag)


    diag.raise_if_errors()
    return Project(
        config_path=config_path,
        root=root,
        config=config,
        output=output,
        sections=sections,
        labels=labels,
        cover_date=cover_date,
        cover_logo=cover_logo if doc.cover.enabled else None,
        template_dir=template_dir,
        stylesheets=stylesheets,
        diagnostics=diag,
    )


def _display(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _file_locations(document: ResolvedDocument) -> list[Location | None]:
    if document.images:
        return [image.location for image in document.images]
    return [document.location]


_IMAGE_OPTIONS = ("per_page", "columns", "show_title", "page_size")
_PDF_OPTIONS = ("source_bookmarks", "password_env", "allow_restricted")


def _resolve_document(entry: DocumentEntry, d_path: str, d_loc: Location | None, root: Path,
                      doc: DocumentConfig, diag: Diagnostics) -> ResolvedDocument | None:
    """Check one document entry and decide whether it is a PDF or images."""
    if entry.file is not None and entry.images:
        diag.error("use either 'file' or 'images', not both", loc_of(entry, "images") or d_loc)
        return None
    if entry.file is None and not entry.images:
        if was_given(entry, "images"):
            diag.error("images must list at least one image", loc_of(entry, "images") or d_loc)
        else:
            diag.error("a document needs 'file' (a PDF or an image) or 'images'", d_loc)
        return None
    if entry.file is not None and not entry.file.strip():
        diag.error("file must not be empty", d_loc)
        return None

    images: list[ResolvedImage] = []
    if entry.images:
        for i_index, item in enumerate(entry.images):
            i_loc = loc_of(item, "file") or Location(d_loc.file if d_loc else None, None,
                                                    f"{d_path}.images[{i_index}]")
            if not item.file.strip():
                diag.error("file must not be empty", i_loc)
                return None
            images.append(ResolvedImage(_resolve(root, item.file), item.title, i_loc))
    elif Path(entry.file).suffix.lower() in IMAGE_SUFFIXES:
        images.append(ResolvedImage(_resolve(root, entry.file), None, d_loc))

    for sub in _walk_subsections(entry.subsections):
        if sub.page < 1:
            diag.error("subsection page numbers start at 1", loc_of(sub, "page"))

    if not images:
        for name in _IMAGE_OPTIONS:
            if was_given(entry, name):
                diag.error(f"'{name}' only applies to image documents", loc_of(entry, name))
        path = _resolve(root, entry.file)
        source_bookmarks = (entry.source_bookmarks if entry.source_bookmarks is not None
                            else doc.bookmarks.include_source_bookmarks)
        return ResolvedDocument(path=path, title=entry.title or title_from_filename(path),
                                entry=entry, source_bookmarks=source_bookmarks,
                                location=d_loc, shown=_display(root, path))

    for name in _PDF_OPTIONS:
        if was_given(entry, name):
            diag.error(f"'{name}' only applies to PDF documents", loc_of(entry, name))
    if entry.per_page < 1:
        diag.error("per_page must be 1 or greater", loc_of(entry, "per_page"))
        return None
    if entry.columns is not None and not 1 <= entry.columns <= entry.per_page:
        diag.error(f"columns must be between 1 and per_page ({entry.per_page})",
                   loc_of(entry, "columns"))
    first = _display(root, images[0].path)
    shown = first if len(images) == 1 else f"{first} and {len(images) - 1} more image(s)"
    document = ResolvedDocument(path=None, title=entry.title or title_from_filename(images[0].path),
                                entry=entry, source_bookmarks=False, location=d_loc,
                                images=images, shown=shown)
    pages = document.image_page_count
    for sub in _walk_subsections(entry.subsections):
        if sub.page > pages:
            diag.error(f"subsection {sub.title!r} points to page {sub.page}, but the "
                       f"{len(images)} image(s) fill {pages} page(s)",
                       loc_of(sub, "page") or d_loc)
    return document


def _walk_subsections(subsections: list[Subsection]):
    for sub in subsections:
        yield sub
        yield from _walk_subsections(sub.subsections)


def _resolve_divider(section: SectionConfig, doc: DocumentConfig, root: Path,
                     labels: dict[str, str], default_logo: Path | None,
                     diag: Diagnostics) -> ResolvedDivider | None:
    own, defaults = section.divider, doc.dividers

    def pick(name: str, fallback: Any) -> Any:
        value = getattr(own, name)
        if value is None:
            value = getattr(defaults, name)
        return fallback if value is None else value

    if not pick("enabled", True):
        return None
    logo = default_logo
    if own.logo:
        logo = _resolve(root, own.logo)
        if not logo.is_file():
            diag.error(f"logo not found: {logo}", loc_of(own, "logo"))
    return ResolvedDivider(
        title=own.title or section.title,
        subtitle=own.subtitle,
        description=own.description,
        logo=logo,
        show_number=pick("show_number", doc.number_sections),
        list_documents=pick("list_documents", False),
        label=pick("label", labels["section"]),
        template=pick("template", "divider.html"),
    )


def _check_output(output: Path, loc: Location | None, config_path: Path,
                  sources: dict[Path, Location | None], cover_logo: Path | None,
                  stylesheets: list[Path], template_dir: Path | None,
                  diag: Diagnostics) -> None:
    if output.exists() and output.is_dir():
        diag.error(f"output path is a directory: {output}", loc)
        return
    if output.suffix.lower() != ".pdf":
        diag.warning(f"output file does not end in .pdf: {output.name}", loc)
    for parent in output.parents:
        if parent.exists():
            if not parent.is_dir():
                diag.error(f"output directory {parent} is a file", loc)
            elif not os.access(parent, os.W_OK):
                diag.error(f"output directory {parent} is not writable", loc)
            break
    protected = [config_path, *sources, *stylesheets]
    if cover_logo:
        protected.append(cover_logo)
    for path in protected:
        if output == path or _same_file(output, path):
            diag.error(f"output would overwrite an input file: {path}", loc)
            return
    if template_dir and template_dir in output.parents:
        diag.warning("output is written inside the template directory", loc)
