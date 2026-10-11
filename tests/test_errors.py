"""Validation, diagnostics and safe output replacement."""

from __future__ import annotations

import os
from pathlib import Path

import pikepdf
import pytest

from stoetzms_pdf.build import build
from stoetzms_pdf.cli import main
from stoetzms_pdf.errors import BuildError, ValidationError

from conftest import make_pdf


def simple(project, tmp_path: Path, documents: str = "[a.pdf]", document: str = "") -> Path:
    if not (tmp_path / "a.pdf").exists():
        make_pdf(tmp_path / "a.pdf", 2)
    return project(f"""
        document:
          title: T
          output: out/t.pdf
        {document}
        sections:
          - title: S
            documents: {documents}
        """)


def messages(exc: pytest.ExceptionInfo) -> str:
    return "\n".join(str(p) for p in exc.value.problems)


def test_invalid_yaml_reports_line(project):
    config = project("""
        document:
          title: "T
        sections: []
        """)
    with pytest.raises(ValidationError) as exc:
        build(config)
    assert "stoetzms-pdf.yaml:" in messages(exc) and "invalid YAML" in messages(exc)


def test_unknown_option_is_rejected_with_suggestion_and_line(project, tmp_path):
    make_pdf(tmp_path / "a.pdf", 1)
    config = project("""
        document:
          title: T
          tocc: {enabled: false}
        sections:
          - title: S
            documents:
              - file: a.pdf
                titel: Typo
        """)
    with pytest.raises(ValidationError) as exc:
        build(config)
    text = messages(exc)
    assert "stoetzms-pdf.yaml:4 (document.tocc): unsupported option 'tocc' (did you mean 'toc'?)" in text
    assert "stoetzms-pdf.yaml:9 (sections[0].documents[0].titel)" in text
    assert "did you mean 'title'?" in text


def test_duplicate_key_is_an_error(project):
    config = project("""
        document:
          title: A
          title: B
        sections: []
        """)
    with pytest.raises(ValidationError) as exc:
        build(config)
    assert "duplicate key 'title'" in messages(exc)


def test_wrong_types_and_values(project, tmp_path):
    make_pdf(tmp_path / "a.pdf", 1)
    config = project("""
        document:
          title: T
          toc: {max_depth: 7}
          page_numbering:
            position: middle
            start_at: 0
            format: "{pg}"
          cover: {enabled: "yes please"}
        sections:
          - title: S
            documents: a.pdf
        """)
    with pytest.raises(ValidationError) as exc:
        build(config)
    text = messages(exc)
    assert "document.cover.enabled): expected true or false, got text" in text
    assert "invalid value 'middle'" in text
    assert "sections[0].documents): expected a list" in text


def test_semantic_checks(project, tmp_path):
    make_pdf(tmp_path / "a.pdf", 1)
    config = project("""
        document:
          title: T
          toc: {max_depth: 7}
          page_numbering: {start_at: 0, format: "{pg}"}
        sections:
          - title: S
            documents: [a.pdf]
        """)
    with pytest.raises(ValidationError) as exc:
        build(config)
    text = messages(exc)
    assert "max_depth must be" in text
    assert "start_at must be 1 or greater" in text
    assert "unknown placeholder {pg}" in text


def test_missing_title_and_sections(project):
    config = project("""
        document: {}
        """)
    with pytest.raises(ValidationError) as exc:
        build(config)
    assert "missing required option 'title'" in messages(exc)
    assert "missing required option 'sections'" in messages(exc)


def test_missing_source_file_names_file_and_config_line(project, tmp_path):
    config = simple(project, tmp_path, documents="[a.pdf, missing.pdf]")
    with pytest.raises(ValidationError) as exc:
        build(config)
    text = messages(exc)
    assert "source file not found: missing.pdf" in text
    assert "sections[0].documents[1]" in text


def test_disabled_document_is_not_checked_or_included(project, tmp_path):
    make_pdf(tmp_path / "a.pdf", 2)
    config = simple(project, tmp_path, documents="""
              - a.pdf
              - {file: missing.pdf, enabled: false}""")
    result = build(config)
    assert result.plan.parts[-1].title == "A"
    assert result.plan.total_pages == 5


def test_corrupted_pdf_is_an_error(project, tmp_path):
    (tmp_path / "bad.pdf").write_bytes(b"%PDF-1.7\n this is not a pdf at all")
    (tmp_path / "text.pdf").write_text("plain text")
    config = simple(project, tmp_path, documents="[a.pdf, bad.pdf, text.pdf]")
    with pytest.raises(ValidationError) as exc:
        build(config)
    text = messages(exc)
    assert "bad.pdf" in text and "text.pdf is not a PDF file" in text


