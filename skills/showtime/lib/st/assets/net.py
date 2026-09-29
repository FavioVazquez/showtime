"""Small, dependable HTTP helpers for asset fetching (stdlib only).

- Always sends a descriptive User-Agent (several APIs reject Python's default).
- Retries transient failures (timeouts, 5xx, 429 honouring Retry-After up to 60 s per wait).
- Streams downloads to `<dest>.part`, counts bytes (never trusts
  Content-Length), enforces a size cap and renames atomically.
- Optional JSON response cache in ~/.showtime/cache/http (TTL based).
- SHOWTIME_OFFLINE=1 makes every network call fail fast with a clear error
  (cached responses and already-downloaded files still work).
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from .. import __version__
from ..common import ShowtimeError, debug, home

# Wikimedia and others ask for a descriptive agent; SHOWTIME_CONTACT (an email or URL)
# is appended when set so API operators can reach the person running the tool.
# The project URL is the contact Wikimedia's User-Agent policy asks for (plain agents get HTTP 429 there).
USER_AGENT = "showtime/%s (open-source local video tool; +https://github.com/FavioVazquez/showtime%s)" % (
    __version__, ("; " + os.environ["SHOWTIME_CONTACT"]) if os.environ.get("SHOWTIME_CONTACT") else "")
# A browser-like UA for hosts that refuse unknown agents (sent only where needed).
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 showtime/%s" % __version__)

_SSL_CTX: Optional[ssl.SSLContext] = None


def offline() -> bool:
    return os.environ.get("SHOWTIME_OFFLINE", "") not in ("", "0", "false", "no")


def _ssl_context() -> ssl.SSLContext:
    """Default context, using certifi's CA bundle when available (portable Pythons
    sometimes ship without a usable system trust store)."""
    global _SSL_CTX
    if _SSL_CTX is None:
        try:
            import certifi  # type: ignore

            _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
        except Exception:  # noqa: BLE001
            _SSL_CTX = ssl.create_default_context()
    return _SSL_CTX


def _request(url: str, headers: Optional[Dict[str, str]] = None, method: str = "GET") -> urllib.request.Request:
    h = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        h.update(headers)
    return urllib.request.Request(url, headers=h, method=method)


class HTTPStatusError(ShowtimeError):
    def __init__(self, url: str, status: int, reason: str = ""):
        self.url = url
        self.status = status
        hint = None
        if status == 429:
            hint = "the service is rate limiting anonymous use; wait a minute and retry"
        elif status in (401, 403):
            hint = "the server refused the request (it may block scripts or need a key)"
        super().__init__("HTTP %s %s for %s" % (status, reason, _short(url)), hint=hint)


def _short(url: str, n: int = 110) -> str:
    return url if len(url) <= n else url[:n - 3] + "..."


RATE_LIMIT_MAX_WAIT = 60.0   # longest single wait on HTTP 429; a longer Retry-After fails with the time to wait


def retry_after(value: Optional[str]) -> Optional[float]:
    """Seconds from a Retry-After header (delta-seconds or an HTTP date), or None."""
    if not value:
        return None
    v = value.strip()
    try:
        return max(0.0, float(v))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        import datetime as _dt
        when = parsedate_to_datetime(v)
        if when.tzinfo is None:
            when = when.replace(tzinfo=_dt.timezone.utc)
        return max(0.0, (when - _dt.datetime.now(_dt.timezone.utc)).total_seconds())
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def open_url(url: str, *, headers: Optional[Dict[str, str]] = None, timeout: float = 30,
             retries: int = 2, method: str = "GET"):
    """urlopen with retries; returns the response object (caller closes it). HTTP 429 waits for the
    server's Retry-After (else 5, 10, 20 s ...), up to RATE_LIMIT_MAX_WAIT per wait."""
    if offline():
        raise ShowtimeError("offline mode (SHOWTIME_OFFLINE=1): cannot fetch %s" % _short(url))
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ShowtimeError("only http(s) URLs can be fetched (got %s)" % _short(url))
    last: Optional[BaseException] = None
    for attempt in range(retries + 1):
        try:
            return urllib.request.urlopen(_request(url, headers, method), timeout=timeout,
                                          context=_ssl_context())
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:
                ra = retry_after(e.headers.get("Retry-After") if e.headers else None)
                wait = ra if ra is not None else 5.0 * (2 ** attempt)
                if attempt < retries and wait <= RATE_LIMIT_MAX_WAIT:
                    from ..common import log as _log
                    _log("rate limited by %s: waiting %.0f s%s" % (urllib.parse.urlsplit(url).hostname or "the server",
                                                                   wait, " (its Retry-After)" if ra is not None else ""))
                    time.sleep(wait)
                    continue
                err = HTTPStatusError(url, 429, str(e.reason or ""))
                if ra is not None and ra > RATE_LIMIT_MAX_WAIT:
                    err.hint = "the server asks to wait about %.0f min before retrying%s" % (
                        ra / 60.0, "; Wikimedia serves thumbnails from another tier: fetch with --max-size 1920 "
                        "or 3840" if "wikimedia.org" in url else "")
                raise err from None
            if 500 <= e.code < 600 and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise HTTPStatusError(url, e.code, str(e.reason or "")) from None
        except (urllib.error.URLError, socket.timeout, ConnectionError, ssl.SSLError) as e:
            last = e
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
                continue
    reason = getattr(last, "reason", last)
    raise ShowtimeError("network error fetching %s: %s" % (_short(url), reason),
                        hint="check your internet connection (or proxy) and retry")


