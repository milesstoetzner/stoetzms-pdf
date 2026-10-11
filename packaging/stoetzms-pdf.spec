# PyInstaller build of the standalone `stoetzms-pdf` binary:
#
#     pyinstaller packaging/stoetzms-pdf.spec
#
# Produces dist/stoetzms-pdf/ (the executable and its libraries); see docs/development.md.

from PyInstaller.utils.hooks import collect_data_files

a = Analysis(
    ["main.py"],
    datas=[
        *collect_data_files("stoetzms_pdf"),
        *collect_data_files("pyphen"),
        ("fontconfig", "fontconfig"),
    ],
    excludes=["tkinter", "pytest", "pymupdf", "fitz"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="stoetzms-pdf", strip=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="stoetzms-pdf", strip=False, upx=False)
