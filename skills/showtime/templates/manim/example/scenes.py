"""Odd numbers build squares: a narrated math explainer in two scenes.

Beat sheet (one narration line per beat; ids match the `## id` headings in narration.md, and no id is
a word the voice says, so at("square") can only mean the word):

  scene    beat     on screen
  Sum      hook     t=0: the question, large. "odd": it steps up into a heading. Each spoken number
                    drops into the sum, large, while a running total ticks up; "Sixteen" sends the total
                    into the answer and boxes it
  Squares  tiling   the sum moves up out of the way. "tiles": the 1 drops down and becomes one tile;
                    "three", "five": copies of the term fly down and become the tiles of its band, the
                    band wrapping the square before it; each band's colour is its term's colour
           closing  "seven" closes the square; "every": the bands ripple in turn; "four": braces read
                    4 and 4; "four" again: 16 becomes 4^2 and the square is outlined
           rule     the sum becomes the general rule, a label for the picture already on screen;
                    "squared": the picture grows a little and the outline thickens

Motion: something visibly changes every 1-2 s (qa reads a still stretch of 2.5 s as a hold), and the
changes are big enough to see: whole numbers flying, tiles landing, a heading moving; a thin line or
an Indicate on one small symbol alone is too little.

Colours: manim.json "colors" binds each odd number to one hue (term and band alike) and the square
to the emphasis colour, for the whole video. Timing: every reveal waits for its word (self.at),
so a new voice take re-times the video on the next render. Sound: the voice, plus the composed bed
in audio/mix.json ducked under it.
"""
from st_manim import *

TILE = 1.0          # side of one tile (frame units; the short side of the frame is 8)
BIG = 1.3           # the sum's size in the hook, relative to its size as the heading in Squares


def tile_grid(n: int, size: float = TILE) -> VGroup:
    """n bands of tiles: band k (1-based) holds the 2k-1 tiles whose row or column index is k-1."""
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


def square_picture() -> VGroup:
    """The tile square with its braces and "4" labels, fitted (with room to grow 6 %) under the sum.
    Returns VGroup(bands, brace_below, brace_right, label_below, label_right)."""
    bands = tile_grid(4)
    b1 = Brace(bands, DOWN, buff=0.12, color=T.muted)
    b2 = Brace(bands, RIGHT, buff=0.12, color=T.muted)
    l1 = label("4", size=48).next_to(b1, DOWN, buff=0.12)
    l2 = label("4", size=48).next_to(b2, RIGHT, buff=0.12)
    pic = VGroup(bands, b1, b2, l1, l2)
    x0, y0, x1, y1 = region("main")
    pic.scale(min(0.8 * (x1 - x0) / pic.width, 0.9 * (y1 - y0) / pic.height))   # fill it in any aspect (room
    # for the square to sit on the centre line and to grow 6 % at the end)
    pic.move_to(region_center("main"))
    pic.shift((region_center("main")[0] - bands.get_center()[0]) * RIGHT)   # the square itself on the centre line
    return pic


def the_sum(big: bool = False) -> Eq:
    """The sum as the heading (Squares), or large in the middle (the hook)."""
    s = eq(r"1 + 3 + 5 + 7 = 16")
    if big:
        s.scale(BIG)
        fit_width(s, 0.9)
        s.move_to(region_center("middle") + 0.35 * UP)
    else:
        place(s, "top")
    return s


def drop(term: VMobject) -> Animation:
    """A spoken number arrives large just above its slot and drops into the sum (a big, visible change
    on each word; a term that only fades in at the sum's size is a small one). Above, not below: the
    running total sits under the sum."""
    big = term.copy().scale(1.7).move_to(term.get_center() + 0.8 * UP)
    return ReplacementTransform(big, term)


