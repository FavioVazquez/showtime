"""Loaded by every Python process a test file starts while run_all.py records which repository files that
test file uses (run_all puts this folder first on PYTHONPATH and sets ST_TRACE_DIR / ST_TRACE_ROOT).

Records each file under ST_TRACE_ROOT the process opens or imports (the "open" audit event; a cached import
opens __pycache__/<name>.cpython-XY.pyc, recorded as <name>.py) and appends it at once to
ST_TRACE_DIR/py-<pid>.txt, so a process that is killed still leaves what it used. Never prints, never
raises: any problem only stops the recording. Stdlib only, Python 3.8+.
"""
import os
import sys


def _install():
    out = os.environ.get("ST_TRACE_DIR")
    root = os.environ.get("ST_TRACE_ROOT")
    if not out or not root or not hasattr(sys, "addaudithook"):
        return
    roots = tuple({os.path.normcase(os.path.join(os.path.abspath(root), "")),
                   os.path.normcase(os.path.join(os.path.realpath(root), ""))})
    log = os.path.join(out, "py-%d.txt" % os.getpid())
    seen = set()
    busy = [False]
    abspath, normcase = os.path.abspath, os.path.normcase

    def hook(event, args):
        if event != "open" or busy[0] or not args:
            return
        p = args[0]
        if not isinstance(p, str):
            return
        try:
            busy[0] = True
            a = abspath(p)
            if a in seen:
                return
            seen.add(a)
            if not normcase(a).startswith(roots):
                return
            d, name = os.path.split(a)
            if os.path.basename(d) == "__pycache__" and name.endswith(".pyc"):
                a = os.path.join(os.path.dirname(d), name.split(".", 1)[0] + ".py")
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(a + "\n")
        except Exception:  # noqa: BLE001 - recording must never break the test
            pass
        finally:
            busy[0] = False

    try:
        os.makedirs(out, exist_ok=True)
        sys.addaudithook(hook)
    except Exception:  # noqa: BLE001
        pass


def _chain():
    """Run the next sitecustomize on sys.path (a distribution's own), which this file shadows."""
    here = os.path.normcase(os.path.dirname(os.path.abspath(__file__)))
    for d in sys.path:
        try:
            if os.path.normcase(os.path.abspath(d or os.curdir)) == here:
                continue
            cand = os.path.join(d or os.curdir, "sitecustomize.py")
            if os.path.isfile(cand):
                import importlib.util
                spec = importlib.util.spec_from_file_location("_st_next_sitecustomize", cand)
                if spec and spec.loader:
                    spec.loader.exec_module(importlib.util.module_from_spec(spec))
                return
        except Exception:  # noqa: BLE001
            return


_install()
_chain()
