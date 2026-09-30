#!/usr/bin/env python3
"""Chart labels stay put while the data changes (headless Chrome through the stage host).

Round-4 benchmark videos showed every value label blink off when a state added bars and come back
when they settled, and a line's end label that read a different point than the one it sat on. These
tests sample frames around an item entering and assert, with illustrative sample values:
  - bars: every label lit before the new items arrive stays lit on every sampled frame, keeps its
    text (count: false shows only real values) and stays on its bar; items not in a state (a missing
    label or null) draw no bar and no "0" label, then grow in and light their own labels
  - hbar: the rows already ranked keep their value labels through a state that adds a row
  - line: a state that only swaps the title does not mark the chart as moving, the end label stays
    lit through it and always reads the point under the drawn tip; the callout names its year
  - `showtime check` warns (chart_labels_hidden) about project CSS that hides labels while charts move
Skipped with --fast (needs a browser). usage: python tests/test_chart_constancy.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())

# illustrative sample values (not real measurements)
VALUES = [-0.11, -0.18, -0.13, -0.20, -0.24, -0.27, -0.27, -0.19, -0.08, 0.08, -0.02, -0.01, 0.06, 0.26, 0.39, 0.57, 0.80, 1.05]
NAMES = [str(1850 + 10 * i) for i in range(18)]
FIRST = 11                     # items in the first state
STATE2_AT = 2.2                # the state that adds the other 7 (chart local time; the chart starts at 0.15)
CHART_AT = 0.15

LINE_LABELS = [str(1966 + i) for i in range(60)]
# a noisy flat start, then a climb (the noise makes the path longer than its share of the x axis)
LINE_VALUES = [round(320 + (8 if i % 2 else -8) * (1 if i < 30 else 0.1) + max(0, i - 30) * 3.1, 1) for i in range(60)]


def node_exe():
    return ENV.get("SHOWTIME_NODE") or plat.which("node") or shutil.which("node") or "node"


def showtime(*args, check=True, timeout=600):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                    cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def page(opts, typ="bar", dur=5, css=""):
    return ("""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>chart constancy</title>
