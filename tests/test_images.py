"""Image documents: PNG/JPEG files laid out on generated pages."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
import yaml
from PIL import Image

from stoetzms_pdf.build import build
from stoetzms_pdf.errors import BuildError, ValidationError

from conftest import A4, A4_LANDSCAPE, bookmarks, make_pdf, page_texts


def make_image(path: Path, size=(1200, 800), fmt: str | None = None,
               orientation: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, "white")
    image.paste((0, 0, 0), (0, 0, size[0] // 2, size[1] // 2))
    options = {}
    if orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = orientation
        options["exif"] = exif.tobytes()
    image.save(path, fmt, **options)
    return path


def image_project(tmp_path: Path, documents: list, **document) -> Path:
    config = {
        "document": {"title": "Images", "output": "out/images.pdf", **document},
        "sections": [{"title": "S", "divider": False, "documents": documents}],
    }
    path = tmp_path / "stoetzms-pdf.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def image_boxes(path: Path, page_index: int) -> list[pymupdf.Rect]:
    with pymupdf.open(path) as doc:
        return [pymupdf.Rect(info["bbox"]) for info in doc[page_index].get_image_info()]


def page_size(path: Path, page_index: int) -> tuple[float, float]:
    with pymupdf.open(path) as doc:
        rect = doc[page_index].rect
        return round(rect.width, 2), round(rect.height, 2)


def messages(exc: pytest.ExceptionInfo) -> str:
    return "\n".join(str(p) for p in exc.value.problems)


def test_grid_with_titles_and_captions(tmp_path):
    for i in range(5):
        make_image(tmp_path / f"img/{i}.png", (1200, 800) if i % 2 else (800, 1200))
    config = image_project(tmp_path, [{
        "title": "Site photos",
        "per_page": 4,
        "images": [{"file": "img/0.png", "title": "Front view"}, "img/1.png", "img/2.png",
                   "img/3.png", {"file": "img/4.png", "title": "Roof"}],
    }], toc=False)
    result = build(config)

    assert [p.kind for p in result.plan.parts] == ["cover", "document"]
    assert result.plan.parts[1].page_count == 2
    assert len(image_boxes(result.output, 1)) == 4
    assert len(image_boxes(result.output, 2)) == 1
    texts = page_texts(result.output)
    assert "Site photos" in texts[1] and "Front view" in texts[1]
    assert "Roof" in texts[2]
    # Default for four per page on a portrait page: two columns, two rows.
    boxes = image_boxes(result.output, 1)
    assert len({round(b.x0) for b in boxes}) == 2 and len({round(b.y0) for b in boxes}) == 2
    # Images keep their proportions and stay inside the page.
    for box in boxes:
        assert box.width > 50 and box.x1 < A4[0] and box.y1 < A4[1]
    assert {round(b.width / b.height, 2) for b in boxes} == {round(800 / 1200, 2),
                                                             round(1200 / 800, 2)}
    assert bookmarks(result.output)[-1] == [2, "Site photos", 2]


def test_single_image_file_and_exif_orientation(tmp_path):
    # Stored landscape, EXIF says "rotate 90 degrees": displayed portrait.
    make_image(tmp_path / "scan.jpg", (1200, 800), "JPEG", orientation=6)
    config = image_project(tmp_path, ["scan.jpg"], cover=False, toc=False)
    result = build(config)
    assert result.plan.parts[0].title == "Scan"
    (box,) = image_boxes(result.output, 0)
    assert box.height > box.width
    assert round(box.width / box.height, 2) == round(800 / 1200, 2)
    assert page_size(result.output, 0) == (round(A4[0], 2), round(A4[1], 2))


def test_page_size_columns_and_no_title(tmp_path):
    for i in range(3):
        make_image(tmp_path / f"{i}.png")
    config = image_project(tmp_path, [{
        "title": "Sheet", "images": ["0.png", "1.png", "2.png"], "per_page": 3,
        "columns": 3, "page_size": "A4 landscape", "show_title": False,
    }], cover=False, toc=False)
    result = build(config)
    assert page_size(result.output, 0) == (round(A4_LANDSCAPE[0], 2), round(A4_LANDSCAPE[1], 2))
    boxes = image_boxes(result.output, 0)
    assert len({round(b.y0) for b in boxes}) == 1 and len({round(b.x0) for b in boxes}) == 3
    assert "Sheet" not in page_texts(result.output)[0]


def test_small_images_are_not_enlarged(tmp_path):
    make_image(tmp_path / "icon.png", (96, 48))
    config = image_project(tmp_path, ["icon.png"], cover=False, toc=False)
    (box,) = image_boxes(build(config).output, 0)
    assert round(box.width) == 72 and round(box.height) == 36  # 96 dpi


def test_images_mixed_with_pdfs_and_page_numbers(tmp_path):
    make_pdf(tmp_path / "a.pdf", 2)
    make_image(tmp_path / "b.png")
    config = image_project(tmp_path, ["a.pdf", {"file": "b.png", "title": "Photo"}],
                           page_numbering={"source_documents": True})
    result = build(config)
    assert [(p.kind, p.title, p.page_count) for p in result.plan.parts] == [
        ("cover", "Images", 1), ("toc", "Table of Contents", 1), ("document", "A", 2),
        ("document", "Photo", 1)]
    assert page_texts(result.output)[4].strip().endswith("5")


def test_repeat_builds_are_identical(tmp_path):
    make_image(tmp_path / "a.png")
    make_image(tmp_path / "b.jpg", fmt="JPEG")
    config = image_project(tmp_path, [{"title": "Two", "per_page": 2,
                                       "images": ["a.png", {"file": "b.jpg", "title": "B"}]}])
    first = build(config).output.read_bytes()
    assert build(config).output.read_bytes() == first


@pytest.mark.parametrize("documents, expected", [
    (["missing.png"], "source file not found: missing.png"),
    ([{"images": []}], "images must list at least one image"),
    ([{"title": "X"}], "a document needs 'file' (a PDF or an image) or 'images'"),
    ([{"file": "a.pdf", "images": ["ok.png"]}], "use either 'file' or 'images', not both"),
    ([{"file": "a.pdf", "per_page": 2}], "'per_page' only applies to image documents"),
    ([{"file": "ok.png", "password_env": "X"}], "'password_env' only applies to PDF documents"),
    ([{"images": ["ok.png"], "per_page": 0}], "per_page must be 1 or greater"),
    ([{"images": ["ok.png"], "per_page": 2, "columns": 3}], "columns must be between 1 and"),
    ([{"images": ["ok.png", "ok.png"], "per_page": 2,
       "subsections": [{"title": "Two", "page": 2}]}], "fill 1 page(s)"),
])
def test_configuration_errors(tmp_path, documents, expected):
    make_pdf(tmp_path / "a.pdf", 1)
    make_image(tmp_path / "ok.png")
    with pytest.raises(ValidationError) as exc:
        build(image_project(tmp_path, documents))
    assert expected in messages(exc)


def test_unreadable_images_are_reported_with_location(tmp_path):
    make_image(tmp_path / "ok.png")
    (tmp_path / "text.png").write_text("not an image")
    truncated = make_image(tmp_path / "cut.png", (2000, 2000)).read_bytes()
    (tmp_path / "cut.png").write_bytes(truncated[: len(truncated) // 2])
    make_pdf(tmp_path / "doc.png", 1)
    config = image_project(tmp_path, [{"title": "Bad", "images": [
        "ok.png", "text.png", "cut.png", "doc.png"]}])
    with pytest.raises(ValidationError) as exc:
        build(config)
    text = messages(exc)
    assert "text.png is not an image file" in text
    assert "sections[0].documents[0].images[1]" in text
    assert "cut.png is damaged and cannot be read" in text
    assert "doc.png is a PDF" in text
    assert not (tmp_path / "out/images.pdf").exists()


def test_too_many_images_per_page_fails_clearly(tmp_path):
    make_image(tmp_path / "a.png")
    config = image_project(tmp_path, [{"images": ["a.png"], "per_page": 400}])
    with pytest.raises(BuildError) as exc:
        build(config)
    assert "too little room" in str(exc.value)
