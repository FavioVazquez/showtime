"""`showtime motion ...`: list the motion components, scene transitions and themes.
`showtime data ...`: turn a CSV/JSON table into the chart data files the data template reads.

Stdlib only (`data` also runs before the venv exists)."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .common import ShowtimeError, print_json, skill_dir

COMMANDS = {
    "motion": "List motion components, scene transitions (CSS + WebGL) and themes for HTML videos",
    "data": "Turn a CSV or JSON table into chart data for a project: showtime data import <file> <project>",
}


def _runtime() -> Path:
    return skill_dir() / "runtime"


# One-liners for components that share a file (the file header describes both).
SUMMARY = {
    "chat-thread": "chat bubbles with typing indicator, optional streamed (AI-style) replies, auto-scroll",
    "notifications": "notification banners that spring in from the top and stack",
    "cursor": "synthetic pointer: eased arcs between waypoints or elements, click ripple, press, hover",
    "keystrokes": "keycap overlay (shortcuts) or typed-text bubble, bottom centre",
    "logo-reveal": "logo or wordmark reveal: assemble, mask, blur, draw (SVG strokes)",
    "end-card": "closing card: logo image and/or wordmark (both when data-logo + data-text) + tagline + CTA pill + URL",
    "browser-frame": "brand-free browser window around a screenshot, video or live DOM; scroll, zoom, typed URL",
    "device-frame": "phone / tablet / laptop body around a screenshot, video or live DOM; scroll, zoom, tilt",
    "count-up": "animated statistic with tabular digits, landing pulse, optional ring or bar",
    "lower-third": "name + role identification: bar, card, kicker, pill variants",
    "fit": "shrink type so the longest line fits its box at every frame size (terminals, code, command pills); wraps with a hanging indent only below the minimum",
    "camera": "scene camera: eased pushes, pulls and pans over the scene's content in log-zoom space, drift on holds, parallax depth layers",
    "code-block": "editor-style code panel from `showtime code` tokens: line or typed reveal, highlight, diff, focus scroll",
}


def list_components() -> List[Dict[str, Any]]:
    """Every define({name: ...}) in runtime/components, with the file's summary line."""
    out = []
    for f in sorted((_runtime() / "components").glob("*.js")):
        text = f.read_text(encoding="utf-8")
        names = re.findall(r"define\(\{\s*name:\s*'([^']+)'", text)
        if not names:
            continue
        head = []
        for line in text.splitlines():
            if not line.startswith("//"):
                break
            head.append(line[2:].strip())
        summary = " ".join(head).split(". ")[0].rstrip(".") if head else ""
        summary = re.sub(r"^[\w-]+( and [\w-]+)?:\s*", "", summary)
        for n in names:
            m = re.search(r"name:\s*'%s',\s*defaults:\s*\{(.*?)\},\s*\n" % re.escape(n), text, re.S)
            opts = re.findall(r"(\w+):", m.group(1)) if m else []
            out.append({"name": n, "module": "/_st/components/" + f.name, "summary": SUMMARY.get(n, summary),
                        "options": [o for o in opts if o not in ("true", "false", "null")],
                        "html": '<div data-st="%s"></div>' % n})
    return out


def list_transitions(kind: str = "", energy: str = "") -> List[Dict[str, Any]]:
    cat = _runtime() / "transitions" / "catalog.json"
    if not cat.is_file():
        raise ShowtimeError("transition catalog missing: %s" % cat, hint="reinstall the skill")
    data = json.loads(cat.read_text(encoding="utf-8"))
    items = data.get("transitions", [])
    if kind:
        items = [t for t in items if t.get("kind") == kind]
    if energy:
        items = [t for t in items if t.get("energy") == energy]
    return items


def list_themes() -> List[Dict[str, Any]]:
    out = []
    for f in sorted((_runtime() / "themes").glob("*.css")):
        if f.name in ("base.css", "fonts.css"):
            continue
        first = f.read_text(encoding="utf-8").splitlines()[0]
        m = re.match(r"/\*\s*showtime theme:\s*([\w-]+)\.\s*(.*)$", first)
        desc = m.group(2) if m else first
        out.append({"name": f.stem, "href": "/_st/themes/" + f.name, "summary": desc.rstrip(" */")})
    return out


