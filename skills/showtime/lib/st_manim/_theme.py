"""The theme object `T`: brand colours, semantic hues, fonts registered from files, stroke tiers."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import _settings

WEIGHTS = {100: "THIN", 200: "ULTRALIGHT", 300: "LIGHT", 400: "NORMAL", 500: "MEDIUM", 600: "SEMIBOLD",
           700: "BOLD", 800: "ULTRABOLD", 900: "HEAVY"}


class Theme:
    """Resolved once per render. Colours are hex strings.

        T.bg T.surface T.ink T.muted T.emph T.grid T.ghost   roles
        T.hue(1) .. T.hue(n), T.hues                         semantic hues (text-safe, never the emphasis colour)
        T.var("x")                                           the one colour of concept "x" (manim.json "colors")
        T.display, T.body                                    font family names (registered from files)
        T.stroke["data"|"construct"|"grid"|"back"]           stroke widths (px at 1080p)
    """

    def __init__(self, data: Dict[str, Any], colors: Optional[Dict[str, str]] = None) -> None:
        self.data = data
        self.bg: str = data["bg"]
        self.surface: str = data.get("surface") or data["bg"]
        self.ink: str = data["ink"]
        self.muted: str = data.get("muted") or data["ink"]
        self.emph: str = data.get("emph") or data["ink"]
        self.grid: str = data.get("grid") or self.muted
        self.ghost: str = data.get("ghost") or self.muted
        self.dark: bool = bool(data.get("dark", True))
        self.hues: List[str] = list(data.get("hues") or [self.ink])
        self.notes: List[str] = list(data.get("notes") or [])
        self.stroke = {"data": 4.5, "construct": 2.0, "grid": 1.2, "back": 5.0}
        self._colors = dict(colors or {})
        fonts = data.get("fonts") or {}
        self.display = (fonts.get("display") or {}).get("family") or "sans-serif"
        self.body = (fonts.get("body") or {}).get("family") or "sans-serif"
        self.display_weight = WEIGHTS.get(_round_weight((fonts.get("display") or {}).get("weight", 800)), "BOLD")
        self.body_weight = WEIGHTS.get(_round_weight((fonts.get("body") or {}).get("weight", 400)), "NORMAL")
        self.font_files = [f.get("file") for f in fonts.values() if isinstance(f, dict) and f.get("file")]

    def hue(self, i: int) -> str:
        """Semantic hue i (1-based, wraps around)."""
        return self.hues[(int(i) - 1) % len(self.hues)]

    def color(self, value: Any) -> Optional[str]:
        """'hue2', a role name ('emph', 'ink', 'muted' ...) or a hex -> hex."""
        from st.manim_run.palette import resolve_color
        return resolve_color(value, self.data)

    def var(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """The colour bound to concept `key` in manim.json "colors" (or `default`)."""
        v = self._colors.get(key)
        return self.color(v) if v else default

    @property
    def colors(self) -> Dict[str, str]:
        return {k: self.color(v) or self.ink for k, v in self._colors.items()}

    def __repr__(self) -> str:  # pragma: no cover
        return "Theme(bg=%s ink=%s emph=%s hues=%s fonts=%s/%s)" % (self.bg, self.ink, self.emph, self.hues,
                                                                     self.display, self.body)


def _round_weight(w: Any) -> int:
    try:
        return min(WEIGHTS, key=lambda k: abs(k - int(w)))
    except (TypeError, ValueError):
        return 400


_T: Optional[Theme] = None


def theme() -> Theme:
    global _T
    if _T is None:
        _T = Theme(_settings.theme_dict(), _settings.colors())
        _register_fonts(_T)
    return _T


def _register_fonts(t: Theme) -> None:
    """Fonts as files: register each theme font with Pango for the whole render (every OS)."""
    try:
        import manimpango
    except ImportError:  # pragma: no cover - manim always brings it
        return
    for f in t.font_files:
        try:
            manimpango.register_font(str(f))
        except Exception as e:  # noqa: BLE001 - a bad file must not stop the render
            t.notes.append("could not register font %s: %s" % (f, e))
