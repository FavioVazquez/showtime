"""Odd numbers build squares: a narrated math explainer in two scenes.

Beat sheet (one narration line per beat; ids match the `## id` headings in narration.md):

  scene    beat    on screen
  Sum      hook    the sum is written term by term on each spoken number; a running total ticks up;
                   "Sixteen" boxes the answer
  Squares  tiles   one tile, then a band of three wraps it, then a band of five; each band's colour is
                   its term's colour, and a copy of the band flies into its term
           square  the band of seven closes the square; the bands ripple in turn; braces read 4 and 4;
                   the answer becomes 4^2
           rule    the sum becomes the general rule, a label for the picture already on screen

Colours: manim.json "colors" binds each odd number to one hue (term and band alike) and the square
to the emphasis colour, for the whole video. Timing: every reveal waits for its word (self.at),
so a new voice take re-times the video on the next render. Sound: the voice, plus the composed bed
in audio/mix.json ducked under it.
"""
from st_manim import *

TILE = 0.8


def tile_grid(n: int, size: float = TILE) -> VGroup:
    """n bands of tiles: band k (1-based) holds the 2k-1 tiles whose row or column index is k-1."""
    T = theme()
    bands = VGroup()
    for k in range(1, n + 1):
        band = VGroup()
        for i in range(k):
            for j in range(k):
                if max(i, j) != k - 1:
                    continue
                sq = Square(side_length=size * 0.9, stroke_width=0)
                sq.set_fill(T.var(str(2 * k - 1)) or T.hue(k), opacity=0.92)
                sq.move_to(np.array([(i + 0.5) * size, (j + 0.5) * size, 0.0]))
                band.add(sq)
        bands.add(band)
    return bands


def the_sum() -> Eq:
    s = eq(r"1 + 3 + 5 + 7 = 16")
    place(s, "top")
    return s


class Sum(ShowScene):
    def construct(self):
        self.beat("hook")
        s = the_sum()
        total = counter(0, font_size=40, color=T.muted)
        running = VGroup(note("running total"), total).arrange(RIGHT, buff=0.3)
        align_baseline(running[0], total)             # words and number on one baseline (see manim.md)
        running.next_to(s, DOWN, buff=0.9)
        q = callout("Add the odd numbers")
        q.move_to(region_center("middle"))
        self.add(q)                                   # the hook is on screen at t=0
        self.play(q.animate.scale(1.08), run_time=0.8)
        self.at("one")
        self.play(FadeOut(q), Write(s["1"]), FadeIn(running), count_to(total, 1), run_time=0.6)
        acc = 1
        for word, term in (("three", "3"), ("five", "5"), ("seven", "7")):
            self.at(word)
            acc += int(term)
            self.play(FadeIn(s.part("+", int(term) // 2), shift=0.1 * RIGHT), Write(s[term]),
                      count_to(total, acc), run_time=0.6)
        self.at("sixteen")
        self.play(Write(s["="]), ReplacementTransform(total.copy().clear_updaters(), s["16"]), run_time=0.7)
        box = highlight(s["16"])
        self.play(Create(box), FadeOut(running), run_time=0.4)
        self.play(FadeOut(box), run_time=0.3)


class Squares(ShowScene):
    def fly(self, band: VGroup, term: VMobject) -> None:
        """Picture to symbol: a copy of the band morphs into its term (the term stays put)."""
        ghost_term = term.copy()
        self.play(TransformFromCopy(band, ghost_term), Indicate(term, color=term.get_color(), scale_factor=1.15),
                  run_time=0.9)
        self.remove(ghost_term)

    def construct(self):
        self.beat("tiles")
        s = the_sum()
        self.add(s)                                   # opens on the last frame of Sum
        bands = tile_grid(4)
        bands.move_to(region_center("middle") + 0.25 * DOWN)
        self.play(FadeIn(bands[0], scale=0.6), run_time=0.6)
        self.fly(bands[0], s["1"])
        for word, k in (("three", 1), ("five", 2)):
            self.at(word)
            self.play(LaggedStart(*[FadeIn(t, scale=0.6) for t in bands[k]], lag_ratio=0.12), run_time=0.9)
            self.fly(bands[k], s[str(2 * k + 1)])

        self.beat("square")
        self.at("seven")
        self.play(LaggedStart(*[FadeIn(t, scale=0.6) for t in bands[3]], lag_ratio=0.1), run_time=0.9)
        self.fly(bands[3], s["7"])
        self.at("every")                              # ripple: each band in turn, as "every band" is said
        self.play(LaggedStart(*[Indicate(b, color=b[0].get_fill_color(), scale_factor=1.06) for b in bands],
                              lag_ratio=0.3), run_time=1.5)
        self.at("four")
        b1 = Brace(bands, DOWN, buff=0.12, color=T.muted)
        b2 = Brace(bands, RIGHT, buff=0.12, color=T.muted)
        l1 = label("4").next_to(b1, DOWN, buff=0.12)
        l2 = label("4").next_to(b2, RIGHT, buff=0.12)
        self.play(GrowFromCenter(b1), GrowFromCenter(b2), FadeIn(l1), FadeIn(l2), run_time=0.8)
        sq = eq(r"1 + 3 + 5 + 7 = 4^2").move_to(s)
        self.at("four#2")
        self.play(morph(s, sq, key_map={"16": "4^2"}), run_time=1.1)
        outline = SurroundingRectangle(bands, buff=0.06, color=T.emph, stroke_width=4)
        self.play(Create(outline), run_time=0.5)
        self.mark("poster")

        self.beat("rule")
        rule = eq(r"1 + 3 + \dots + (2n-1) = n^2", isolate=["(2n-1)"]).move_to(sq)
        fit_width(rule, 0.9)
        self.at("n")
        self.play(morph(sq, rule), run_time=1.2)
        self.at("squared")
        self.play(Indicate(rule["n^2"], color=T.emph), outline.animate.set_stroke(width=7), run_time=0.7)
        self.play(VGroup(bands, outline, b1, b2, l1, l2).animate.scale(1.04), run_time=1.2)
        self.hold(1.8)                                # end on the image