def get_bytes(url: str, *, headers: Optional[Dict[str, str]] = None, timeout: float = 30,
              max_bytes: int = 50 << 20, retries: int = 2) -> Tuple[bytes, str]:
    """GET a URL into memory -> (body, content_type). Enforces max_bytes."""
    with open_url(url, headers=headers, timeout=timeout, retries=retries) as r:
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        chunks = []
        total = 0
        while True:
            b = r.read(1 << 16)
            if not b:
                break
            total += len(b)
            if total > max_bytes:
                raise ShowtimeError("%s is larger than the %d MB limit" % (_short(url), max_bytes >> 20))
            chunks.append(b)
    return b"".join(chunks), ctype


def _cache_path(key: str) -> Path:
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return home() / "cache" / "http" / h[:2] / (h + ".json")


def get_json(url: str, *, headers: Optional[Dict[str, str]] = None, ttl: Optional[float] = None,
             timeout: float = 30, retries: int = 2) -> Any:
    """GET JSON. With ttl (seconds) the response is cached on disk; a stale
    cache entry is still used when the network is unavailable."""
    cp = _cache_path(url) if ttl else None
    if cp is not None and cp.is_file():
        age = time.time() - cp.stat().st_mtime
        if age < ttl or offline():
            try:
                return json.loads(cp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
    try:
        body, _ = get_bytes(url, headers=dict({"Accept": "application/json"}, **(headers or {})),
                            timeout=timeout, retries=retries)
    except ShowtimeError:
        if cp is not None and cp.is_file():
            debug("network failed; using stale cache for %s" % _short(url))
            return json.loads(cp.read_text(encoding="utf-8"))
        raise
    try:
        data = json.loads(body.decode("utf-8"))
    except ValueError:
        raise ShowtimeError("expected JSON from %s but got something else" % _short(url),
                            hint="the service may be down or changed; retry later")
    if cp is not None:
        try:
            cp.parent.mkdir(parents=True, exist_ok=True)
            tmp = cp.with_suffix(".tmp%d" % os.getpid())
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(str(tmp), str(cp))
        except OSError:
            pass
    return data


_MAGIC = [
    (b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"), (b"GIF87a", "gif"), (b"GIF89a", "gif"),
    (b"RIFF", "riff"), (b"\x1aE\xdf\xa3", "webm"), (b"OggS", "ogv"), (b"wOF2", "woff2"),
    (b"wOFF", "woff"), (b"\x00\x01\x00\x00", "ttf"), (b"OTTO", "otf"), (b"true", "ttf"),
    (b"%PDF", "pdf"),
]


def sniff_ext(head: bytes) -> Optional[str]:
    """File extension from the first bytes (None when unknown)."""
    for sig, ext in _MAGIC:
        if head.startswith(sig):
            if ext == "riff":
                return "webp" if head[8:12] == b"WEBP" else ("wav" if head[8:12] == b"WAVE" else None)
            return ext
    if len(head) > 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"qt  ",):
            return "mov"
        if brand.startswith(b"avif") or brand.startswith(b"avis"):
            return "avif"
        return "mp4"
    s = head.lstrip()[:200].lower()
    if s.startswith(b"<svg") or (s.startswith(b"<?xml") and b"<svg" in head[:2000].lower()):
        return "svg"
    if s.startswith(b"<!doctype html") or s.startswith(b"<html"):
        return "html"
    return None


def download(url: str, dest: Path, *, headers: Optional[Dict[str, str]] = None,
             max_bytes: int = 200 << 20, timeout: float = 60, retries: int = 2,
             reject_types: Iterable[str] = ("text/html", "application/xml", "text/xml"),
             progress: bool = False) -> Dict[str, Any]:
    """Stream `url` to `dest` atomically. Returns {path, bytes, sha256, content_type, ext}.

    Rejects HTML/XML error pages served with status 200 and bodies over max_bytes.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    total = 0
    head = b""
    t0 = time.time()
    last_note = t0
    with open_url(url, headers=headers, timeout=timeout, retries=retries) as r:
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if any(ctype.startswith(t) for t in reject_types):
            raise ShowtimeError("%s returned %s instead of a media file" % (_short(url), ctype or "an error page"))
        size_hint = r.headers.get("Content-Length")
        try:
            with open(part, "wb") as f:
                while True:
                    b = r.read(1 << 17)
                    if not b:
                        break
                    if len(head) < 4096:
                        head += b[:4096 - len(head)]
                    total += len(b)
                    if total > max_bytes:
                        raise ShowtimeError("%s exceeds the %d MB limit" % (_short(url), max_bytes >> 20),
                                            hint="pick a smaller rendition or raise the limit")
                    h.update(b)
                    f.write(b)
                    if progress and time.time() - last_note > 5:
                        last_note = time.time()
                        pct = (" of %.1f MB" % (int(size_hint) / 1e6)) if size_hint and size_hint.isdigit() else ""
                        debug("  %.1f MB%s downloaded" % (total / 1e6, pct))
            ext = sniff_ext(head)
            if ext == "html":
                raise ShowtimeError("%s returned an HTML page instead of a file" % _short(url))
            os.replace(str(part), str(dest))
        finally:
            if part.exists():
                try:
                    part.unlink()
                except OSError:
                    pass
    debug("downloaded %s (%d bytes, %.1fs)" % (_short(url), total, time.time() - t0))
    return {"path": str(dest), "bytes": total, "sha256": h.hexdigest(), "content_type": ctype, "ext": ext}


def quote_path(s: str) -> str:
    """Percent-encode a URL path segment (keeps '/')."""
    return urllib.parse.quote(s, safe="/")