<script src="/_st/stage.js"></script><script>ST.config({"width": 1920, "height": 1080, "fps": 30, "duration": @DUR@});</script>
<link rel="stylesheet" href="/_st/themes/editorial.css">
<script type="module" src="/_st/components/index.js"></script>
<style>.scene{padding:7cqh 7cqw;background:var(--bg)} .chart{position:absolute;inset:7cqh 7cqw 10cqh} @CSS@</style></head>
<body><div class="stage"><section class="scene" data-start="0" data-dur="@DUR@">
<div class="chart" id="ch" data-st="chart" data-type="@TYPE@" data-at="@AT@" data-options='@OPTS@'></div>
</section></div></body></html>""".replace("@DUR@", str(dur)).replace("@TYPE@", typ).replace("@AT@", str(CHART_AT))
            .replace("@CSS@", css).replace("@OPTS@", json.dumps(opts)))


def bar_states(null_style):
    first = [{"label": n, "value": v} for n, v in zip(NAMES[:FIRST], VALUES[:FIRST])]
    if null_style:   # the later items listed with null: "not in this state yet"
        first += [{"label": n, "value": None} for n in NAMES[FIRST:]]
    return [{"at": 0, "title": "Sample data: the first eleven", "data": first},
            {"at": STATE2_AT, "title": "Sample data: all eighteen", "data": [{"label": n, "value": v} for n, v in zip(NAMES, VALUES)]}]


BAR = {"prefix": "+", "decimals": 2, "count": False}
RANK_FIRST = [{"label": "A", "value": 90}, {"label": "B", "value": 70}, {"label": "C", "value": 50}, {"label": "D", "value": 30}, {"label": "E", "value": 10}]
LINE = {"decimals": 1, "count": False, "dots": False, "draw": 3,
        "annotate": {"label": "2015", "text": "first year above 400"},
        "states": [{"at": 0, "title": "Sample data: a climbing line", "data": {"labels": LINE_LABELS, "series": [{"name": "s", "values": LINE_VALUES}]}},
                   {"at": 3.6, "title": "Sample data: the same line, a new title", "data": {"labels": LINE_LABELS, "series": [{"name": "s", "values": LINE_VALUES}]}}]}
HIDE_CSS = "#ch[data-st-moving] .st-chart-val { opacity: 0 !important; }"
PAGES = {
    "grow.html": page(dict(BAR, states=bar_states(False))),
    "grow-null.html": page(dict(BAR, states=bar_states(True))),
    "rank.html": page({"count": False, "states": [{"at": 0, "data": RANK_FIRST},
                                                  {"at": STATE2_AT, "data": RANK_FIRST + [{"label": "N", "value": 80}]}]}, typ="hbar"),
    # D and E leave while N and M join: five rows at a time, sized for five, not for the seven names
    "replace.html": page({"count": False, "states": [{"at": 0, "data": RANK_FIRST},
                                                     {"at": STATE2_AT, "data": RANK_FIRST[:3] + [{"label": "N", "value": 60}, {"label": "M", "value": 40}]}]}, typ="hbar"),
    "static5.html": page({"count": False, "data": RANK_FIRST}, typ="hbar"),
    # a callout on the top row and a reference line whose label sits above the rows
    "rank-ref.html": page({"count": False, "data": RANK_FIRST, "ref": {"value": 60, "label": "A sample reference line at sixty"},
                           "annotate": {"label": "A", "text": "the top sample value"}}, typ="hbar"),
    "line.html": page(LINE, typ="line", dur=6),
    "line-value.html": page(dict(LINE, annotate={"label": "2015", "text": "{value} in {label}"}), typ="line", dur=6),
    # a callout near the end of a climbing line, wide enough to reach the end label
    "line-end.html": page(dict(LINE, annotate={"label": "2021", "text": "the first sample year above the line we drew"}), typ="line", dur=6),
    "hide.html": page(dict(BAR, states=bar_states(False)), css=HIDE_CSS),
}

PROBE = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const skill = process.argv[2], dir = process.argv[3], plan = JSON.parse(process.argv[4]);
const imp = (p) => import(pathToFileURL(path.join(skill, 'scripts', p)).href);
const { startServer } = await imp('server.mjs');
const { openBrowser, openStage } = await imp('lib/stagehost.mjs');
const server = await startServer({ root: dir, port: 0 });
const b = await openBrowser({ gpu: 'auto' });
const R = {};
const grab = () => {
  const ch = document.querySelector('#ch');
  // the opacity a viewer sees: the element's own times every ancestor's up to the chart
  const eff = (e) => { let o = 1; for (let n = e; n && n !== ch.parentElement; n = n.parentElement) o *= parseFloat(getComputedStyle(n).opacity); return o; };
  const box = (e) => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; };
  const pf = parseFloat(getComputedStyle(ch.querySelector('.st-chart-plot')).fontSize);
  return {
    moving: ch.hasAttribute('data-st-moving'),
    fs: pf,
    vals: [...ch.querySelectorAll('.st-chart-val')].map((e) => ({ t: e.textContent, op: eff(e), box: box(e) })),
    bars: [...ch.querySelectorAll('.st-chart-bar')].map((e) => ({ box: box(e), h: e.getBBox().height, w: e.getBBox().width })),
    names: [...ch.querySelectorAll('.st-chart-yl')].map((e) => ({ t: e.textContent, op: eff(e) })),
    xl: [...ch.querySelectorAll('.st-chart-xl')].map((e) => ({ t: e.textContent, x: parseFloat(e.getAttribute('x')) })),
    end: [...ch.querySelectorAll('.st-chart-endlabel')].map((e) => ({ t: e.textContent, op: eff(e), x: parseFloat(e.getAttribute('x')), box: box(e) })),
    callout: (() => { const c = ch.querySelector('.st-chart-callout'); return c ? { t: c.textContent, op: parseFloat(getComputedStyle(c).opacity), box: box(c) } : null; })(),
    ref: (() => { const r = ch.querySelector('.st-chart-ref text'); return r ? { t: r.textContent, op: eff(r), box: box(r) } : null; })(),
  };
};
try {
  for (const [name, times] of Object.entries(plan)) {
    const s = await openStage(b.browser, { url: server.url, page: name, config: {} });
    R[name] = {};
    for (const t of times) { await s.seek(t); R[name][t.toFixed(2)] = await s.page.evaluate(grab); }
    await s.close();
  }
} finally { await b.browser.close(); await server.close(); }
console.log(JSON.stringify(R));
"""