def test_truncated_pdf_is_reported(project, tmp_path):
    make_pdf(tmp_path / "full.pdf", 3)
    data = (tmp_path / "full.pdf").read_bytes()
    (tmp_path / "cut.pdf").write_bytes(data[: len(data) // 2])
    config = simple(project, tmp_path, documents="[cut.pdf]")
    try:
        result = build(config)
    except ValidationError as exc:
        assert "cut.pdf" in str(exc)
    else:  # qpdf could reconstruct it: that must be a visible warning
        assert any("cut.pdf" in str(w) and "repaired" in str(w)
                   for w in result.diagnostics.warnings)


def test_encrypted_pdf_needs_password(project, tmp_path, monkeypatch):
    make_pdf(tmp_path / "plain.pdf", 1)
    with pikepdf.open(tmp_path / "plain.pdf") as pdf:
        pdf.save(tmp_path / "locked.pdf", encryption=pikepdf.Encryption(user="u", owner="o"))
        pdf.save(tmp_path / "restricted.pdf", encryption=pikepdf.Encryption(user="", owner="o"))
    config = simple(project, tmp_path, documents="[locked.pdf, restricted.pdf]")
    with pytest.raises(ValidationError) as exc:
        build(config)
    text = messages(exc)
    assert "locked.pdf is password-protected" in text
    assert "restricted.pdf is encrypted with usage restrictions" in text

    monkeypatch.setenv("LOCKED_PW", "u")
    config = simple(project, tmp_path, documents="""
              - {file: locked.pdf, password_env: LOCKED_PW}
              - {file: restricted.pdf, allow_restricted: true}""")
    result = build(config)
    assert result.plan.total_pages == 5
    with pikepdf.open(result.output) as out:
        assert not out.is_encrypted


def test_empty_section_is_an_error(project, tmp_path):
    config = simple(project, tmp_path, documents="[]")
    with pytest.raises(ValidationError) as exc:
        build(config)
    assert "section 'S' has no documents" in messages(exc)


def test_all_documents_disabled_warns_and_omits_section(project, tmp_path):
    make_pdf(tmp_path / "a.pdf", 1)
    config = project("""
        document: {title: T}
        sections:
          - title: Kept
            documents: [a.pdf]
          - title: Dropped
            documents:
              - {file: a.pdf, enabled: false}
        """)
    result = build(config)
    assert [s.title for s in result.project.sections] == ["Kept"]
    assert any("section is left out" in str(w) for w in result.diagnostics.warnings)


def test_output_must_not_overwrite_inputs(project, tmp_path):
    config = simple(project, tmp_path)
    with pytest.raises(ValidationError) as exc:
        build(config, output=tmp_path / "a.pdf")
    assert "output would overwrite an input file" in messages(exc)
    with pytest.raises(ValidationError):
        build(config, output=config)
    (tmp_path / "dir.pdf").mkdir()
    with pytest.raises(ValidationError) as exc:
        build(config, output=tmp_path / "dir.pdf")
    assert "is a directory" in messages(exc)


def test_duplicate_file_warns(project, tmp_path):
    config = simple(project, tmp_path, documents="[a.pdf, ./a.pdf]")
    result = build(config)
    assert any("included more than once" in str(w) for w in result.diagnostics.warnings)


def test_subsection_page_out_of_range(project, tmp_path):
    config = simple(project, tmp_path, documents="""
              - file: a.pdf
                subsections: [{title: Far, page: 9}]""")
    with pytest.raises(ValidationError) as exc:
        build(config)
    assert "points to page 9, but a.pdf has 2 page(s)" in messages(exc)


def test_missing_logo_and_remote_assets(project, tmp_path):
    config = simple(project, tmp_path, document="""
          cover: {logo: assets/nope.png}""")
    with pytest.raises(ValidationError) as exc:
        build(config)
    assert "logo not found" in messages(exc)

    (tmp_path / "remote.css").write_text(
        '@import url("https://example.org/x.css");\n'
        'body { background: url("https://example.org/bg.png"); }')
    config = simple(project, tmp_path, document="""
          templates: {stylesheets: [remote.css]}""")
    with pytest.raises(BuildError) as exc:
        build(config)
    assert "not a local file" in messages(exc)


def test_check_does_not_write(project, tmp_path, capsys):
    config = simple(project, tmp_path)
    assert main([str(config), "--check"]) == 0
    assert not (tmp_path / "out").exists()
    assert "would have 5 pages" in capsys.readouterr().out


def test_failed_build_keeps_previous_output_and_leaves_no_temp_files(project, tmp_path,
                                                                    monkeypatch):
    config = simple(project, tmp_path)
    first = build(config).output
    previous = first.read_bytes()
    os.chmod(first, 0o640)

    import stoetzms_pdf.build as build_module

    def broken_validation(*args, **kwargs):
        raise BuildError("simulated validation failure")

    monkeypatch.setattr(build_module, "validate_output", broken_validation)
    make_pdf(tmp_path / "a.pdf", 4)
    with pytest.raises(BuildError):
        build(config)
    assert first.read_bytes() == previous
    assert sorted(p.name for p in first.parent.iterdir()) == ["t.pdf"]

    monkeypatch.undo()
    build(config)
    assert first.read_bytes() != previous
    assert (first.stat().st_mode & 0o777) == 0o640  # permissions kept on replace
    assert sorted(p.name for p in first.parent.iterdir()) == ["t.pdf"]


def test_validation_catches_wrong_bookmark(project, tmp_path, monkeypatch):
    config = simple(project, tmp_path)
    import stoetzms_pdf.assemble as assemble_module

    real = assemble_module._write_outline

    def off_by_one(out, project_, plan):
        for entry in plan.entries():
            entry.offset += 1
        real(out, project_, plan)
        for entry in plan.entries():
            entry.offset -= 1

    monkeypatch.setattr(assemble_module, "_write_outline", off_by_one)
    with pytest.raises(BuildError) as exc:
        build(config)
    assert "bookmark" in str(exc.value) and "expected page" in str(exc.value)
    assert not (tmp_path / "out" / "t.pdf").exists()


def test_signed_pdf_warns_and_strict_fails(project, tmp_path, capsys):
    make_pdf(tmp_path / "signed.pdf", 1)
    with pikepdf.open(tmp_path / "signed.pdf", allow_overwriting_input=True) as pdf:
        sig = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Sig,
                                                   Filter=pikepdf.Name("/Adobe.PPKLite"),
                                                   Contents=pikepdf.String(b"\0" * 16)))
        field = pdf.make_indirect(pikepdf.Dictionary(
            FT=pikepdf.Name.Sig, T=pikepdf.String("Signature1"), V=sig,
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget,
            Rect=[0, 0, 0, 0], P=pdf.pages[0].obj))
        pdf.pages[0].obj.Annots = pdf.make_indirect(pikepdf.Array([field]))
        pdf.Root.AcroForm = pikepdf.Dictionary(Fields=[field], SigFlags=3)
        pdf.save(tmp_path / "signed.pdf")
    config = simple(project, tmp_path, documents="[signed.pdf]")
    result = build(config)
    warnings = [str(w) for w in result.diagnostics.warnings]
    assert any("digitally signed" in w and "invalidates the signature" in w for w in warnings)

    output = result.output
    before = output.read_bytes()
    make_pdf(tmp_path / "a.pdf", 1)
    assert main([str(config), "--strict"]) == 3
    assert output.read_bytes() == before
    assert "--strict" in capsys.readouterr().err


