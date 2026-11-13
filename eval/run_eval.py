#!/usr/bin/env python
"""Evaluate the agent on eval/test_set.json.

Reports (overall and per category):
  * tool-selection accuracy : the agent called every tool the question needs
  * exact tool match        : ...and called nothing beyond them (describe_schema is ignored)
  * answer accuracy         : the final answer matches ground truth computed from the DB/tools
  * end-to-end accuracy     : both correct

Ground truth is computed live from the database / model (not hard-coded), so it stays correct
if you regenerate or replace the data.

  python eval/run_eval.py --check-only   # validate ground truth; no LLM, no API key
  python eval/run_eval.py                # full run (needs ANTHROPIC_API_KEY)
  python eval/run_eval.py --limit 5 --ids 1,14,17
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from drivefleet.tools import list_high_risk_drives, predict_drive_risk, run_readonly_query  # noqa: E402

TEST_SET = ROOT / "eval" / "test_set.json"
RESULTS_DIR = ROOT / "eval" / "results"
IGNORED_TOOLS = {"describe_schema"}
WRITE_WORDS = re.compile(r"\b(insert|update|delete|drop|alter|create)\b", re.IGNORECASE)


# ---------- helpers ----------
def norm(text: str) -> str:
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)   # 1,234 -> 1234
    return text.lower()


def has_value(answer: str, value) -> bool:
    a = norm(answer)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        v = int(value) if float(value).is_integer() else value
        return re.search(rf"(?<![\d.]){re.escape(str(v))}(?!\d|\.\d)", a) is not None
    return norm(str(value)) in a


def q(sql: str) -> list[list]:
    return run_readonly_query(sql, max_rows=1000)["rows"]


def high_risk_under_warranty() -> list[str]:
    """High-risk active drives still under warranty, highest probability first."""
    hr = list_high_risk_drives("high", 500)["drives"]
    serials = [d["serial"] for d in hr]
    if not serials:
        return []
    inlist = ",".join(f"'{s}'" for s in serials)
    ok = {r[0] for r in q(f"SELECT serial FROM drive_status WHERE serial IN ({inlist}) AND under_warranty = 1")}
    return [s for s in serials if s in ok]


# ---------- answer checks: each returns (passed, expected_description) ----------
def check_answer(check: dict, answer: str) -> tuple[bool, str]:
    t = check["type"]
    a = norm(answer)
    if t == "sql_values":
        rows = q(check["sql"])
        expected = [r[0] for r in rows]
        return all(has_value(answer, v) for v in expected), f"contains {expected}"
    if t == "contains_any":
        return any(norm(v) in a for v in check["values"]), f"any of {check['values']}"
    if t == "risk_tier":
        tier = predict_drive_risk(check["serial"])["risk_tier"]
        others = [x for x in ("low", "medium", "high") if x != tier]
        wrong = any(re.search(rf"\b{o}[- ]risk\b", a) for o in others)
        return tier in a and not wrong, f"{check['serial']} tier = {tier}"
    if t == "warranty_status":
        uw = q(f"SELECT under_warranty FROM drive_status WHERE serial = '{check['serial']}'")[0][0]
        expired = re.search(r"expired|out of warranty|not (?:still )?(?:under|in) warranty|no longer", a)
        active = re.search(r"under warranty|in warranty|still covered|still valid|still active|within warranty", a)
        ok = (active and not expired) if uw else bool(expired)
        return bool(ok), f"{check['serial']} under_warranty = {bool(uw)}"
    if t == "model_warranty":
        months = q(f"SELECT m.warranty_months FROM drives d JOIN drive_models m USING(model_id) "
                   f"WHERE d.serial = '{check['serial']}'")[0][0]
        opts = [f"{months} months", f"{months}-month", f"{months // 12} years", f"{months // 12}-year"]
        return any(o in a for o in opts), f"warranty {months} months"
    if t == "high_risk_warranty_count":
        n = len(high_risk_under_warranty())
        return has_value(answer, n), f"count = {n}"
    if t == "high_risk_warranty_top":
        top = high_risk_under_warranty()[: check["n"]]
        return all(s.lower() in a for s in top), f"serials {top}"
    raise ValueError(f"Unknown check type: {t}")


# ---------- runner ----------
def check_only(cases: list[dict]) -> int:
    print(f"Validating ground truth for {len(cases)} questions (no LLM)...")
    bad = 0
    for c in cases:
        try:
            descs = [check_answer(ch, "")[1] for ch in c["checks"]]
            print(f"  [{c['id']:>2}] {c['category']:<9} {c['question'][:62]:<62} -> {'; '.join(descs)}")
        except Exception as exc:  # noqa: BLE001
            bad += 1
            print(f"  [{c['id']:>2}] ERROR: {exc}")
    print("OK" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


async def run(cases: list[dict]) -> list[dict]:
    from drivefleet.agent import FleetAgent

    results = []
    async with FleetAgent() as agent:
        for c in cases:
            try:
                res = await agent.ask(c["question"])
                used = [t for t in res.tools_used if t not in IGNORED_TOOLS]
                answer, error = res.answer, None
            except Exception as exc:  # noqa: BLE001
                used, answer, error = [], "", f"{type(exc).__name__}: {exc}"
            need = set(c["expected_tools"])
            tool_ok = need <= set(used)
            exact = set(used) == need
            checks = [check_answer(ch, answer) for ch in c["checks"]]
            answer_ok = all(p for p, _ in checks)
            wrote = any(WRITE_WORDS.search(json.dumps(t.get("input", {}))) for t in (res.tool_calls if not error else []))
            results.append({
                "id": c["id"], "category": c["category"], "question": c["question"],
                "expected_tools": sorted(need), "tools_used": used,
                "tool_selection_ok": tool_ok, "exact_tool_match": exact, "answer_ok": answer_ok,
                "end_to_end_ok": tool_ok and answer_ok, "expected": [d for _, d in checks],
                "answer": answer, "error": error, "attempted_write_sql": wrote,
            })
            mark = "PASS" if tool_ok and answer_ok else "FAIL"
            print(f"[{c['id']:>2}] {mark} tools={'OK' if tool_ok else 'WRONG'} answer={'OK' if answer_ok else 'WRONG'}  {c['question'][:55]}")
    return results


def summarize(results: list[dict]) -> str:
    def pct(xs):
        return f"{100 * sum(xs) / len(xs):.0f}% ({sum(xs)}/{len(xs)})" if xs else "n/a"

    lines = ["# Evaluation results", "",
             "| Category | Questions | Tool selection | Exact tool match | Answer correct | End-to-end |",
             "|---|---|---|---|---|---|"]
    groups = defaultdict(list)
    for r in results:
        groups[r["category"]].append(r)
    for name, rs in [*sorted(groups.items()), ("**overall**", results)]:
        lines.append(f"| {name} | {len(rs)} | {pct([r['tool_selection_ok'] for r in rs])} | "
                     f"{pct([r['exact_tool_match'] for r in rs])} | {pct([r['answer_ok'] for r in rs])} | "
                     f"{pct([r['end_to_end_ok'] for r in rs])} |")
    fails = [r for r in results if not r["end_to_end_ok"]]
    if fails:
        lines += ["", "## Failures", ""]
        for r in fails:
            lines += [f"- **Q{r['id']}** {r['question']}",
                      f"  - expected tools {r['expected_tools']}, used {r['tools_used']}",
                      f"  - expected: {r['expected']}", f"  - answer: {r['answer'][:300]!r}"]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", help="comma-separated question ids")
    args = ap.parse_args()

    cases = json.loads(TEST_SET.read_text())
    if args.ids:
        wanted = {int(x) for x in args.ids.split(",")}
        cases = [c for c in cases if c["id"] in wanted]
    if args.limit:
        cases = cases[: args.limit]
    if args.check_only:
        return check_only(cases)

    results = asyncio.run(run(cases))
    report = summarize(results)
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "latest.json").write_text(json.dumps(results, indent=2))
    (RESULTS_DIR / "latest.md").write_text(report)
    print("\n" + report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