def cmd_motion(args: argparse.Namespace) -> int:
    what = args.what or "all"
    res: Dict[str, Any] = {}
    if what in ("components", "all"):
        res["components"] = list_components()
    if what in ("transitions", "all"):
        res["transitions"] = list_transitions(args.kind or "", args.energy or "")
    if what in ("themes", "all"):
        res["themes"] = list_themes()
    if args.json:
        print_json(res)
        return 0
    if "components" in res:
        print("components  (<script type=\"module\" src=\"/_st/components/index.js\"></script>, then data-st=\"name\")")
        for c in res["components"]:
            print("  %-16s %s" % (c["name"], c["summary"]))
    if "transitions" in res:
        print("\ntransitions (data-transition=\"<name> [dir] [seconds]\" on the incoming scene)")
        for t in res["transitions"]:
            print("  %-16s %-5s %-6s %4.2fs  %s" % (t["name"], t["kind"], t["energy"], t["dur"], t.get("use_when", "")))
    if "themes" in res:
        print("\nthemes      (<link rel=\"stylesheet\" href=\"/_st/themes/<name>.css\">)")
        for t in res["themes"]:
            print("  %-16s %s" % (t["name"], t["summary"]))
    if what == "all":
        print("\ndocs: references/components.md, references/transitions.md, references/motion-craft.md")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("motion", help=COMMANDS["motion"], description=(
        "List what an HTML video page can use.\n\n"
        "  components   motion components (kinetic type, captions, charts, frames, cursor ...)\n"
        "  transitions  scene transitions, CSS and WebGL, with energy and when to use them\n"
        "  themes       token themes (colour, type, motion feel)\n\n"
        "examples:\n"
        "  showtime motion\n"
        "  showtime motion transitions --energy calm\n"
        "  showtime motion components --json"), formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("what", nargs="?", choices=["components", "transitions", "themes", "all"], help="what to list (default all)")
    p.add_argument("--kind", choices=["css", "webgl"], help="transitions: only this kind")
    p.add_argument("--energy", choices=["calm", "medium", "high"], help="transitions: only this energy")
    p.add_argument("--json", action="store_true", help="print JSON")
    p.set_defaults(func=cmd_motion)
    register_data(sub)


# ---------------------------------------------------------------------------- data
#
# `showtime data import <table> <project>` writes the JSON a `data-st="chart"` element reads
# (data/<name>.json in the project) and, with --scene, points that scene's chart at it.

import csv
import io
import math

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_NUMLIKE = re.compile(r"^\(?[-+−]?\s*[$€£¥₹]?\s*[-+−]?(\d{1,3}(,\d{3})+|\d+)?(\.\d+)?\s*(%|[kKmMbB])?\s*[$€£¥₹%]?\)?$")


def _num(v: Any) -> Any:
    """'1,200' -> 1200, '$3.5k' -> 3500, '45%' -> 45, '(12)' -> -12, '' -> None; else raises ValueError."""
    if isinstance(v, bool):
        raise ValueError(v)
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v
    if v is None:
        return None
    t = str(v).strip().replace(" ", "").replace(" ", "")
    if t in ("", "-", "—", "NA", "N/A", "n/a", "null", "None", "NaN", "nan"):
        return None
    if not _NUMLIKE.match(t) or not re.search(r"\d", t):
        raise ValueError(v)
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace("−", "-")
    mult = 1.0
    m = re.search(r"([kKmMbB])[$€£¥₹%]?$", t)
    if m:
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}[m.group(1).lower()]
    t = re.sub(r"[$€£¥₹%kKmMbB,+]", "", t)
    x = float(t) * mult
    x = -x if neg else x
    return int(x) if x.is_integer() and abs(x) < 1e15 else x


def _affix(values: List[str]) -> Any:
    """A currency prefix or % suffix shared by most cells of a column."""
    vals = [str(v).strip() for v in values if str(v).strip()]
    if not vals:
        return "", ""
    for sym in "$€£¥₹":
        if sum(sym in v for v in vals) >= 0.8 * len(vals):
            return sym, ""
    if sum(v.endswith("%") for v in vals) >= 0.8 * len(vals):
        return "", "%"
    return "", ""