def test_template_override_from_project_directory(project, tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "divider.html").write_text(
        '{% extends "base.html" %}{% block content %}'
        '<p>CUSTOM DIVIDER {{ divider.title }}</p>{% endblock %}')
    config = simple(project, tmp_path, document="""
          templates: {directory: templates}""")
    result = build(config)
    import pymupdf
    with pymupdf.open(result.output) as doc:
        assert "CUSTOM DIVIDER S" in doc[2].get_text()


def test_template_errors_are_reported(project, tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "cover.html").write_text("{{ cover.no_such_field }}")
    config = simple(project, tmp_path, document="""
          templates: {directory: templates}""")
    with pytest.raises(BuildError) as exc:
        build(config)
    assert "template cover.html" in str(exc.value)


def test_missing_fonts_fail_clearly_instead_of_crashing(project, tmp_path, monkeypatch):
    import stoetzms_pdf.render as render_module

    monkeypatch.setattr(render_module, "installed_font_count", lambda: 0)  # cached otherwise
    with pytest.raises(BuildError) as exc:
        build(simple(project, tmp_path))
    assert "no fonts are installed" in str(exc.value)


def test_default_project_file_in_cwd_or_directory(project, tmp_path, monkeypatch, capsys):
    simple(project, tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main([]) == 0
    assert (tmp_path / "out/t.pdf").exists()
    monkeypatch.chdir(tmp_path.parent)
    assert main(["--check", tmp_path.name]) == 0
    assert "stoetzms-pdf.yaml is valid" in capsys.readouterr().out


def test_missing_or_ambiguous_default_project_file(project, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main([]) == 2
    assert "no stoetzms-pdf.yaml in" in capsys.readouterr().err
    simple(project, tmp_path)
    (tmp_path / "stoetzms-pdf.yml").write_text("document: {title: T}\n")
    assert main([]) == 2
    assert "both stoetzms-pdf.yaml and stoetzms-pdf.yml exist" in capsys.readouterr().err
