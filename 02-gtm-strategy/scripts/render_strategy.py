#!/usr/bin/env python3
"""Validate strategy.json and render strategy.md from it.

The agent writes strategy.json using templates/strategy.template.json and
prompt.md. This script checks every required field is present (and that
there are exactly 3 front-end offers), then renders a readable
strategy.md. Exits 1 with a list of problems if validation fails.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from gtm_common import read_json  # noqa: E402

REQUIRED_TOP = ["company", "core_offer", "icp", "personas", "pains", "front_end_offers", "proof_points"]
REQUIRED_ICP = ["icp_text", "industries", "employee_range", "countries"]


def validate(s: dict) -> list[str]:
    errs = [f"missing `{k}`" for k in REQUIRED_TOP if not s.get(k)]
    icp = s.get("icp") or {}
    errs += [f"missing `icp.{k}`" for k in REQUIRED_ICP if not icp.get(k)]
    feo = s.get("front_end_offers") or []
    if len(feo) != 3:
        errs.append(f"need exactly 3 front_end_offers, found {len(feo)}")
    for i, o in enumerate(feo, 1):
        for k in ("name", "what_they_get", "piece_of_core_offer", "cta"):
            if not o.get(k):
                errs.append(f"front_end_offers[{i}] missing `{k}`")
    for i, p in enumerate(s.get("personas") or [], 1):
        for k in ("persona", "titles"):
            if not p.get(k):
                errs.append(f"personas[{i}] missing `{k}`")
    for i, p in enumerate(s.get("proof_points") or [], 1):
        if not p.get("source"):
            errs.append(f"proof_points[{i}] has no `source` (only use proof you can point to)")
    return errs


def bullets(items) -> str:
    return "\n".join(f"- {x}" for x in items or [])


def render(s: dict) -> str:
    c, o, icp = s["company"], s["core_offer"], s["icp"]
    out = [
        f"# GTM strategy: {c.get('name', '')}",
        f"Website: {c.get('url', '')}\n",
        "## Core offer",
        f"**{o.get('name', '')}**: {o.get('one_liner', '')}",
        f"Outcome: {o.get('outcome', '')}",
        f"Price point: {o.get('price_point', 'n/a')}\n",
        "## ICP",
        icp["icp_text"],
        f"- Industries: {', '.join(icp['industries'])}",
        f"- Employees: {icp['employee_range']}",
        f"- Countries: {', '.join(icp['countries'])}",
        f"- Exclude: {', '.join(icp.get('exclude', []) or ['none'])}\n",
        "## Personas",
    ]
    for p in s["personas"]:
        out += [f"### {p['persona']}", f"Titles: {', '.join(p['titles'])}", bullets(p.get("cares_about")), ""]
    out += ["## Pains"]
    for p in s["pains"]:
        out.append(f"- **{p.get('pain', '')}** ({p.get('persona', 'all')}): {p.get('cost_of_inaction', '')}")
    out += ["", "## Front-end offers (cold traffic)"]
    for i, f in enumerate(s["front_end_offers"], 1):
        out += [f"### {i}. {f['name']}", f"- What they get: {f['what_they_get']}",
                f"- Piece of the core offer: {f['piece_of_core_offer']}", f"- CTA: {f['cta']}", ""]
    out += ["## Proof points"]
    for p in s["proof_points"]:
        out.append(f"- {p.get('claim', '')} (source: {p['source']})")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", default="strategy.json")
    ap.add_argument("--out", default="strategy.md")
    a = ap.parse_args(argv)
    s = read_json(a.inp)
    errs = validate(s)
    if errs:
        print("strategy.json is not ready:\n" + bullets(errs))
        return 1
    Path(a.out).write_text(render(s), encoding="utf-8")
    print(f"OK -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
