"""Shared helpers for the outbound-gtm-sc skills.

Everything here is provider-agnostic: env loading, HTTP with retries,
CSV/JSON IO and a tiny dry-run guard. Keys are only ever read from the
environment (or a local .env file you create yourself) and are never
printed.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 outbound-gtm-sc"
)


# --------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------
def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from .env into os.environ (no override).

    A tiny parser so the repo only depends on `requests`.
    """
    path = path or REPO_ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def require_env(*names: str) -> dict[str, str]:
    """Return the requested env vars or exit with a clear message.

    Only the variable NAMES are printed, never the values.
    """
    load_dotenv()
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        sys.exit(
            "Missing env vars: " + ", ".join(missing)
            + "\nCopy .env.example to .env and fill in your own keys."
        )
    return {n: os.environ[n] for n in names}


def optional_env(name: str, default: str = "") -> str:
    load_dotenv()
    return os.environ.get(name, default)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def redact(text: str) -> str:
    """Replace any secret-looking env var value found in `text` with ***."""
    for name, value in os.environ.items():
        if value and len(value) >= 8 and any(h in name.upper() for h in SECRET_HINTS):
            text = text.replace(value, "***")
    return text


class ApiError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(redact(f"HTTP {status} from {url}: {body[:300]}"))
        self.status = status
        self.body = body
        self.url = url


def http(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: Any = None,
    json_body: Any = None,
    timeout: float = 60,
    retries: int = 3,
    session: requests.Session | None = None,
    ok_statuses: Iterable[int] = (200, 201, 202),
) -> Any:
    """Make a request, retry on 429/5xx with backoff, return parsed JSON.

    Returns the raw text when the body is not JSON.
    """
    sess = session or requests
    hdrs = {"User-Agent": BROWSER_UA, "Accept": "application/json"}
    hdrs.update(headers or {})
    ok = set(ok_statuses)
    last: requests.Response | None = None
    for attempt in range(retries + 1):
        resp = sess.request(
            method, url, headers=hdrs, params=params, json=json_body, timeout=timeout
        )
        last = resp
        if resp.status_code in ok:
            try:
                return resp.json()
            except ValueError:
                return resp.text
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            wait = resp.headers.get("Retry-After")
            try:
                delay = float(wait) if wait else 2 ** attempt
            except ValueError:
                delay = 2 ** attempt
            time.sleep(min(delay, 60))
            continue
        break
    assert last is not None
    raise ApiError(last.status_code, last.text, url)


class RateLimiter:
    """Simple 'max N calls per second' limiter."""

    def __init__(self, per_second: float):
        self.min_gap = 1.0 / per_second if per_second > 0 else 0
        self._last = 0.0

    def wait(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self.min_gap:
            time.sleep(self.min_gap - gap)
        self._last = time.monotonic()


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------
def read_csv(path: str | Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    if fieldnames is None:
        fieldnames = []
        for r in rows:
            for k in r:
                if k not in fieldnames:
                    fieldnames.append(k)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fieldnames})


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, data: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def normalize_domain(value: str) -> str:
    v = (value or "").strip().lower()
    for prefix in ("https://", "http://"):
        if v.startswith(prefix):
            v = v[len(prefix):]
    if v.startswith("www."):
        v = v[4:]
    return v.split("/")[0].split("?")[0]


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def dry_run_print(action: str, payload: Any) -> None:
    """Print what WOULD be sent. Payloads never contain keys (auth goes in headers)."""
    print(f"[dry-run] {action}")
    print(json.dumps(payload, indent=2, ensure_ascii=False)[:4000])
