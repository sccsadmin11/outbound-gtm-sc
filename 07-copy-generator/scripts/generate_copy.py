#!/usr/bin/env python3
"""Build the cold email sequence from the verbatim templates.

Email 1: variants A, B, C.  Email 2: variants A, B.
Only the {{...}} slots and the listed plain placeholders (P.S. line,
X problem, ABC result, regarding X) are filled. Everything else is kept
character for character, including the typos "{{THe offer}}", "Whos" and
"i've". Every email gets the signature and the opt-out line.

"First_name" becomes the PlusVibe merge var {{first_name}} and
{{COMPANY}} becomes {{company_name}}.

Input : copy_config.json, verified_leads.csv (skill 06)
Output: sequence.json (PlusVibe-ready), preview.md (first N leads rendered)
This script writes local files only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "lib"))
from copy_utils import SLOT_RE, merge_vars, render, text_to_html  # noqa: E402
from gtm_common import read_csv, read_json, write_json  # noqa: E402

TEMPLATES_FILE = HERE.parent / "templates" / "email_templates.json"
DEFAULT_OPT_OUT = "If you don't want to hear from me again, just reply no thx!"
STEPS = {"1": ["1A", "1B", "1C"], "2": ["2A", "2B"]}


class CopyError(ValueError):
    pass


def load_templates(path: Path = TEMPLATES_FILE) -> dict:
    return read_json(path)


def fill_template(tid: str, tdoc: dict, slots: dict, plain: dict) -> str:
    """Fill one template. Literal text is untouched except the named placeholders."""
    template = tdoc["templates"][tid]
    system = tdoc.get("system_slots", {})
    fn = tdoc["first_name_token"]
    out, pos = [], 0
    for m in SLOT_RE.finditer(template):
        out.append(_literal(template[pos:m.start()], tid, tdoc, plain, fn))
        name = m.group(1)
        if name in system:
            val = system[name]
        else:
            val = (slots or {}).get(name)
            if val is None or not str(val).strip():
                raise CopyError(f"{tid}: slot '{{{{{name}}}}}' has no value in copy_config.json")
            val = str(val).strip()
            # template already has punctuation right after this slot (e.g. "{{CTA}}.")
            nxt = template[m.end():m.end() + 1]
            if nxt and nxt in ".?!" and val[-1:] in ".?!":
                val = val[:-1]
        out.append(val)
        pos = m.end()
    out.append(_literal(template[pos:], tid, tdoc, plain, fn))
    return "".join(out)


def _literal(seg: str, tid: str, tdoc: dict, plain: dict, fn: dict) -> str:
    seg = seg.replace(fn["find"], fn["replace_with"])
    for ph in tdoc.get("plain_placeholders", {}).get(tid, []):
        if ph["find"] in seg:
            val = (plain or {}).get(ph["key"])
            if val is None or not str(val).strip():
                raise CopyError(f"{tid}: placeholder '{ph['find']}' needs plain.{tid}.{ph['key']} in copy_config.json")
            seg = seg.replace(ph["find"], ph["replace_with"].format(value=str(val).strip()))
    return seg


def signature_block(sender: dict) -> str:
    for k in ("name", "title", "company", "website"):
        if not str(sender.get(k, "")).strip():
            raise CopyError(f"sender.{k} is required in copy_config.json")
    return f"{sender['name']}\n{sender['title']}, {sender['company']}\n{sender['website']}"


def build_sequence(cfg: dict, tdoc: dict) -> dict:
    sender = cfg.get("sender", {})
    sig = signature_block(sender)
    opt_out = (cfg.get("opt_out") or DEFAULT_OPT_OUT).strip()
    steps = []
    for step, tids in STEPS.items():
        variations = []
        for tid in tids:
            body = fill_template(tid, tdoc, cfg.get("slots", {}).get(tid, {}), cfg.get("plain", {}).get(tid, {}))
            full = f"{body}\n\n{sig}\n\n{opt_out}"
            subject = cfg.get("subjects", {}).get(tid, "")
            if step == "1" and not subject.strip():
                raise CopyError(f"{tid}: Email 1 needs a subject")
            variations.append({
                "template_id": tid,
                "variation": tid[1],
                "subject": subject,
                "body_text": full,
                "body_html": text_to_html(full),
                "merge_vars": sorted(merge_vars(full) | merge_vars(subject)),
            })
        steps.append({"step": int(step), "wait_time": int(cfg.get("wait_days", {}).get(step, 0 if step == "1" else 3)),
                      "variations": variations})
    return {"signature": sig, "opt_out": opt_out, "steps": steps}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default="copy_config.json")
    p.add_argument("--leads", default="verified_leads.csv", help="used for the preview and the merge var check")
    p.add_argument("--preview", type=int, default=3, help="number of leads to render in preview.md")
    p.add_argument("--out", default="sequence.json")
    p.add_argument("--preview-out", default="preview.md")
    a = p.parse_args(argv)
    cfg, tdoc = read_json(a.config), load_templates()
    try:
        seq = build_sequence(cfg, tdoc)
    except CopyError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    leads = read_csv(a.leads) if a.leads and Path(a.leads).exists() else []
    problems, lines = [], ["# Preview", ""]
    for i, lead in enumerate(leads):
        for st in seq["steps"]:
            for v in st["variations"]:
                subj, m1 = render(v["subject"], lead, cfg.get("sender"))
                body, m2 = render(v["body_text"], lead, cfg.get("sender"))
                for k in sorted(set(m1 + m2)):
                    problems.append(f"{lead.get('email')}: {v['template_id']} merge var {{{{{k}}}}} is empty or missing")
                if i < a.preview:
                    lines += [f"## {lead.get('email')} / Email {st['step']}{v['variation']}", "",
                              f"Subject: {subj or '(same thread, no subject)'}", "", "```", body, "```", ""]
    write_json(a.out, seq)
    Path(a.preview_out).write_text("\n".join(lines), encoding="utf-8")
    print(f"sequence -> {a.out} ({sum(len(s['variations']) for s in seq['steps'])} variations), preview -> {a.preview_out}")
    if problems:
        print("WARNING: some leads are missing merge var values (skill 11 will block launch):", file=sys.stderr)
        for pr in problems[:50]:
            print("  " + pr, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
