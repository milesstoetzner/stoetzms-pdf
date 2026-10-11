# Configuration

A project file is named `stoetzms-pdf.yaml` by default (see the [command line](./user-guide#command-line)). It has three top-level keys:

```yaml
version: 1        # optional; the only supported version
document: {...}   # required; title is the only required option
sections: [...]   # required; at least one section with a document
```

Unknown options are errors (with a "did you mean" hint), so a typo never
silently does nothing. All paths are relative to the project file.

Several options accept a shorthand: `cover: false`, `toc: false`,
`bookmarks: false`, `page_numbering: false` and `divider: false` mean
`{enabled: false}`, and a document or image can be given as just its path.

## `document`

| Option | Default | |
|---|---|---|
| `title` | — (required) | Document title: cover, PDF metadata, default output name. |
| `subtitle` | none | Shown on the cover. |
| `author` | none | Cover and PDF metadata. |
| `subject` | none | PDF metadata. |
| `keywords` | `[]` | PDF metadata. |
| `language` | `en` | `lang` of generated pages and of the PDF. `de` and `fr` also switch the default wording ("Inhaltsverzeichnis", "Abschnitt"). |
| `output` | `output/<title-as-slug>.pdf` | Output file. `--output` overrides it. |
| `number_sections` | `false` | Number sections (`1.`, `2.`, …) in the TOC, bookmarks and dividers. |
| `timestamp` | `false` | Embed the build time in the PDF metadata. Off by default for reproducible output. |
| `cover` | | See below. |
| `toc` | | See below. |
| `bookmarks` | | See below. |
| `page_numbering` | | See below. |
| `dividers` | | Defaults for every section divider. See below. |
| `style` | | See below. |
| `templates` | | See below. |

### `document.cover`

The cover shows the title and, when set, everything else below.

| Option | Default | |
|---|---|---|
| `enabled` | `true` | |
| `title` | `document.title` | |
| `subtitle` | `document.subtitle` | |
| `author` | `document.author` | |
| `date` | none | Text, a date (`2026-10-11`), or `today` (uses the build date — this makes the output change daily). |
| `date_format` | ISO | `strftime` pattern for dates, e.g. `"%d %B %Y"`. |
| `logo` | none | Image file (PNG, JPEG, SVG, …). |
| `details` | `[]` | Extra lines on the cover: a list of `{label: ..., value: ...}`. |
| `accent_bar` | `false` | A short rule above the title. |
| `template` | `cover.html` | Template name. |

### `document.toc`

| Option | Default | |
|---|---|---|
| `enabled` | `true` | |
| `title` | "Table of Contents" | Depends on `language`. |
| `include_page_numbers` | `true` | |
| `include_document_entries` | `true` | `false` lists sections only. |
| `max_depth` | `2` | `1` sections, `2` + documents, `3` + subsections. |
| `indent` | `1.6em` | Indentation per level (CSS length). |
| `leader` | `dotted` | `dotted`, `solid`, `space` or `none`. |
| `links` | `true` | Make entries clickable. |
| `template` | `toc.html` | |

The TOC grows to as many pages as it needs; page numbers account for its
final length.

### `document.bookmarks`

| Option | Default | |
|---|---|---|
| `enabled` | `true` | |
| `include_subsections` | `true` | Bookmark configured `subsections`. |
| `include_source_bookmarks` | `false` | Nest each source PDF's own bookmarks under its document. Per document: `source_bookmarks`. |
| `expand_sections` | `true` | Show sections expanded in the viewer's bookmark panel. |

Section bookmarks point to the divider, or to the first page of the first
document if the section has no divider. Document bookmarks point to the
document's first page.

### `document.page_numbering`

| Option | Default | |
|---|---|---|
| `enabled` | `true` | Print numbers on pages. When `false`, the TOC and page labels still use the numbering below. |
| `position` | `bottom-center` | `bottom-left`, `bottom-center`, `bottom-right`, `top-left`, `top-center`, `top-right`. |
| `start_at` | `1` | First number of the main sequence. |
| `style` | `arabic` | `arabic`, `lower-roman` or `upper-roman`. |
| `count_from` | `document` | `document`: physical page 1 is `start_at`. `content`: cover and TOC are numbered separately and the first section starts at `start_at`. |
| `front_matter_style` | `lower-roman` | Style of the cover/TOC sequence with `count_from: content`. |
| `format` | `"{page}"` | Text to print. `{page}` is the page's label, `{total}` the last label, e.g. `"Page {page} of {total}"`. |
| `cover` | `false` | Print the number on the cover. |
| `toc` | `true` | … on TOC pages. |
| `dividers` | `false` | … on divider pages. |
| `source_documents` | `false` | … on source PDF pages (as an overlay; the original content is untouched). |
| `font_family` | `style.font_family` | |
| `font_size` | `9pt` | |
| `color` | `style.muted_color` | |
| `margin` | `12mm` | Distance from the page edge to the number (`mm`, `cm`, `in`, `pt`). |
| `page_labels` | `true` | Store the labels in the PDF so viewers show the printed numbers. |

Pages that do not show a number are still counted.

### `document.dividers` and `sections[].divider`

`document.dividers` sets defaults; `divider` in a section overrides them.

| Option | Default | |
|---|---|---|
| `enabled` | `true` | `false`: the section starts with its first document. |
| `title` | section title | Section level only. |
| `subtitle` | none | Section level only. |
| `description` | none | Section level only. |
| `logo` | none | Image file. |
| `show_number` | `document.number_sections` | Show "Section 2" above the title. |
| `list_documents` | `false` | List the section's document titles on the divider. |
| `label` | "Section" | Word before the number; depends on `language`. |
| `template` | `divider.html` | |

### `document.style`

Values used by the default stylesheet. Any CSS value is accepted.

| Option | Default |
|---|---|
| `page_size` | `A4` (`Letter`, `A4 landscape`, `210mm 297mm`, …) |
| `margin` | `25mm` |
| `font_family` | Helvetica Neue / Helvetica / Arial / Liberation Sans / DejaVu Sans |
| `heading_font_family` | `font_family` |
| `base_font_size` | `10.5pt` |
| `text_color` | `#000000` |
| `muted_color` | `#000000` |
| `accent_color` | `#000000` |
| `rule_color` | `#000000` |
| `cover_align` | `left` (`center`, `right`) |
| `divider_align` | `left` (`center`, `right`) |

`page_size` applies to generated pages only; source documents keep their own
sizes.

### `document.templates`

| Option | Default | |
|---|---|---|
| `directory` | none | Folder searched for templates before the built-in ones. |
| `stylesheets` | `[]` | CSS files applied after the default stylesheet. |

See [customization.md](customization.md).

## `sections`

| Option | Default | |
|---|---|---|
| `title` | — (required) | |
| `enabled` | `true` | `false` leaves the whole section out. |
| `divider` | defaults | See above. |
| `documents` | — (required) | At least one document. |

A section with no documents is an error. A section whose documents are all
disabled is left out with a warning.

### `sections[].documents[]`

A document is either a PDF (`file: x.pdf`) or images (`images: [...]`, or
`file:` with an image).

| Option | Default | |
|---|---|---|
| `file` | — | Source PDF, or a single image (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.tif`, `.tiff`, `.bmp`). |
| `images` | — | List of images, instead of `file`. See below. |
| `title` | file name | `application-form.pdf` becomes "Application form". |
| `enabled` | `true` | `false` leaves the document out (its files are not checked). |
| `subsections` | `[]` | Bookmarks/TOC entries inside the document: `{title, page, subsections}` with a 1-based `page` within the document. Shown in the TOC with `max_depth: 3`. |

PDF documents only:

| Option | Default | |
|---|---|---|
| `source_bookmarks` | `bookmarks.include_source_bookmarks` | Nest the PDF's own bookmarks under this document. |
| `password_env` | none | Name of an environment variable with the PDF's password. |
| `allow_restricted` | `false` | Accept a PDF with an owner password (permission restrictions). The output is not encrypted. |

Image documents only:

| Option | Default | |
|---|---|---|
| `per_page` | `1` | Images per page. |
| `columns` | automatic | Grid columns. By default a portrait page is filled top to bottom (2 → 1×2, 4 → 2×2, 6 → 2×3, 9 → 3×3) and a landscape page left to right. |
| `show_title` | `true` | Print the document title above the images on each page. |
| `page_size` | `style.page_size` | Page size for these pages, e.g. `A4 landscape`. |

Including the same file twice produces a warning.

### Image documents

```yaml
documents:
  - documents/scan.jpg              # one image, one page
  - title: "Identity Card"
    per_page: 2
    images:
      - file: documents/id-front.jpg
        title: "Front"              # caption under the image
      - documents/id-back.jpg       # no caption
```

Each item of `images` is a path or `{file, title}`; `title` is printed as a
caption under the image. Images are laid out in a grid, in order, filling
`per_page` cells per page; the last page may be partly empty. Each image is
scaled to fit its cell with its proportions kept, and never enlarged beyond
96 dpi, so small images stay sharp. The camera orientation stored in a JPEG
(EXIF) is applied, so phone photos appear upright.

Images are embedded as they are (JPEG data is not re-compressed), so a
document with many full-resolution photos produces a large PDF; scale them
down beforehand if size matters.

Image pages are generated pages: they use the document's margins and fonts,
and show page numbers when `page_numbering.source_documents` is on. The
layout comes from the `images.html` template (see
[customization](customization.md)). A missing, damaged or unsupported image
is an error that names the image's line in the project file.
