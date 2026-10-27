"""Lab 4, part 2: shadow-test a candidate prompt on real traffic before it ships (Chapter 9).

  python shadow.py                              # candidate prompts/v2_fun.txt vs production answers
  python shadow.py --candidate v1_short --n 15

Replays questions captured in traces/traces.jsonl through the candidate. Customers never see the
candidate's answers; we only compare them with what production actually said.
"""
import argparse
import json
import re
import statistics

import bankbot as bb
from monitor import read
from pricing import cost

BRAND = """You review replies from a bank's customer-support chatbot. A reply FAILS if it mocks or criticises the bank,
insults anyone, uses profanity or slang, gives personal opinions, or makes jokes about money problems.
Return JSON only: {"ok": true|false, "reason": "<short>"}"""
OFF_BRAND = re.compile(r"(ridiculous|stupid|terrible|awful|hate|damn|honestly, between us|lol|sucks)", re.I)


def brand_ok(text):
    if bb.BACKEND == "openai":
        r = bb.chat([{"role": "system", "content": BRAND}, {"role": "user", "content": text}],
                    model=bb.JUDGE_MODEL, temperature=0, max_tokens=80, json_mode=True)
        try:
            return bool(json.loads(r["text"]).get("ok", False))
        except ValueError:
            return False
    return not OFF_BRAND.search(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate", default="v2_fun")
    ap.add_argument("--n", type=int, default=20)
    args = ap.parse_args()
    bb.banner()
    bb.ensure_index()
    seen, prod = set(), []
    for t in read()[0]:
        if not t.get("blocked") and not t.get("error") and t["input"] not in seen:
            seen.add(t["input"])
            prod.append(t)
    prod = prod[:args.n]
    if not prod:
        raise SystemExit("No production traces: run `python monitor.py serve` and `python monitor.py load` first.")
    system = bb.load_prompt(args.candidate)
    rows = []
    for t in prod:
        r = bb.answer(t["input"], system=system)
        rows.append({"q": t["input"], "prod": t["output"], "cand": r["text"],
                     "prod_ok": brand_ok(t["output"]), "cand_ok": brand_ok(r["text"]),
                     "prod_cost": t.get("cost_usd", 0), "cand_cost": cost(r["model"], r["tokens_in"], r["tokens_out"]),
                     "prod_cite": bool(re.search(r"\[[\w.\-]+\.md\]", t["output"])),
                     "cand_cite": bool(re.search(r"\[[\w.\-]+\.md\]", r["text"]))})
        print(f"{'ok ' if rows[-1]['cand_ok'] else 'BAD'} {t['input'][:70]}", flush=True)
    n = len(rows)
    pv, cv = sum(not r["prod_ok"] for r in rows), sum(not r["cand_ok"] for r in rows)
    pc, cc = statistics.mean(r["prod_cost"] for r in rows), statistics.mean(r["cand_cost"] for r in rows)
    print(f"\n{'':<24}{'production v1':>15}{'candidate ' + args.candidate:>22}")
    print(f"{'off-brand replies':<24}{pv:>15}{cv:>22}")
    print(f"{'replies with citation':<24}{sum(r['prod_cite'] for r in rows):>15}{sum(r['cand_cite'] for r in rows):>22}")
    print(f"{'$ per 1,000 requests':<24}{pc * 1000:>15.4f}{cc * 1000:>22.4f}")
    reasons = []
    if cv > pv:
        reasons.append(f"{cv - pv} more off-brand replies than production")
    if sum(r["cand_cite"] for r in rows) < sum(r["prod_cite"] for r in rows) - 0.1 * n:
        reasons.append("fewer grounded (cited) answers")
    if pc and cc > pc * 1.2:
        reasons.append("more than 20% more expensive")
    print(f"\nDecision: {'HOLD: ' + '; '.join(reasons) if reasons else 'SHIP: no regressions found on this traffic'}")
    bad = [r for r in rows if not r["cand_ok"]][:2]
    for r in bad:
        print(f"\nExample candidate reply that failed review:\n  Q: {r['q']}\n  A: {r['cand'][:300]}")


if __name__ == "__main__":
    main()
