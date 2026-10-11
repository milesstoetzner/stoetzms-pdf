# User Guide

## Installation

Install the binary on Linux or macOS using ...

```shell
curl -fsSL https://pdf.stoetz.ms/install.sh | sudo bash -
```

Install the binary on Windows using ...

```powershell
powershell -Command "& {Invoke-WebRequest -Uri 'https://pdf.stoetz.ms/install.ps1' -UseBasicParsing | Invoke-Expression}"
```

Then check that it works.

```shell
stoetzms-pdf --version
```

Running the same command again updates to the latest release. Binaries are available for Linux (x64 and arm64, glibc 2.35 or newer, e.g. Ubuntu 22.04 or Debian 12), macOS (Apple silicon, macOS 15 or newer) and Windows (x64). They need no Python and bring their own text-layout libraries; on Linux, at least one font must be installed (e.g. `apt install fonts-dejavu-core`). The first run takes a few seconds longer while the font cache is built.

### Installing with pip

On other systems, install from source. This needs Python 3.11 or newer and the Pango library.

```shell
# macOS
brew install pango
# Debian / Ubuntu
sudo apt install libpango-1.0-0 libpangoft2-1.0-0

pipx install git+https://github.com/milesstoetzner/stoetzms-pdf.git
```

See the [WeasyPrint installation notes](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html) for Pango on other platforms.

### Uninstalling

On Linux and macOS, remove `/usr/local/bin/stoetzms-pdf` and `/usr/local/lib/stoetzms-pdf`. On Windows, remove `%LOCALAPPDATA%\stoetzms-pdf` and its entry in the user's `PATH`.

## Quick Start

```
application/
├── stoetzms-pdf.yaml
├── documents/
│   ├── application-form.pdf
│   ├── passport.pdf
│   ├── diploma.pdf
│   └── transcript.pdf
└── assets/
    └── logo.svg
```

A minimal `stoetzms-pdf.yaml` ...

```yaml
document:
    title: 'Application for Example'

sections:
    - title: 'Application'
      documents:
          - documents/application-form.pdf
    - title: 'Qualifications'
      documents:
          - file: documents/diploma.pdf
            title: 'University Diploma'
          - file: documents/transcript.pdf
            title: 'Academic Transcript'
```

... in `stoetzms-pdf.yaml` and one command in the same directory.

```shell
stoetzms-pdf
```

This produces `output/application-for-example.pdf` with a cover, a table of contents, a divider page before each section, bookmarks, and page numbers on the TOC. Every option is listed in the [Configuration](./configuration) reference.

## Images

PNG and JPEG files (also GIF, WebP, TIFF and BMP) can be included next to PDFs. A single image becomes a page of its own; several images can share a page, each with an optional caption.

```yaml
documents:
    - documents/scan.jpg
    - title: 'Identity Card'
      per_page: 2
      images:
          - file: documents/id-front.jpg
            title: 'Front'
          - file: documents/id-back.jpg
            title: 'Back'
```

Images are scaled to fit, keep their proportions, and phone photos are turned upright. `per_page`, `columns`, `show_title` and `page_size` control the layout; see [image documents](./configuration#image-documents).

A complete example is in [examples/application](https://github.com/milesstoetzner/stoetzms-pdf/tree/main/examples/application). Its generated output is the [example PDF](./example.pdf){target="_blank"}: 14 pages with cover, table of contents, section dividers, bookmarks, page numbers, and two image documents (an identity card scanned front and back, two per page, and four certificates on one page).

```shell
cd examples/application
stoetzms-pdf
open output/application.pdf
```

## Command Line

```shell
stoetzms-pdf [CONFIG] [-o OUTPUT] [--check] [-v] [-q] [--strict]
```

`CONFIG` is the project file. Without it, `stoetzms-pdf.yaml` (or `stoetzms-pdf.yml`) in the current directory is used; if `CONFIG` is a directory, the project file is looked up there.

| Option              |                                                                                                                         |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `-o, --output PATH` | Write here instead of `document.output`. Relative to the current directory.                                            |
| `--check`           | Validate the configuration, inputs and templates, and lay out the document (including the TOC), without writing anything. |
| `-v, --verbose`     | Print the page plan: physical pages, printed labels and source of every part.                                           |
| `-q, --quiet`       | Print only warnings and errors.                                                                                         |
| `--strict`          | Treat warnings as errors; the previous output is kept. Useful in CI.                                                    |

Exit codes: `0` success, `1` build failed, `2` invalid configuration or input, `3` warnings with `--strict`.

Paths inside the YAML file are always resolved relative to the YAML file, so the command works from any directory.

## How a Build Works

1. **Validate and inspect.** The YAML is parsed with line tracking; unknown options, wrong types and duplicate keys are errors that name the file, line and option path (`stoetzms-pdf.yaml:12 (sections[1].documents[0].file)`). Every source PDF is read once into memory and checked: missing, unreadable, corrupted, encrypted and empty files are errors. All problems are reported together.
2. **Generate.** The cover and dividers are rendered from HTML/CSS templates.
3. **Lay out.** Page positions follow from page counts. The TOC is rendered with the page numbers that result from its own length, and re-rendered until the page count it was laid out for equals the page count it produces. If it would oscillate, it is padded with a blank page rather than printing wrong numbers; if it does not settle, the build fails.
4. **Assemble and verify.** Pages are copied, page numbers are laid over the pages that should show them, and bookmarks, TOC links, page labels and metadata are added. The file is written to a temporary file next to the output and read back: page count, page sizes, bookmark targets, TOC link targets and page labels are checked against the plan. Only then does it replace the previous output (atomically, keeping its file permissions).

A failed build never leaves a partial or stale-but-new-looking file behind.

## Page Numbers

Every page has a physical position and a printed label. All pages are counted; `cover`, `toc`, `dividers` and `source_documents` only decide which pages _show_ their number. The TOC prints the same labels, and the PDF's page labels make viewers display them too, so "page 7" in the TOC is "7" in the viewer's page box.

By default physical page 1 is number 1. With `count_from: content` the cover and TOC are numbered separately (lower-case Roman by default) and the first section starts at `start_at`.

Numbers are rendered with the same CSS machinery as the other generated pages and placed as a transparent overlay, so they work on any page size and respect `/Rotate`. `source_documents` defaults to `false` so source pages are left exactly as they are.

## Limits

- **Fonts.** Generated pages (cover, table of contents, dividers, image pages, page numbers) use the fonts installed on the machine, so they can look different on another machine. Ship the font files with the project to avoid this (see [Customization](./customization#fonts-and-offline-use)).
- **Local files only.** Templates and stylesheets can load only local files and `data:` URLs; a remote URL is an error.
- **Digital signatures.** A signature in a source PDF does not apply to the assembled document; signed sources produce a warning. Submit the original where a valid signature is required.
- **Encryption.** Password-protected PDFs need `password_env`, and PDFs with permission restrictions need `allow_restricted: true`. The output is never encrypted.
- **Form fields.** If two documents use the same field name, one is renamed (with a warning).
- **Not carried over** from source PDFs: their metadata, layer (optional content) settings (with a warning), attachments, JavaScript and tagged-PDF structure.
- **Image size.** Images are embedded without re-compression, so many full-resolution photos make a large PDF.