GROW_T = [1.8] + [round(STATE2_AT + CHART_AT + 0.1 * i, 2) for i in range(0, 22)] + [4.9]
LINE_T = [round(0.6 + 0.2 * i, 2) for i in range(13)] + [3.5, 3.9, 4.2, 4.5, 4.8, 5.1, 5.6]
PLAN = {"grow.html": GROW_T, "grow-null.html": GROW_T, "rank.html": GROW_T, "hide.html": [1.8], "replace.html": [1.8, 4.9], "static5.html": [1.8], "rank-ref.html": [4.9],
        "line.html": LINE_T, "line-value.html": [5.6], "line-end.html": [5.6]}


def key(t):
    return "%.2f" % t


def num(s):
    return float(s.replace("−", "-").replace("+", "").replace(",", "").strip())


@unittest.skipIf(FAST, "needs a browser")
class ChartConstancy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-chartconst-"))
        cls.proj = cls.tmp / "proj"
        cls.proj.mkdir()
        (cls.proj / "showtime.json").write_text(json.dumps({"width": 1920, "height": 1080, "fps": 30, "duration": 5}), encoding="utf-8")
        for name, html in PAGES.items():
            (cls.proj / name).write_text(html, encoding="utf-8")
        probe = cls.tmp / "probe.mjs"
        probe.write_text(PROBE, encoding="utf-8")
        cp = subprocess.run([node_exe(), str(probe), str(SKILL), str(cls.proj), json.dumps(PLAN)], env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=400)
        if cp.returncode != 0:
            raise AssertionError("probe failed:\n%s\n%s" % (cp.stdout[-3000:], cp.stderr[-3000:]))
        cls.R = json.loads(cp.stdout.strip().splitlines()[-1])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def check_grow(self, name):
        frames = self.R[name]
        before = frames[key(1.8)]
        lit = [i for i, v in enumerate(before["vals"]) if v["op"] > 0.95]
        self.assertGreaterEqual(len(lit), 8, "most of the first state's labels show: %s" % before["vals"])
        self.assertTrue(all(i < FIRST for i in lit), "only items in the first state are labelled")
        for i in range(FIRST, 18):
            self.assertLess(before["vals"][i]["op"], 0.02, "%s is not in the first state: no label (%s)" % (NAMES[i], before["vals"][i]))
            self.assertLess(before["bars"][i]["h"], 0.5, "%s is not in the first state: no bar" % NAMES[i])
        # a label lit before the items arrive stays lit on every frame; only when the grown chart is
        # really too crowded for it (the auto plan, `labels_crowded` otherwise) may it fade out, once,
        # and then it stays out: never off and back on
        ops = {i: [frames[key(t)]["vals"][i]["op"] for t in GROW_T] for i in lit}
        faded = [i for i in lit if min(ops[i]) <= 0.95]
        for i in faded:
            low = next(k for k, o in enumerate(ops[i]) if o <= 0.95)
            self.assertLess(ops[i][-1], 0.05, "%s's label blinked: %s" % (NAMES[i], ["%.2f" % o for o in ops[i]]))
            self.assertTrue(all(b <= a + 1e-3 for a, b in zip(ops[i][low:], ops[i][low + 1:])), "%s's label came back: %s" % (NAMES[i], ops[i]))
        self.assertLessEqual(len(faded), 3, "at most a few labels give way to the added bars: %s" % [NAMES[i] for i in faded])
        for t in GROW_T[1:]:
            f = frames[key(t)]
            for i in lit:
                v, v0 = f["vals"][i], before["vals"][i]
                if i in faded:
                    continue
                self.assertGreater(v["op"], 0.95, "%s's label blinked (opacity %.2f) at %.2fs while items were added" % (NAMES[i], v["op"], t))
                self.assertEqual(v["t"], v0["t"], "%s's label changed its number at %.2fs" % (NAMES[i], t))
                cx, cx0 = (v["box"][0] + v["box"][2]) / 2, (v0["box"][0] + v0["box"][2]) / 2
                self.assertAlmostEqual(cx, cx0, delta=1.0, msg="%s's label left its bar" % NAMES[i])
                bar = f["bars"][i]["box"]
                # the label rides its bar: above a positive bar's top, below a negative bar's bottom
                if VALUES[i] >= 0:
                    self.assertLessEqual(v["box"][3], bar[1] + 1, "%s's label sits on its bar at %.2fs" % (NAMES[i], t))
                else:
                    self.assertGreaterEqual(v["box"][1], bar[3] - 1, "%s's label sits on its bar at %.2fs" % (NAMES[i], t))
            for i in range(FIRST, 18):
                v = f["vals"][i]
                if v["op"] > 0.02:   # an added item shows only its real value, never "0.00" or a count in progress
                    self.assertAlmostEqual(num(v["t"]), VALUES[i], places=2, msg="%s shows %s at %.2fs" % (NAMES[i], v["t"], t))
        after = frames[key(4.9)]
        new_lit = [i for i in range(FIRST, 18) if after["vals"][i]["op"] > 0.95]
        self.assertGreaterEqual(len(new_lit), 4, "the added items light their labels once they land: %s" % after["vals"][FIRST:])
        for i in range(FIRST, 18):
            self.assertGreater(after["bars"][i]["h"], 0.5, "%s grew in" % NAMES[i])

    def test_bars_added_by_a_state_leave_the_other_labels_lit(self):
        self.check_grow("grow.html")

    def test_null_means_not_yet_in_the_data(self):
        self.check_grow("grow-null.html")

    def test_ranked_rows_keep_their_labels_when_a_row_enters(self):
        frames = self.R["rank.html"]
        before = frames[key(1.8)]
        self.assertLess(before["names"][5]["op"], 0.02, "the row not in the first state is hidden: %s" % before["names"])
        self.assertLess(before["vals"][5]["op"], 0.02)
        for t in GROW_T[1:]:
            f = frames[key(t)]
            for i in range(5):
                self.assertGreater(f["vals"][i]["op"], 0.95, "row %s's label blinked at %.2fs" % (RANK_FIRST[i]["label"], t))
                self.assertEqual(f["vals"][i]["t"], before["vals"][i]["t"], "row %s's number changed at %.2fs" % (RANK_FIRST[i]["label"], t))
        after = frames[key(4.9)]
        self.assertGreater(after["names"][5]["op"], 0.95, "the added row shows once it lands")
        self.assertEqual(num(after["vals"][5]["t"]), 80)

    def test_rows_are_sized_for_the_largest_state(self):
        rep, static = self.R["replace.html"], self.R["static5.html"]
        self.assertAlmostEqual(rep[key(1.8)]["bars"][0]["box"][3] - rep[key(1.8)]["bars"][0]["box"][1],
                               static[key(1.8)]["bars"][0]["box"][3] - static[key(1.8)]["bars"][0]["box"][1], delta=0.5,
                               msg="five rows at a time get the height of five rows")
        end = rep[key(4.9)]
        names = {n["t"]: n["op"] for n in end["names"]}
        self.assertLess(names["D"], 0.02, names)
        self.assertLess(names["E"], 0.02, names)
        self.assertGreater(names["N"], 0.95, names)
        self.assertGreater(names["M"], 0.95, names)
        bottom = max(b["box"][3] for b, n in zip(static[key(1.8)]["bars"], static[key(1.8)]["names"]))
        for i, n in enumerate(end["names"]):
            if n["op"] > 0.95:
                self.assertLessEqual(end["bars"][i]["box"][3], bottom + 1, "row %s sits inside the plot" % n["t"])

    def test_callout_leaves_the_reference_label_readable(self):
        f = self.R["rank-ref.html"][key(4.9)]
        self.assertGreater(f["callout"]["op"], 0.95)
        self.assertGreater(f["ref"]["op"], 0.95)
        a, b = f["callout"]["box"], f["ref"]["box"]
        overlap = min(a[2], b[2]) - max(a[0], b[0]) > 0 and min(a[3], b[3]) - max(a[1], b[1]) > 0
        self.assertFalse(overlap, "the callout %s covers the reference label %s" % (a, b))
        # and it still points at its row: the anchor (the bar's end + 4em) lies under the box
        anchor = f["bars"][0]["box"][2] + 4 * f["fs"]
        self.assertTrue(a[0] - 1 <= anchor <= a[2] + 1, "the callout %s left its anchor %.0f" % (a, anchor))

    def test_line_end_label_reads_the_point_under_the_tip(self):
        frames = self.R["line.html"]
        xs = [x["x"] for x in frames[key(LINE_T[0])]["xl"]]
        checked = 0
        for t in LINE_T:
            f = frames[key(t)]
            end = f["end"][0]
            if end["op"] < 0.5:
                continue
            tip = end["x"] - f["fs"] * 0.6
            idx = min(range(len(xs)), key=lambda i: abs(xs[i] - tip))
            self.assertAlmostEqual(num(end["t"]), LINE_VALUES[idx], places=1,
                                   msg="at %.2fs the end label reads %s but sits on %s (%s)" % (t, end["t"], LINE_LABELS[idx], LINE_VALUES[idx]))
            checked += 1
        self.assertGreaterEqual(checked, 12)

    def test_title_only_state_does_not_hide_the_end_label(self):
        frames = self.R["line.html"]
        for t in (3.9, 4.2, 4.5, 4.8, 5.1, 5.6):   # the second state (title only) starts at 3.6 + 0.15
            f = frames[key(t)]
            self.assertFalse(f["moving"], "a title-only state marks the chart as moving at %.2fs" % t)
            self.assertGreater(f["end"][0]["op"], 0.95)
            self.assertEqual(num(f["end"][0]["t"]), LINE_VALUES[-1])

    def test_line_callout_names_its_year(self):
        c = self.R["line.html"][key(5.6)]["callout"]
        self.assertEqual(c["t"], "2015: first year above 400")
        self.assertGreater(c["op"], 0.95)
        for pg in ("line.html", "line-end.html"):
            f = self.R[pg][key(5.6)]
            a, b = f["callout"]["box"], f["end"][0]["box"]
            overlap = min(a[2], b[2]) - max(a[0], b[0]) > 0 and min(a[3], b[3]) - max(a[1], b[1]) > 0
            self.assertFalse(overlap, "%s: the callout %s sits on the end label %s" % (pg, a, b))
        c2 = self.R["line-value.html"][key(5.6)]["callout"]
        self.assertEqual(c2["t"], "%.1f in 2015" % LINE_VALUES[LINE_LABELS.index("2015")])

    def test_check_warns_about_css_that_hides_labels_while_moving(self):
        def codes(pg):
            rep = json.loads(showtime("check", self.proj, "--page", pg, "--json", "--no-determinism", "--no-timeline", check=False).stdout)
            return [f for f in rep["findings"] if f["code"] == "chart_labels_hidden"]
        hid = codes("hide.html")
        self.assertTrue(hid and hid[0]["severity"] == "warning", hid)
        self.assertIn("delete the rule", hid[0].get("fix", ""))
        self.assertEqual(codes("grow.html"), [])


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
