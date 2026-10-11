"""Entry point of the standalone binary built with PyInstaller.

The binary carries its own Pango, HarfBuzz, fontconfig and GLib. WeasyPrint
loads them by trying several bare names (``pango-1.0``, ...,
``libpango-1.0.dylib``), and the first that resolves anywhere wins, which
would be a system copy if there is one. On macOS and Linux a bare name is
therefore resolved to the bundled file, and names that are not bundled are
refused so WeasyPrint moves on to one that is. On Windows the bundle is
added to the DLL search path, which WeasyPrint uses there.
"""

import os
import sys
from pathlib import Path


def _use_bundled_libraries(bundle: Path) -> None:
    import cffi

    original = cffi.FFI.dlopen

    def dlopen(self, name, flags=0):
        if isinstance(name, str) and "/" not in name:
            if not (bundle / name).exists():
                raise OSError(f"{name} is not part of this binary")
            name = str(bundle / name)
        return original(self, name, flags)

    cffi.FFI.dlopen = dlopen


def _use_font_config(bundle: Path) -> None:
    """Point the bundled fontconfig at a configuration that exists here."""
    if "FONTCONFIG_FILE" in os.environ:
        return
    if sys.platform == "darwin":
        os.environ["FONTCONFIG_FILE"] = str(bundle / "fontconfig" / "macos.conf")
    elif os.name == "nt":
        # Collected from MSYS2 by PyInstaller's WeasyPrint hook; it lists the
        # Windows font folder.
        conf = bundle / "etc" / "fonts" / "fonts.conf"
        if conf.exists():
            os.environ["FONTCONFIG_FILE"] = str(conf)
    elif not Path("/etc/fonts/fonts.conf").exists():
        os.environ["FONTCONFIG_FILE"] = str(bundle / "fontconfig" / "linux.conf")


if getattr(sys, "frozen", False):
    _bundle = Path(sys._MEIPASS)
    if os.name == "nt":
        os.add_dll_directory(str(_bundle))
    else:
        _use_bundled_libraries(_bundle)
    _use_font_config(_bundle)

from stoetzms_pdf.cli import main  # noqa: E402  (after the library setup above)

if __name__ == "__main__":
    sys.exit(main())
