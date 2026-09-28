"""LaTeX for Manim's MathTex/Tex: find it on every OS, probe the packages, print exact FIX lines.

LaTeX is optional: Text, shapes, graphs and planes render without it. Only equations need
`latex` + `dvisvgm`. showtime never installs TeX itself (it needs admin rights and is large);
doctor, `showtime manim check` and a failing render print the per-OS command instead.

TeX is often missing from PATH in apps started from a GUI (the install adds it to shell profiles
only), so the usual install folders are searched too and the one found is put first on the render's
PATH.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from .. import platform as plat

# TeX Live package -> a file it provides (probed with kpsewhich). What Manim Community's default
# template loads, plus xcolor for the colour-coded equations. There is no `ms` package in TeX Live
# 2026: `everysel` (its old part) is its own package.
PACKAGES = {
    "standalone": "standalone.cls", "preview": "preview.sty", "doublestroke": "dsfont.sty",
    "relsize": "relsize.sty", "fundus-calligra": "calligra.sty", "wasysym": "wasysym.sty",
    "physics": "physics.sty", "rsfs": "rsfs10.tfm", "wasy": "wasy10.tfm", "cm-super": "type1ec.sty",
    "jknapltx": "mathrsfs.sty", "mathastext": "mathastext.sty", "microtype": "microtype.sty",
    "setspace": "setspace.sty", "xcolor": "xcolor.sty", "everysel": "everysel.sty",
    "ragged2e": "ragged2e.sty", "babel-english": "english.ldf",
}
TLMGR_LIST = ("standalone preview doublestroke relsize fundus-calligra wasysym physics dvisvgm rsfs wasy cm-super "
              "jknapltx mathastext microtype setspace xcolor everysel ragged2e babel-english")


def candidate_dirs() -> List[Path]:
    """Usual TeX bin folders for this OS (newest TeX Live year first)."""
    out: List[Path] = []
    osn = plat.os_name()
    if osn == "mac":
        out.append(Path("/Library/TeX/texbin"))
        out += sorted(Path("/usr/local/texlive").glob("*/bin/universal-darwin"), reverse=True)
    elif osn == "linux":
        for arch in ("x86_64-linux", "aarch64-linux"):
            out += sorted(Path("/usr/local/texlive").glob("*/bin/%s" % arch), reverse=True)
        out.append(Path("/usr/bin"))
    else:
        for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles"), os.environ.get("APPDATA")):
            if base:
                out.append(Path(base) / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64")
                out.append(Path(base) / "MiKTeX" / "miktex" / "bin" / "x64")
        out += sorted(Path("C:/texlive").glob("*/bin/windows"), reverse=True)
        out += sorted(Path("C:/texlive").glob("*/bin/win64"), reverse=True)
    return out


def _find(name: str) -> Optional[str]:
    exe = shutil.which(name)
    if exe:
        return exe
    for d in candidate_dirs():
        for cand in (d / plat.exe(name), d / name):
            if cand.is_file():
                return str(cand)
    return None


def find() -> Dict[str, object]:
    """{ok, latex, dvisvgm, bin_dir, distribution}. SHOWTIME_MANIM_FAKE_NO_TEX=1 pretends none exists (tests)."""
    if os.environ.get("SHOWTIME_MANIM_FAKE_NO_TEX") == "1":
        return {"ok": False, "latex": None, "dvisvgm": None, "bin_dir": None, "distribution": None}
    latex = _find("latex")
    dvisvgm = _find("dvisvgm")
    bin_dir = str(Path(latex).parent) if latex else None
    dist = None
    if latex:
        low = latex.lower()
        dist = "MiKTeX" if "miktex" in low else "TeX Live"
    return {"ok": bool(latex and dvisvgm), "latex": latex, "dvisvgm": dvisvgm, "bin_dir": bin_dir,
            "distribution": dist}


def missing_packages(info: Optional[Dict[str, object]] = None, timeout: float = 30) -> Optional[List[str]]:
    """TeX packages whose files kpsewhich cannot find (None when it cannot be asked; MiKTeX installs on demand)."""
    info = info or find()
    if not info.get("ok"):
        return None
    if info.get("distribution") == "MiKTeX":
        return []
    kpse = _find("kpsewhich")
    if not kpse:
        return None
    files = list(PACKAGES.values())
    try:
        cp = subprocess.run([kpse] + files, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    found = {Path(line.strip()).name for line in cp.stdout.splitlines() if line.strip()}
    return [pkg for pkg, f in PACKAGES.items() if f not in found]


def fix_lines(os_name: Optional[str] = None, missing: Optional[List[str]] = None) -> List[str]:
    """The exact commands that give this OS a working LaTeX for Manim."""
    osn = os_name or plat.os_name()
    pk = " ".join(missing) if missing else TLMGR_LIST
    if osn == "mac":
        return ["brew install --cask basictex   (BasicTeX 2026, about 100 MB; or the BasicTeX pkg from tug.org)",
                "open a new terminal, then: sudo tlmgr update --self && sudo tlmgr install " + pk]
    if osn == "windows":
        return ["winget install MiKTeX.MiKTeX   (or the installer from miktex.org)",
                "initexmf --set-config-value=[MPM]AutoInstall=1   (missing packages then install on first use; "
                "the first equation render can take a few minutes)"]
    return ["TeX Live 2026 (scheme-basic, https://tug.org/texlive/) then: sudo tlmgr install " + pk,
            "or distro packages: Debian/Ubuntu `sudo apt install texlive texlive-latex-extra texlive-fonts-extra "
            "texlive-science cm-super dvisvgm`; Fedora `sudo dnf install texlive-scheme-basic texlive-standalone "
            "texlive-preview texlive-physics texlive-doublestroke texlive-relsize texlive-dvisvgm texlive-cm-super`; "
            "Arch `sudo pacman -S texlive-basic texlive-latexextra texlive-fontsextra texlive-science`"]


def fix_text(os_name: Optional[str] = None, missing: Optional[List[str]] = None) -> str:
    return " ; ".join(fix_lines(os_name, missing))


def cairo_fix_lines(os_name: Optional[str] = None) -> List[str]:
    """Build dependencies for Manim Community's pycairo/manimpango (macOS and Linux build from source)."""
    osn = os_name or plat.os_name()
    if osn == "mac":
        return ["brew install cairo pango pkg-config"]
    if osn == "windows":
        return ["pycairo and manimpango ship wheels for Windows; if pip still builds them, install the "
                "Microsoft C++ Build Tools"]
    return ["Debian/Ubuntu: sudo apt install libcairo2-dev libpango1.0-dev pkg-config python3-dev",
            "Fedora: sudo dnf install cairo-devel pango-devel pkgconf-pkg-config python3-devel",
            "Arch: sudo pacman -S cairo pango pkgconf"]


TEX_USE_RE = re.compile(r"\b(MathTex|Tex|SingleStringMathTex|eq|equation_walkthrough|Matrix|IntegerMatrix|"
                        r"DecimalMatrix|MobjectMatrix|BulletedList|Title|DecimalNumber|Integer|Variable|"
                        r"ChangeDecimalToValue)\s*\(")
AXES_LABEL_RE = re.compile(r"\.(get_axis_labels|get_graph_label|add_coordinates)\s*\(|include_numbers\s*=\s*True|"
                           r"plane_transform\s*\(")


def uses_tex(source: str) -> bool:
    """True when a scene file will compile LaTeX (equations, matrices, numbered axes...)."""
    code = re.sub(r"#.*", "", source)
    return bool(TEX_USE_RE.search(code) or AXES_LABEL_RE.search(code))


if __name__ == "__main__":  # pragma: no cover - manual probe
    i = find()
    print(i)
    print("missing:", missing_packages(i))
    print("\n".join(fix_lines()))
    sys.exit(0)
