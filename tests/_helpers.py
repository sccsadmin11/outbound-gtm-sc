"""Test helpers: load a skill script as a module and fake HTTP responses."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))


def load(rel: str):
    path = ROOT / rel
    sys.path.insert(0, str(path.parent))
    name = "skill_" + path.stem + "_" + str(abs(hash(rel)))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeResponse:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code = status
        self._data = data if data is not None else {}
        self.headers = headers or {}
        self.text = json.dumps(self._data)

    def json(self):
        return self._data


def fake_requests(handler):
    """Patch requests.request; handler(method, url, kwargs) -> FakeResponse. Records calls."""
    calls = []

    def _req(method, url, **kw):
        calls.append((method, url, kw))
        return handler(method, url, kw)

    return mock.patch("requests.request", side_effect=_req), calls
