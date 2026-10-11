# Customization

The cover, table of contents, dividers, image pages and page numbers are
HTML/CSS rendered by WeasyPrint. They can be changed at three levels, without touching
Python code. Source documents are never styled.

## Style values

`document.style` sets the page size, margins, fonts and colours used by the
default stylesheet:

```yaml
document:
  style:
    font_family: '"Source Serif 4", Georgia, serif'
    accent_color: "#7a1f2b"
    cover_align: center
```

## Extra stylesheets

Stylesheets listed in `document.templates.stylesheets` are applied after the
default one, so their rules win:

```yaml
document:
  templates:
    stylesheets: [styles/dossier.css]
```

```css
/* styles/dossier.css */
.cover-title { font-size: 32pt; letter-spacing: -0.01em; }
.toc-item.level-1 > .toc-entry { text-transform: uppercase; }
.divider-page { border-left: 4pt solid #7a1f2b; padding-left: 10mm; }
```

Relative URLs in a stylesheet resolve against the stylesheet; in templates
they resolve against the project directory.

## Replacement templates

Set `document.templates.directory`. Any file there replaces the built-in file
of the same name; files you do not provide fall back to the built-ins.

| File | Purpose | Variables |
|---|---|---|
| `base.html` | Shared HTML skeleton | — |
| `cover.html` | Cover page | `cover.title`, `.subtitle`, `.author`, `.date`, `.logo` (URL), `.details` (`label`, `value`), `.accent_bar` |
| `toc.html` | Table of contents | `toc.title`, `.include_page_numbers`, `.links`, `.max_depth`; `entries` (tree) |
| `images.html` | Pages of an image document | `images.title`, `.show_title`, `.page_style`, `.area_height`, `.heading_height`, `.caption_height`, `.pages` (list of pages, each a list of `src`, `title`, `left`, `top`, `cell_width`, `width`, `height` in points) |
| `divider.html` | Section divider | `divider.title`, `.subtitle`, `.description`, `.logo`, `.number`, `.label`, `.list_documents`, `.documents`; `section` |
| `default.css` | Default stylesheet (a Jinja template) | `style`, `toc`, `heading_font_family`, `toc_leader` |
| `page-number.css` | Page number layout (a Jinja template) | `page_numbering`, `font_family`, `color`, `margin_box`, `vertical_margin`, `horizontal_margin`, `sizes` |

Every template also receives `document` (the `document` options), `style`,
`labels` (default wording for the language) and `sections` (`number`,
`title`, `documents[].title`).

The built-in templates in `src/stoetzms_pdf/templates/` are the best
starting point: copy one into your directory and edit it. Undefined variables
are errors, so a typo in a template stops the build instead of printing
nothing.

### TOC entries and links

Each item of `entries` has `title`, `number` (with `number_sections`),
`level` (1 section, 2 document, 3 subsection), `kind`, `label` (printed page
number), `page` (physical page, 1-based), `href` and `children`.

To make anything clickable, link to `entry.href` (`stoetzms-pdf:entry/<id>`).
After assembly these links are rewritten into PDF links to the entry's final
page, and the build checks that each one points where it should. A link
that names an unknown entry fails the build.

The default TOC puts the number after a leader with
`content: leader(dotted) " " attr(data-page)`; WeasyPrint supports CSS
leaders, `target-counter` is not needed because numbers are computed before
rendering.

### Image pages

The grid is computed by pdf.stoetz.ms: `images.html` receives each image's
position within the page's content box and its size, already scaled to fit.
Restyle captions and headings with `.image-heading` and
`.image-cell figcaption`. A custom `images.html` must keep each page's
images on one page (the build checks the page count). Image pages use the
named page `image-page`, so `@page image-page { ... }` styles only them.

### Page numbers

Page numbers are rendered as one small page per numbered page, sized like the
page it goes on, and laid over it. The text is placed by a CSS page-margin
box chosen by `position` and comes from the `page-number` string. To restyle
it beyond the `page_numbering` options, copy `page-number.css` into your
template directory, e.g. to add a rule above the number:

```css
@page { @bottom-center { border-top: 0.5pt solid #999; padding-top: 2mm; } }
```

## Fonts and offline use

Only local files and `data:` URLs can be loaded; a remote URL in a template or
stylesheet is an error. Fonts named in CSS are looked up among the fonts
installed on the system. To get the same output on every machine, keep the
font files in the project and declare them:

```css
@font-face {
  font-family: "Source Serif 4";
  src: url("../fonts/SourceSerif4-Regular.otf");
}
@font-face {
  font-family: "Source Serif 4";
  font-weight: 600;
  src: url("../fonts/SourceSerif4-Semibold.otf");
}
```
