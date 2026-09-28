"""Frame, safe area and regions that work in 16:9, 9:16, 1:1 and 4:5.

The short side of the frame is always 8 units (set when the kit is imported, from the pixel size),
so a 9:16 render is 8 x 14.22 units and nothing shrinks. Place things by region, not by absolute
coordinates, and the same scene re-lays itself out for a vertical cut:

    place(eq_mob, "top")            # scaled down (never up) to fit, centred in the region
    place(diagram, "left_third")    # on 9:16 the thirds become the upper and lower halves
    if is_portrait(): ...           # branch when a layout really differs
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
from manim import Mobject, config

Box = Tuple[float, float, float, float]   # x0, y0, x1, y1 in scene units

# safe margins in units (short side = 8): portrait leaves room for platform buttons and captions
MARGINS = {"landscape": (0.45, 0.45, 0.45, 0.45), "portrait": (0.5, 0.5, 1.3, 2.1)}   # left, right, top, bottom


def apply_frame() -> Tuple[float, float]:
    """Set config.frame_width/height from the pixel size (short side = 8 units). Returns them."""
    w, h = int(config.pixel_width), int(config.pixel_height)
    if w >= h:
        fw, fh = 8.0 * w / h, 8.0
    else:
        fw, fh = 8.0, 8.0 * h / w
    config.frame_width = fw
    config.frame_height = fh
    return fw, fh


def frame_size() -> Tuple[float, float]:
    return float(config.frame_width), float(config.frame_height)


def is_portrait() -> bool:
    w, h = frame_size()
    return h > w * 1.05


def margins() -> Tuple[float, float, float, float]:
    return MARGINS["portrait" if is_portrait() else "landscape"]


def safe_box() -> Box:
    w, h = frame_size()
    l, r, t, b = margins()
    return (-w / 2 + l, -h / 2 + b, w / 2 - r, h / 2 - t)


def regions() -> Dict[str, Box]:
    x0, y0, x1, y1 = safe_box()
    W, H = x1 - x0, y1 - y0
    out = {
        "full": (x0, y0, x1, y1),
        "center": (x0 + W * 0.1, y0 + H * 0.2, x1 - W * 0.1, y1 - H * 0.2),
        "top": (x0, y1 - H * 0.28, x1, y1),
        "bottom": (x0, y0, x1, y0 + H * 0.28),
        "upper": (x0, y0 + H * 0.5, x1, y1),
        "lower": (x0, y0, x1, y0 + H * 0.5),
        "middle": (x0, y0 + H * 0.28, x1, y1 - H * 0.28),
        "main": (x0, y0, x1, y1 - H * 0.24),          # everything under a title band
    }
    if is_portrait():
        out.update({"left": out["upper"], "right": out["lower"], "left_third": out["upper"],
                    "right_third": out["lower"], "left_two_thirds": out["upper"]})
    else:
        out.update({"left": (x0, y0, x0 + W * 0.5, y1), "right": (x0 + W * 0.5, y0, x1, y1),
                    "left_third": (x0, y0, x0 + W / 3, y1), "right_third": (x1 - W / 3, y0, x1, y1),
                    "left_two_thirds": (x0, y0, x0 + W * 2 / 3, y1)})
    return out


def region(name: str) -> Box:
    r = regions()
    if name not in r:
        raise KeyError("unknown region %r; use one of: %s" % (name, ", ".join(sorted(r))))
    return r[name]


def region_center(name: str) -> np.ndarray:
    x0, y0, x1, y1 = region(name)
    return np.array([(x0 + x1) / 2, (y0 + y1) / 2, 0.0])


def fit_in(mob: Mobject, box: Box, fill: float = 1.0) -> Mobject:
    """Scale `mob` down (never up) so it fits `fill` of the box."""
    x0, y0, x1, y1 = box
    bw, bh = (x1 - x0) * fill, (y1 - y0) * fill
    w, h = max(mob.width, 1e-6), max(mob.height, 1e-6)
    k = min(bw / w, bh / h, 1.0)
    if k < 1.0:
        mob.scale(k)
    return mob


def place(mob: Mobject, where: str = "center", fill: float = 1.0, align: str = "center") -> Mobject:
    """Fit `mob` into a region and put it there. align: center | top | bottom | left | right."""
    box = region(where)
    fit_in(mob, box, fill)
    x0, y0, x1, y1 = box
    c = np.array([(x0 + x1) / 2, (y0 + y1) / 2, 0.0])
    mob.move_to(c)
    if align == "top":
        mob.shift(np.array([0, y1 - mob.get_top()[1], 0]))
    elif align == "bottom":
        mob.shift(np.array([0, y0 - mob.get_bottom()[1], 0]))
    elif align == "left":
        mob.shift(np.array([x0 - mob.get_left()[0], 0, 0]))
    elif align == "right":
        mob.shift(np.array([x1 - mob.get_right()[0], 0, 0]))
    return mob


def fit_width(mob: Mobject, frac: float = 0.9) -> Mobject:
    """Scale down so `mob` uses at most `frac` of the safe width (and fits the safe height)."""
    return fit_in(mob, safe_box(), frac)


def outside_safe(mob: Mobject, tol: float = 0.05) -> bool:
    x0, y0, x1, y1 = safe_box()
    return bool(mob.get_left()[0] < x0 - tol or mob.get_right()[0] > x1 + tol or
                mob.get_bottom()[1] < y0 - tol or mob.get_top()[1] > y1 + tol)
