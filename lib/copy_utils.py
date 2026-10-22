"""Shared helpers for copy generation, spam checks and QA (skills 07, 08, 11)."""
from __future__ import annotations

import html
import re

MERGE_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")
SLOT_RE = re.compile(r"\{\{(.+?)\}\}")

# Variables PlusVibe fills from the sending inbox, not from the lead row.
# {{sender_first_name}} appears in PlusVibe's own API examples.
SYSTEM_VARS = {"sender_first_name"}

# Lead CSV column -> PlusVibe standard lead field (skill 09 uses the same map).
STANDARD_FIELDS = {
    "email": "email",
    "first_name": "first_name",
    "last_name": "last_name",
    "company_name": "company_name",
    "domain": "company_website",
    "linkedin_url": "linkedin_person_url",
}


def merge_vars(text: str) -> set[str]:
    return set(MERGE_RE.findall(text or ""))


def text_to_html(text: str) -> str:
    """Plain text -> PlusVibe body HTML (one <div> per line)."""
    out = []
    for line in (text or "").split("\n"):
        out.append(f"<div>{html.escape(line, quote=False)}</div>" if line else "<div><br></div>")
    return "".join(out)


def available_vars(lead: dict) -> dict:
    """Merge vars a lead row provides once uploaded (columns + standard field names)."""
    v = {k: (val or "") for k, val in lead.items()}
    for col, field in STANDARD_FIELDS.items():
        if col in lead and field not in v:
            v[field] = lead[col] or ""
    return v


def render(text: str, lead: dict, sender: dict | None = None) -> tuple[str, list[str]]:
    """Substitute merge vars for a preview. Returns (rendered, missing_or_empty_vars)."""
    values = available_vars(lead)
    if sender:
        name = (sender.get("name") or "").strip()
        values.setdefault("sender_first_name", "[sender first name]" if name.startswith("{{") or not name else name.split(" ")[0])
    missing = []

    def sub(m):
        k = m.group(1)
        val = values.get(k, "")
        if not str(val).strip():
            missing.append(k)
            return m.group(0)
        return str(val)

    return MERGE_RE.sub(sub, text or ""), missing