class Sum(ShowScene):
    def construct(self):
        self.beat("hook")
        q = title("Add the odd numbers")
        fit_width(q, 0.9)
        q.move_to(region_center("middle"))
        self.add(q)                                   # the hook is on screen at t=0 (the voice starts a
        #                                               moment later: the kit holds that lead-in on it)
        self.play(q.animate.scale(1.08), run_time=0.8)
        heading = q.copy().scale(0.62 / 1.08).set_fill(T.muted)
        heading.move_to(region_center("top"))
        self.at("odd")                                # the question steps up into a heading
        self.play(Transform(q, heading), run_time=0.7)

        s = the_sum(big=True)
        total = counter(0, font_size=96)
        running = VGroup(label("running total", color=T.muted), total).arrange(RIGHT, buff=0.35)
        align_baseline(running[0], total)             # words and number on one baseline (see manim.md)
        running.next_to(s, DOWN, buff=0.8)
        self.at("one")
        self.play(drop(s["1"]), FadeIn(running, shift=0.2 * UP), count_to(total, 1), run_time=0.6)
        acc = 1
        for word, term in (("three", "3"), ("five", "5"), ("seven", "7")):
            self.at(word)
            acc += int(term)
            self.play(FadeIn(s.part("+", int(term) // 2), shift=0.15 * RIGHT), drop(s[term]),
                      count_to(total, acc), run_time=0.6)
        self.at("sixteen")                            # the total becomes the answer; the question leaves
        self.play(Write(s["="]), ReplacementTransform(total.copy().clear_updaters(), s["16"]),
                  FadeOut(q, shift=0.3 * UP), run_time=0.7)
        self.play(Create(highlight(s["16"])), FadeOut(running), run_time=0.4)


class Squares(ShowScene):
    def lay(self, term: VMobject, band: VGroup, run_time: float = 0.9) -> None:
        """Symbol to picture: copies of the term fly down and become the band's tiles (the term stays)."""
        self.play(LaggedStart(*[ReplacementTransform(term.copy(), t) for t in band], lag_ratio=0.1),
                  Indicate(term, color=term.get_color(), scale_factor=1.25), run_time=run_time)

    def construct(self):
        self.beat("tiling")
        s = the_sum(big=True)
        box = highlight(s["16"])
        self.add(s, box)                              # opens on the last frame of Sum
        head = the_sum()
        self.play(s.animate.scale(head.width / s.width).move_to(head), FadeOut(box), run_time=0.8)
        pic = square_picture()
        bands, b1, b2, l1, l2 = pic
        self.at("tiles")                              # "...out as tiles": the 1 becomes the first tile
        self.lay(s["1"], bands[0], run_time=0.6)
        for word, k in (("three", 1), ("five", 2)):
            self.at(word)
            self.lay(s[str(2 * k + 1)], bands[k])

        self.beat("closing")
        self.at("seven")
        self.lay(s["7"], bands[3])
        self.at("every")                              # ripple: each band in turn, as "every band" is said
        self.play(LaggedStart(*[Indicate(b, color=b[0].get_fill_color(), scale_factor=1.08) for b in bands],
                              lag_ratio=0.3), run_time=1.5)
        self.at("four")                               # "Four odd numbers": box the four terms; four by four
        terms = highlight(VGroup(*s.submobjects[:7]))
        self.play(Create(terms), GrowFromCenter(b1), GrowFromCenter(b2), FadeIn(l1, shift=0.3 * UP),
                  FadeIn(l2, shift=0.3 * LEFT), run_time=0.8)
        sq = eq(r"1 + 3 + 5 + 7 = 4^2").move_to(s)
        self.at("four#2")
        outline = SurroundingRectangle(bands, buff=0.06, color=T.emph, stroke_width=5)
        self.play(morph(s, sq, key_map={"16": "4^2"}), FadeOut(terms), Create(outline), run_time=1.1)
        self.mark("poster")

        self.beat("rule")
        rule = eq(r"1 + 3 + \dots + (2n-1) = n^2", isolate=["(2n-1)"]).move_to(sq)
        fit_width(rule, 0.9)
        self.at("n")
        self.play(morph(sq, rule), run_time=1.2)
        self.at("squared")
        picture = VGroup(pic, outline)
        self.play(Indicate(rule["n^2"], color=T.emph, scale_factor=1.3), outline.animate.set_stroke(width=8),
                  picture.animate.scale(1.06), run_time=1.2)
        self.hold(2.0)                                # end on the image