def read_table(path: Path) -> Any:
    """(columns, rows as dicts of raw cell values) from a CSV/TSV or JSON file."""
    if not path.is_file():
        raise ShowtimeError("table not found: %s" % path, hint="pass a .csv, .tsv or .json file")
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if path.suffix.lower() == ".json" or text.lstrip()[:1] in "[{":
        try:
            data = json.loads(text)
        except ValueError as e:
            raise ShowtimeError("%s is not valid JSON: %s" % (path, e))
        if isinstance(data, dict):
            for key in ("rows", "data", "records", "items", "values"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
            else:
                if data and all(isinstance(v, list) for v in data.values()):
                    n = max(len(v) for v in data.values())
                    data = [{k: (v[i] if i < len(v) else None) for k, v in data.items()} for i in range(n)]
        if not isinstance(data, list) or not data or not all(isinstance(r, dict) for r in data):
            raise ShowtimeError("%s is not a table" % path,
                                hint="use a list of rows [{\"month\": \"Jan\", \"signups\": 120}, ...] or {\"column\": [values]}")
        cols: List[str] = []
        for r in data:
            for k in r:
                if k not in cols:
                    cols.append(str(k))
        return cols, [{str(k): v for k, v in r.items()} for r in data]
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if path.suffix.lower() == ".tsv" else csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ShowtimeError("%s has no data rows" % path, hint="the first row must be the column names")
    head = [h.strip() or "col%d" % (i + 1) for i, h in enumerate(rows[0])]
    out = []
    for r in rows[1:]:
        out.append({h: (r[i].strip() if i < len(r) else "") for i, h in enumerate(head)})
    return head, out


def _col(cols: List[str], name: str, what: str) -> str:
    if name in cols:
        return name
    low = {c.lower(): c for c in cols}
    if name.lower() in low:
        return low[name.lower()]
    if name.isdigit() and 1 <= int(name) <= len(cols):
        return cols[int(name) - 1]
    raise ShowtimeError("no column %r for %s" % (name, what), hint="columns: %s" % ", ".join(cols))


def _numeric_cols(cols: List[str], rows: List[Dict[str, Any]]) -> List[str]:
    out = []
    for c in cols:
        vals = [r.get(c) for r in rows if r.get(c) not in (None, "")]
        if not vals:
            continue
        ok = 0
        for v in vals:
            try:
                if _num(v) is not None:
                    ok += 1
            except ValueError:
                pass
        if ok >= 0.9 * len(vals):
            out.append(c)
    return out


def _pretty_labels(labels: List[str]) -> List[str]:
    """ISO months/dates on the first of the month -> 'Jan' (one year) or 'Jan 2025'."""
    ms = [re.match(r"^(\d{4})-(\d{2})(?:-(\d{2}))?(?:[T ].*)?$", x) for x in labels]
    if not labels or not all(ms) or any(m.group(3) not in (None, "01") for m in ms):
        return labels
    if not all(1 <= int(m.group(2)) <= 12 for m in ms):
        return labels
    years = {m.group(1) for m in ms}
    return [_MONTHS[int(m.group(2)) - 1] + ("" if len(years) == 1 else " " + m.group(1)) for m in ms]


def _decimals(values: List[Any]) -> int:
    d = 0
    for v in values:
        if isinstance(v, float) and not v.is_integer():
            d = max(d, min(2, len(("%.6f" % abs(v)).rstrip("0").split(".")[1])))
    return d


def _human(name: str) -> str:
    s = re.sub(r"[_\-]+", " ", name).strip()
    return s[:1].upper() + s[1:]


def parse_names(specs: Optional[List[str]]) -> Dict[str, str]:
    """--names wind_solar="Wind + solar" (repeatable, or comma-separated COL=Label pairs) -> {col: label}."""
    out: Dict[str, str] = {}
    for spec in specs or []:
        for part in re.split(r",(?=\s*[^,=]+=)", str(spec)):
            if not part.strip():
                continue
            if "=" not in part:
                raise ShowtimeError("--names %r: use COLUMN=Label (e.g. wind_solar=\"Wind + solar\")" % part.strip())
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


_WHERE_OPS = ("!=", "!~", ">=", "<=", "=", "~", ">", "<")


def _split_where(w: str) -> Optional[Tuple[str, str, str]]:
    """'COL<op>VALUE' -> (col, op, value), or None when there is no column or no operator."""
    at = next((i for i, ch in enumerate(w) if ch in "=!~<>"), -1)
    if at < 1:
        return None
    op = next((o for o in _WHERE_OPS if w.startswith(o, at)), None)
    return None if op is None else (w[:at], op, w[at + len(op):])


def filter_rows(cols: List[str], rows: List[Dict[str, Any]], wheres: Optional[List[str]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Keep the rows that match every --where: COL=V, COL!=V, COL~REGEX, COL!~REGEX, COL>N, COL<N (>=, <=)."""
    if not wheres:
        return rows, []
    tests = []
    for w in wheres:
        m = _split_where(str(w).strip("\r\n"))
        if not m:
            raise ShowtimeError("--where %r: use COLUMN=VALUE, COLUMN~REGEX or COLUMN>NUMBER" % w,
                                hint="e.g. --where MSN=CLETPUS --where \"YYYYMM~13$\"")
        col = _col(cols, m[0].strip(), "--where")
        op, val = m[1], m[2].strip().strip('"').strip("'")
        if op in ("~", "!~"):
            try:
                rx = re.compile(val)
            except re.error as e:
                raise ShowtimeError("--where %r: bad regular expression (%s)" % (w, e))
            tests.append((col, op, rx))
        elif op in (">", "<", ">=", "<="):
            try:
                tests.append((col, op, float(val)))
            except ValueError:
                raise ShowtimeError("--where %r: %s needs a number" % (w, op))
        else:
            tests.append((col, op, val))

    def ok(r: Dict[str, Any]) -> bool:
        for col, op, v in tests:
            cell = "" if r.get(col) is None else str(r.get(col)).strip()
            if op == "=" and cell != v:
                return False
            if op == "!=" and cell == v:
                return False
            if op == "~" and not v.search(cell):
                return False
            if op == "!~" and v.search(cell):
                return False
            if op in (">", "<", ">=", "<="):
                try:
                    n = _num(cell)
                except ValueError:
                    return False
                if n is None or not {">": n > v, "<": n < v, ">=": n >= v, "<=": n <= v}[op]:
                    return False
        return True
    kept = [r for r in rows if ok(r)]
    if not kept:
        raise ShowtimeError("no row matches --where %s" % " and ".join(wheres),
                            hint="check the values with `showtime data inspect <table>`")
    return kept, ["kept %d of %d rows (--where %s)" % (len(kept), len(rows), " and ".join(wheres))]


def build_chart(cols: List[str], rows: List[Dict[str, Any]], chart: Optional[str] = None, x: Optional[str] = None,
                y: Optional[str] = None, series: Optional[str] = None, top: Optional[int] = None,
                step: float = 1.4, highlight: Optional[str] = None, sort: Optional[str] = None,
                ref: Optional[str] = None, names: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """The chart JSON (without title texts) and the element type it needs. names: display names for
    value columns or series (default: the column name made readable, wind_solar -> "Wind solar")."""
    name_map = dict(names or {})

    def disp(nm: str, raw: bool = False) -> str:
        return name_map.get(nm, nm if raw else _human(nm))
    nums = _numeric_cols(cols, rows)
    xc = _col(cols, x, "--x") if x else next((c for c in cols if c not in nums), cols[0])
    sc = _col(cols, series, "--series") if series else None
    if y:
        ys = [_col(cols, v.strip(), "--y") for v in y.split(",") if v.strip()]
    else:
        ys = [c for c in nums if c not in (xc, sc)]
        if not ys:
            raise ShowtimeError("no numeric column to chart", why="columns: %s (x = %s)" % (", ".join(cols), xc),
                                hint="name the value column with --y <column>")
    notes: List[str] = []
    for c in ys:
        if c not in nums:
            raise ShowtimeError("column %r is not numeric" % c, hint="numeric columns: %s" % (", ".join(nums) or "none"))
    if chart is None:
        chart = "line" if (len(ys) > 1 or sc or len(rows) > 12) else "bar"
    if chart not in ("bar", "hbar", "line", "race"):
        raise ShowtimeError("unknown --chart %r" % chart, hint="bar, hbar, line or race")
    prefix, suffix = _affix([str(r.get(ys[0], "")) for r in rows])

    def val(r: Dict[str, Any], c: str) -> Any:
        try:
            return _num(r.get(c))
        except ValueError:
            return None
    xs_raw: List[str] = []
    for r in rows:
        k = str(r.get(xc, "")).strip()
        if k not in xs_raw:
            xs_raw.append(k)
    if sc:
        # long format: one row per (x, series) -> wide
        if len(ys) != 1:
            raise ShowtimeError("--series needs exactly one --y value column")
        names: List[str] = []
        wide: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            k, nm = str(r.get(xc, "")).strip(), str(r.get(sc, "")).strip()
            if nm not in names:
                names.append(nm)
            wide.setdefault(k, {})[nm] = val(r, ys[0])
        table = {k: wide.get(k, {}) for k in xs_raw}
        ynames = names
    else:
        table = {}
        for r in rows:
            k = str(r.get(xc, "")).strip()
            table[k] = {c: val(r, c) for c in ys}
        ynames = ys
    labels = _pretty_labels(xs_raw)
    lab_of = dict(zip(xs_raw, labels))
    all_vals = [v for row in table.values() for v in row.values() if v is not None]
    if not all_vals:
        raise ShowtimeError("the value column(s) %s hold no numbers" % ", ".join(ys))
    dec = _decimals(all_vals)
    out: Dict[str, Any] = {}
    if prefix:
        out["prefix"] = prefix
    if suffix:
        out["suffix"] = suffix
    if dec:
        out["decimals"] = dec
    if chart in ("bar", "hbar"):
        if len(ynames) > 1:
            notes.append("a %s chart shows one value per label: using %s (pass --chart line for all of %s)"
                         % (chart, ynames[0], ", ".join(ynames)))
        items = [{"label": lab_of[k], "value": table[k].get(ynames[0])} for k in xs_raw]
        missing = [it["label"] for it in items if it["value"] is None]
        items = [it for it in items if it["value"] is not None]
        if missing:
            notes.append("rows without a value were left out: %s" % ", ".join(missing[:6]))
        excluded = None
        if top and len(items) > top:
            ranked = sorted(items, key=lambda it: -it["value"])
            keep = ranked[:top]
            excluded = ranked[top]
            items = [it for it in items if it in keep]
            notes.append("kept the %d largest of %d rows (--top), in %s order" % (
                top, len(table), "value" if (sort or ("value" if chart == "hbar" else "source")) == "value" else "source"))
        if len(items) > 12:
            notes.append("%d bars are hard to read in a video: --top 8, or --chart line" % len(items))
        # bar keeps the table's order (chronology reads left to right), hbar ranks by value; --sort overrides
        if (sort or ("value" if chart == "hbar" else "source")) == "value":
            items.sort(key=lambda it: -it["value"])
        if any(it["value"] < 0 for it in items):
            notes.append("negative values: bars grow down from a zero line (anomalies, deltas, profit/loss)")
        if ref:
            if ref == "next":
                if excluded is None:
                    raise ShowtimeError("--ref next needs --top (it marks the first row --top left out)")
                out["ref"] = {"value": excluded["value"], "label": "%s: %s" % (excluded["label"], excluded["value"]),
                              "sub": "next largest"}
            else:
                v, _, lab = str(ref).partition(":")
                try:
                    out["ref"] = {"value": float(v), "label": lab or v}
                except ValueError:
                    raise ShowtimeError("--ref must be next, or VALUE[:LABEL] (e.g. 0.75:\"2014: +0.75\")")
        out["data"] = items
        labels_now = [it["label"] for it in items]
        vals_now = [it["value"] for it in items]
    elif chart == "line":
        series_list = []
        for nm in ynames:
            vals = [table[k].get(nm) for k in xs_raw]
            if any(v is None for v in vals):
                last = None
                filled = []
                for v in vals:
                    last = v if v is not None else last
                    filled.append(last if last is not None else 0)
                notes.append("series %s has gaps; they hold the previous value" % nm)
                vals = filled
            series_list.append({"name": disp(nm, raw=bool(sc)), "values": vals})
        if len(series_list) > 4:
            notes.append("%d lines is a lot for one chart: highlight one (--highlight) or chart fewer (--y a,b)" % len(series_list))
        out["data"] = {"labels": labels, "series": series_list}
        labels_now = [s_["name"] for s_ in series_list]
        vals_now = [s_["values"][-1] for s_ in series_list]
        if highlight is None and len(series_list) > 1:
            highlight = series_list[0]["name"]
    else:  # race: one state per x value, the racers are the series
        racers = list(ynames)
        best = {nm: max([v for v in (table[k].get(nm) for k in xs_raw) if v is not None] or [0]) for nm in racers}
        n = top or 10
        if len(racers) > n:
            racers = sorted(racers, key=lambda nm: -best[nm])[:n]
            notes.append("kept the %d racers with the highest values of %d (--top)" % (n, len(ynames)))
        states = []
        for i, k in enumerate(xs_raw):
            states.append({"at": round(i * step, 3), "title": lab_of[k],
                           "data": [{"label": disp(nm, raw=bool(sc)), "value": table[k].get(nm) or 0} for nm in racers]})
        out["states"] = states
        out["data"] = states[0]["data"]
        labels_now = [d["label"] for d in states[-1]["data"]]
        vals_now = [d["value"] for d in states[-1]["data"]]
        out["_needs"] = round(states[-1]["at"] + 1.3, 2)
    if highlight:
        h_ = str(highlight)
        if h_.lower() in ("max", "min", "last", "first") and labels_now:
            if h_.lower() == "max":
                h_ = labels_now[max(range(len(vals_now)), key=lambda i: vals_now[i] if vals_now[i] is not None else -1e99)]
            elif h_.lower() == "min":
                h_ = labels_now[min(range(len(vals_now)), key=lambda i: vals_now[i] if vals_now[i] is not None else 1e99)]
            else:
                h_ = labels_now[-1] if h_.lower() == "last" else labels_now[0]
        elif h_ not in labels_now:
            raise ShowtimeError("--highlight %r is not a %s" % (h_, "series" if chart == "line" else "label"),
                                hint="choose from: %s (or max, min, first, last)" % ", ".join(map(str, labels_now[:12])))
        out["highlight"] = h_
    unused = [k for k in name_map if k not in ynames]
    if unused:
        notes.append("--names %s: not a value column or series here (they are: %s)" % (
            ", ".join(unused), ", ".join(ynames[:12])))
    return {"type": "hbar" if chart in ("race", "hbar") else chart, "chart": chart, "json": out, "x": xc,
            "y": ys, "series": sc, "notes": notes, "rows": len(rows)}


def _dump_chart(obj: Dict[str, Any]) -> str:
    """Readable JSON: one line per data point, series or state."""
    def one(v: Any) -> str:
        return json.dumps(v, ensure_ascii=False)

    def block(v: Any, ind: str) -> str:
        if isinstance(v, list) and v and all(isinstance(x, (dict, list)) for x in v):
            return "[\n" + ",\n".join(ind + "  " + one(x) for x in v) + "\n" + ind + "]"
        if isinstance(v, dict) and any(isinstance(x, list) for x in v.values()):
            return "{\n" + ",\n".join("%s  %s: %s" % (ind, one(k), block(x, ind + "  ")) for k, x in v.items()) + "\n" + ind + "}"
        return one(v)
    return "{\n" + ",\n".join('  %s: %s' % (one(k), block(v, "  ")) for k, v in obj.items()) + "\n}\n"


class NoChart(ShowtimeError):
    """The --scene exists but holds no chart element (the data is still written)."""


def _wire_scene(proj: Path, scene: str, src: str, ctype: str) -> Any:
    """Point the first chart in <scene> at src; returns (new html, scene duration) or raises."""
    from .cli_core import _Tags, _add_attr, _top_of
    page = proj / "index.html"
    try:
        cfg = json.loads((proj / "showtime.json").read_text(encoding="utf-8-sig"))
        page = proj / str(cfg.get("page") or "index.html")
    except (OSError, ValueError):
        pass
    if not page.is_file():
        raise ShowtimeError("no %s in %s" % (page.name, proj))
    html = page.read_text(encoding="utf-8")
    doc = _Tags(html)
    clips = doc.resolve()
    tops = [c for c in clips if c["parent"] is None]
    names = [c["id"] or c["attrs"].get("data-name") or "" for c in tops]
    want = scene.lstrip("#")
    sc = next((c for c, n in zip(tops, names) if n == want), None)
    if sc is None and want.isdigit() and 1 <= int(want) <= len(tops):
        sc = tops[int(want) - 1]
    if sc is None:
        raise ShowtimeError("no scene %r in %s" % (scene, page.name), hint="scenes: %s" % ", ".join(n or "?" for n in names))
    charts = [t for t in doc.tags if t["attrs"].get("data-st") == "chart" and _top_of(t) is sc]
    if not charts:
        raise NoChart("scene %s has no chart element" % want,
                      hint='add <div class="chart" data-st="chart" data-src="%s" data-type="%s" data-at="0.2"></div> to it'
                           % (src, ctype))
    t = charts[0]
    raw = _add_attr(_add_attr(t["raw"], "data-src", src), "data-type", ctype)
    for gone in ("data-data", "data-states"):
        raw = re.sub(r"\s%s\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)" % gone, "", raw)
    dur = sc["t1"] - sc["t0"] if sc["t1"] == sc["t1"] and sc["t1"] != float("inf") else None
    at = 0.0
    try:
        at = float(t["attrs"].get("data-at") or 0)
    except ValueError:
        pass
    return page, html[:t["start"]] + raw + html[t["end"]:], (sc["id"] or want), dur, at


def cmd_data(args: argparse.Namespace) -> int:
    if args.action == "inspect":
        path = Path(args.table).expanduser()
        cols, rows = read_table(path)
        nums = set(_numeric_cols(cols, rows))
        res = {"file": str(path), "rows": len(rows), "columns": [
            {"name": c, "numeric": c in nums, "sample": [str(r.get(c, "")) for r in rows[:3]]} for c in cols]}
        if args.json:
            print_json(res)
        else:
            print("%s: %d rows" % (path, len(rows)))
            for c in res["columns"]:
                print("  %-20s %-8s %s" % (c["name"], "number" if c["numeric"] else "text", ", ".join(c["sample"])))
            print("next: showtime data import %s <project> --x <column> --y <column>" % path)
        return 0
    if not args.project:
        raise ShowtimeError("missing the project folder", hint="showtime data import %s <project>" % args.table)
    path = Path(args.table).expanduser()
    proj = Path(args.project).expanduser().resolve()
    if not (proj / "showtime.json").is_file():
        raise ShowtimeError("no showtime.json in %s" % proj, hint="start one with `showtime new data %s`" % args.project)
    cols, rows = read_table(path)
    rows, fnotes = filter_rows(cols, rows, args.where)
    res = build_chart(cols, rows, args.chart, args.x, args.y, args.series, args.top, args.step, args.highlight,
                      sort=args.sort, ref=args.ref, names=parse_names(args.names))
    res["notes"] = fnotes + res["notes"]
    js = res["json"]
    needs = js.pop("_needs", None)
    for key in ("prefix", "suffix"):
        if getattr(args, key) is not None:
            js[key] = getattr(args, key)
    if args.decimals is not None:
        js["decimals"] = args.decimals
    nmap = parse_names(args.names)
    one_y = res["y"][0] if len(res["y"]) == 1 and not res["series"] else ""
    title = args.title if args.title is not None else (nmap.get(one_y) or _human(one_y))
    head: Dict[str, Any] = {}
    if title:
        head["title"] = title
    head["subtitle"] = args.subtitle if args.subtitle is not None else "Source: %s" % path.name
    if args.annotate:
        target = js.get("highlight")
        if not target:
            raise ShowtimeError("--annotate needs --highlight (the label the callout points at)")
        js["annotate"] = {"label": target, "text": args.annotate}
    out_json = dict(head, **js)
    out = Path(args.output).expanduser() if args.output else proj / "data" / ("%s.json" % re.sub(r"[^\w.-]+", "-", path.stem).strip("-").lower())
    if not out.is_absolute():
        out = (Path.cwd() / out) if args.output else out
    try:
        src = out.resolve().relative_to(proj).as_posix()
    except ValueError:
        raise ShowtimeError("%s is outside the project" % out, why="the page can only load files inside its folder",
                            hint="write it under %s/data/" % proj)
    notes = list(res["notes"])
    if args.title is None:
        notes.append("no --title: the chart title is %s; pass --title with the takeaway (\"Signups doubled in June\")"
                     % (repr(title) if title else "empty"))
    if res["chart"] == "race" and title:
        for st_ in out_json.get("states") or []:
            st_["title"] = "%s \u00b7 %s" % (title, st_["title"])
    wired = None
    snippet = '<div class="chart" data-st="chart" data-type="%s" data-src="%s" data-at="0.2"></div>' % (res["type"], src)
    no_chart = None
    if args.scene:
        try:
            page, html, sid, dur, at = _wire_scene(proj, args.scene, src, res["type"])
            wired = {"page": str(page), "scene": sid}
        except NoChart as e:
            # the data is still worth writing: say where the chart element goes
            no_chart = str(e.args[0]) if e.args else "scene %s has no chart element" % args.scene
            notes.append("%s, so nothing was wired: add %s to it (the data file is written)" % (no_chart, snippet))
    if wired:
        if needs and dur is not None and at + needs > dur + 1e-6:
            notes.append("scene %s is %.1fs but the race needs %.1fs from its start: `showtime retime %s -d <longer>` "
                         "or raise the scene's data-dur (or a smaller --step)" % (sid, dur, at + needs, args.project))
    existed = out.is_file()
    if not args.dry_run:
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(str(out), "w", encoding="utf-8", newline="") as fh:
            fh.write(_dump_chart(out_json))
        if wired:
            with open(wired["page"], "w", encoding="utf-8", newline="") as fh:
                fh.write(html)
    result = {"output": str(out), "src": src, "type": res["type"], "chart": res["chart"], "x": res["x"], "y": res["y"],
              "series": res["series"], "rows": res["rows"], "scene": wired and wired["scene"], "replaced": existed,
              "notes": notes, "data": out_json, "dry_run": bool(args.dry_run)}
    if args.json:
        print_json(result)
        return 0
    from .common import log, warn
    log("%s %s chart data from %s (%d rows; x=%s, y=%s%s) -> %s%s" % (
        "would write" if args.dry_run else "wrote", res["chart"], path.name, res["rows"], res["x"], ",".join(res["y"]),
        (", series=%s" % res["series"]) if res["series"] else "", out, " (replaced)" if existed else ""))
    if wired:
        log("scene %s: its chart now reads %s (data-type=\"%s\")" % (wired["scene"], src, res["type"]))
    elif not no_chart:
        log("use it in a scene: %s" % snippet)
        log("or run again with --scene <scene id> to point that scene's chart at it")
    for n in notes:
        warn(n)
    print(str(out))
    return 0


def register_data(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("data", help=COMMANDS["data"], description=(
        "Turn a table (CSV, TSV or JSON rows) into the JSON a chart reads (data-st=\"chart\", the\n"
        "`data` template), so a spreadsheet becomes a chart scene in one command.\n\n"
        "  inspect <table>            columns, whether they are numbers, first values\n"
        "  import <table> <project>   write <project>/data/<name>.json (and, with --scene, point\n"
        "                             that scene's chart at it)\n\n"
        "Charts: bar (one value per label), hbar (ranked bars), line (one line per value column,\n"
        "or per --series value in long tables), race (ranked bars that re-order over time: one\n"
        "state per row, every --step seconds; the value columns are the racers). Numbers like\n"
        "1,200 / $3.5k / 45% / (12) are read; a shared $ or % becomes the prefix/suffix; ISO\n"
        "months (2026-01) become Jan, Feb ... Default: x = the first text column, y = every\n"
        "numeric column; bar for one value column and up to 12 rows, else line.\n\n"
        "Never invent numbers: the chart shows exactly what the table holds, and the subtitle\n"
        "names the source file until you replace it with the real source."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("Examples:\n"
                "  showtime data inspect signups.csv\n"
                "  showtime data import signups.csv my-data --x month --y signups --scene bars \\\n"
                "      --title \"Signups doubled in June\" --highlight max --annotate \"launch week\"\n"
                "  showtime data import deploys.csv my-data --chart line --x week --y with_cache,before --scene lines\n"
                "  showtime data import sales-long.csv my-data --chart line --x month --y revenue --series region\n"
                "  showtime data import languages.csv my-data --chart race --x year --top 8 --step 1.2\n"
                "  showtime data import metrics.json my-data -o my-data/data/latency.json --suffix \" ms\"\n"
                "  showtime data import eia.csv my-data --where \"YYYYMM~13$\" --x YYYYMM --y Value --series MSN \\\n"
                "      --names CLETPUS=Coal,NGETPUS=\"Natural gas\""))
    p.add_argument("action", choices=["import", "inspect"], help="import a table, or inspect its columns")
    p.add_argument("table", help="a .csv / .tsv / .json table (first CSV row = column names)")
    p.add_argument("project", nargs="?", help="project folder (import)")
    p.add_argument("--chart", "-c", choices=["bar", "hbar", "line", "race"], help="chart kind (default: bar or line, see above)")
    p.add_argument("--x", "-x", metavar="COL", help="label column (default: the first text column)")
    p.add_argument("--y", "-y", metavar="COL[,COL]", help="value column(s) (default: every numeric column)")
    p.add_argument("--series", metavar="COL", help="long tables: the column that names each line / racer")
    p.add_argument("--names", action="append", metavar="COL=Label", help="display name of a value column or series "
                   "(repeatable, or comma-separated): --names wind_solar=\"Wind + solar\" (default: wind_solar -> "
                   "\"Wind solar\")")
    p.add_argument("--where", action="append", metavar="COND", help="keep only matching rows (repeatable, all must "
                   "match): COL=VALUE, COL!=VALUE, COL~REGEX, COL!~REGEX, COL>N, COL<N; e.g. --where MSN=CLETPUS "
                   "--where \"YYYYMM~13$\" (annual rows of a monthly table)")
    p.add_argument("--title", "-t", help="chart title: the takeaway, not the metric name")
    p.add_argument("--subtitle", help="units and source (default: 'Source: <file name>')")
    p.add_argument("--highlight", metavar="LABEL", help="the label or series to accent (or max, min, first, last)")
    p.add_argument("--annotate", metavar="TEXT", help="callout on the highlighted label, shown after the marks settle")
    p.add_argument("--prefix", help="text before every value (e.g. '$'; default: detected)")
    p.add_argument("--suffix", help="text after every value (e.g. '%%' or ' ms'; default: detected)")
    p.add_argument("--decimals", type=int, help="decimal places (default: from the data, at most 2)")
    p.add_argument("--top", type=int, metavar="N", help="bar/hbar: keep the N largest rows; race: the N biggest racers (default 10)")
    p.add_argument("--sort", choices=["value", "source"], help="bar/hbar order: value (largest first) or source (the table's "
                                                                "order); default: bar source, hbar value")
    p.add_argument("--ref", metavar="next|VALUE[:LABEL]", help="bar/hbar: a dashed reference line; `next` marks the first "
                                                              "row --top left out (\"next warmest\")")
    p.add_argument("--step", type=float, default=1.4, metavar="S", help="race: seconds per row (default 1.4)")
    p.add_argument("--scene", "-s", metavar="ID", help="point the first chart in this scene at the new file (sets data-src and data-type)")
    p.add_argument("--output", "-o", metavar="FILE", help="where to write (default <project>/data/<table name>.json)")
    p.add_argument("--dry-run", "-n", action="store_true", help="print what would be written, write nothing")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.set_defaults(func=cmd_data)
