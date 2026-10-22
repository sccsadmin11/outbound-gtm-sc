#!/usr/bin/env python3
"""Scan the generated sequence for spam trigger words and risky formatting.

Word list modeled on Mailmeteor's spam words list:
https://mailmeteor.com/blog/spam-words

Checks every subject and body in sequence.json (merge vars are ignored)
and, with --leads, the per-lead values of every custom merge var used.
Also flags: 2+ exclamation marks in a row, ALL CAPS words, more than
--max-links links, and link shorteners.

Exit 0 = clean. Exit 1 = hits remain (fix the copy config, rerun 07, rerun 08).
Words you accept on purpose go in data/allowlist.txt (one per line).
Writes a local report only.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "lib"))
from copy_utils import MERGE_RE, STANDARD_FIELDS, SYSTEM_VARS  # noqa: E402
from gtm_common import read_csv, read_json, write_json  # noqa: E402

DATA = HERE.parent / "data"
TEMPLATES = HERE.parents[1] / "07-copy-generator" / "templates" / "email_templates.json"
SHORTENERS = ("bit.ly", "tinyurl.com", "goo.gl", "ow.ly", "t.co", "is.gd", "buff.ly", "rebrand.ly")
URL_RE = re.compile(r"(https?://\S+|www\.\S+)", re.I)
CAPS_RE = re.compile(r"\b[A-Z]{4,}\b")


def load_words(path: Path = DATA / "spam_words.json") -> dict[str, str]:
    """phrase(lower) -> category"""
    doc = read_json(path)
    out = {}
    for cat, words in doc["categories"].items():
        for w in words:
            out.setdefault(w.lower().replace("\u2019", "'"), cat)
    return out


def load_allowlist(path: Path = DATA / "allowlist.txt") -> set[str]:
    if not path.exists():
        return set()
    return {l.strip().lower() for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")}


def _pattern(phrase: str) -> re.Pattern:
    esc = re.escape(phrase)
    left = r"(?<![\w])" if phrase[:1].isalnum() else ""
    right = r"(?![\w])" if phrase[-1:].isalnum() else ""
    return re.compile(left + esc + right, re.I)


class Scanner:
    def __init__(self, words: dict[str, str] | None = None, allow: set[str] | None = None,
                 replacements: dict | None = None, max_links: int = 1):
        self.words = words if words is not None else load_words()
        self.allow = allow if allow is not None else load_allowlist()
        self.repl = replacements if replacements is not None else {
            k: v for k, v in read_json(DATA / "replacements.json").items() if not k.startswith("_")}
        self.max_links = max_links
        self.patterns = [(p, c, _pattern(p)) for p, c in self.words.items() if p not in self.allow]

    def scan(self, text: str, where: str) -> list[dict]:
        clean = MERGE_RE.sub(" ", text or "")
        hits = []
        for phrase, cat, pat in self.patterns:
            for m in pat.finditer(clean):
                hits.append({"where": where, "match": m.group(0), "phrase": phrase, "category": cat,
                             "suggestion": self.repl.get(phrase, "rephrase in plain, specific words")})
        if "!!" in clean:
            hits.append({"where": where, "match": "!!", "phrase": "!!", "category": "formatting",
                         "suggestion": "use one exclamation mark at most"})
        for m in CAPS_RE.finditer(clean):
            if m.group(0).lower() not in self.allow:
                hits.append({"where": where, "match": m.group(0), "phrase": m.group(0), "category": "formatting",
                             "suggestion": "avoid ALL CAPS"})
        links = URL_RE.findall(clean)
        if len(links) > self.max_links:
            hits.append({"where": where, "match": f"{len(links)} links", "phrase": "links", "category": "formatting",
                         "suggestion": f"keep it to {self.max_links} link or fewer in cold email"})
        for l in links:
            if any(s in l.lower() for s in SHORTENERS):
                hits.append({"where": where, "match": l, "phrase": "link shortener", "category": "formatting",
                             "suggestion": "use the full domain"})
        # longer phrases win: drop a hit fully inside another hit's phrase in the same place
        keep = []
        for h in hits:
            if not any(o is not h and o["where"] == h["where"] and h["phrase"] != o["phrase"]
                       and h["phrase"] in o["phrase"] and h["match"].lower() in o["match"].lower() for o in hits):
                keep.append(h)
        return keep


def template_phrases(sc: "Scanner", tid: str) -> set[str]:
    """Phrases that are part of the verbatim template text. Those can't be edited, so they are notes."""
    if not TEMPLATES.exists():
        return set()
    raw = read_json(TEMPLATES)["templates"].get(tid, "")
    raw = re.sub(r"\{\{.+?\}\}", " ", raw)
    return {h["phrase"] for h in sc.scan(raw, "template")}


def check(sequence: dict, leads: list[dict] | None = None, scanner: Scanner | None = None) -> dict:
    sc = scanner or Scanner()
    hits, notes = [], []
    custom = set()
    for st in sequence["steps"]:
        for v in st["variations"]:
            tag = f"Email {st['step']}{v['variation']}"
            hits += sc.scan(v.get("subject", ""), f"{tag} subject")
            fixed = template_phrases(sc, v.get("template_id", f"{st['step']}{v['variation']}"))
            for h in sc.scan(v.get("body_text", ""), f"{tag} body"):
                (notes if h["phrase"] in fixed else hits).append(h)
            custom |= set(MERGE_RE.findall(v.get("subject", "") + v.get("body_text", "")))
    custom -= SYSTEM_VARS | set(STANDARD_FIELDS.values()) | {"first_name", "last_name"}
    for lead in leads or []:
        for var in sorted(custom):
            val = lead.get(var, "")
            if val:
                hits += sc.scan(val, f"lead {lead.get('email')} {{{{{var}}}}}")
    for n in notes:
        n["suggestion"] = "part of the verbatim template, kept on purpose"
    return {"passed": not hits, "hit_count": len(hits), "hits": hits, "template_notes": notes,
            "source": "https://mailmeteor.com/blog/spam-words"}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sequence", default="sequence.json")
    p.add_argument("--leads", help="verified_leads.csv, to scan per-lead merge var values")
    p.add_argument("--max-links", type=int, default=1)
    p.add_argument("--out", default="spam_report.json")
    a = p.parse_args(argv)
    seq = read_json(a.sequence)
    leads = read_csv(a.leads) if a.leads else None
    rep = check(seq, leads, Scanner(max_links=a.max_links))
    rep["sequence_sha256"] = hashlib.sha256(Path(a.sequence).read_bytes()).hexdigest()
    write_json(a.out, rep)
    for n in rep["template_notes"]:
        print(f"  note: {n['where']}: \"{n['match']}\" is in the verbatim template (not counted)")
    if rep["passed"]:
        print(f"PASS: no spam trigger words found -> {a.out}")
        return 0
    print(f"FAIL: {rep['hit_count']} hit(s) -> {a.out}")
    for h in rep["hits"]:
        print(f"  [{h['category']}] {h['where']}: \"{h['match']}\" -> try: {h['suggestion']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
