---
# https://vitepress.dev/reference/default-theme-home-page
layout: home

hero:
    name: 'pdf.stoetz.ms'
    text: 'Assemble PDFs and images into one structured document.'
    tagline: Cover page, table of contents, section dividers, bookmarks and page numbers, from one YAML file.
    image:
        src: /hero.png
        alt: Cover page and table of contents of an assembled document
    actions:
        - theme: brand
          text: User Guide
          link: /user-guide
        - theme: alt
          text: Configuration
          link: /configuration
        - theme: alt
          text: Example PDF
          link: ./example.pdf
          target: _blank

features:
    - title: Declarative
      details: Describe the document in one YAML file — sections, PDFs, images, cover, table of contents and page numbers. Edit it or replace a source, run one command, and everything is regenerated with correct page references.

    - title: Offline
      details: Everything runs locally on your machine. Nothing is uploaded, templates cannot load remote resources, and the same inputs produce a byte-identical PDF.

    - title: Open-source
      details: Apache-2.0 licensed and built on WeasyPrint, pikepdf and Jinja. Covers, dividers and the table of contents are plain HTML and CSS templates you can change.
---
