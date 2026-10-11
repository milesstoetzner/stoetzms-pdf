# Development

Clone or fork the repository.

```shell
git clone git@github.com:milesstoetzner/stoetzms-pdf.git
```

## Code

Install the Pango library (see the [User Guide](./user-guide#installation)), then create a virtual environment with the test dependencies.

```shell
python -m venv .venv
.venv/bin/pip install -e '.[test]'
```

For running the tests ...

```shell
.venv/bin/pytest
```

The tests build fixture PDFs on the fly and check page order, text, TOC numbers, link and bookmark destinations, page labels, number placement on rotated pages, error reporting, atomic replacement and byte-identical rebuilds.

For regenerating the example's source PDFs ...

```shell
python examples/make_sample_documents.py
```

### Libraries

PyYAML (configuration), Jinja2 and WeasyPrint (generated pages), pikepdf (inspection, merging, bookmarks, overlays, validation). PyMuPDF (AGPL) is used only by the test suite.

## Binary

The standalone binary is built with PyInstaller on the platform it is for; it bundles Python, the dependencies and the Pango libraries found on the build machine.

```shell
.venv/bin/pip install pyinstaller
PATH=.venv/bin:$PATH packaging/build.sh
```

This produces `dist/stoetzms-pdf-<os>-<arch>.tar.xz` (`.zip` on Windows). `packaging/main.py` makes the binary load its bundled libraries and fonts configuration rather than any system copy.

## Docs

The docs are a VitePress site in `docs/`, the only part of the repository that uses Node.js. We use the Node.js version in `docs/.nvmrc`, currently the LTS Node.js 24.

```shell
cd docs
nvm use
```

For installing dependencies ...

```shell
yarn
```

For developing the docs ...

```shell
yarn dev
```

For building the docs ...

```shell
yarn build
```

## Release

Every push to `main` runs the tests and builds and tests the binaries for Linux, macOS and Windows on GitHub Actions; nothing is published.

To release a version, set `__version__` in `src/stoetzms_pdf/__init__.py` (the only place the version is written), commit, and push a matching tag.

```shell
git tag v0.2.0
git push origin v0.2.0
```

The workflow checks that the tag matches `__version__`, creates the GitHub release `v0.2.0` with the binaries, and deploys the docs. The install scripts install the newest release by default. Running the workflow by hand deploys the docs without a release.
