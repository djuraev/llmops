"""Lab 4, part 3: cut the bill without cutting quality.

  python cost.py compare            # four strategies on the same traffic
  python cost.py compare --eval     # plus a correctness score for each
  python cost.py breakeven          # paying OpenAI per token vs renting a GPU
"""
import argparse
import json
import math
import re
import statistics

import numpy as np

import bankbot as bb
from pricing import PRICES, cost

# Real traffic repeats itself: paraphrases and exact repeats of popular questions.
PARAPHRASES = {"transfers-daily-001": "How much money can I send card to card in one day?",
               "plan-premium-005": "What is the monthly fee of the Premium plan?",
               "reissue-008": "If I reissue my card, how long does it take and how much does it cost?",
               "cashback-010": "Which plan has 2% cashback in cafes and restaurants?"}
JUDGE = """Grade a bank chatbot ANSWER against EXPECTED facts/behaviour, 1-5 (5 = all facts or exactly the expected
behaviour; 1 = wrong or guesses). Any language or wording is fine. Return JSON only: {"score": <1-5>}"""


def traffic(limit):
    cases = [json.loads(l) for l in (bb.ROOT / "data" / "golden_set.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    seq = []
    for c in cases[:limit] if limit else cases:
        seq.append(c)
        if c["id"] in PARAPHRASES:
            seq += [{**c, "question": PARAPHRASES[c["id"]]}, dict(c)]
    return seq


def correctness(case, ans):
    if bb.BACKEND == "openai":
        r = bb.chat([{"role": "system", "content": JUDGE}, {"role": "user", "content":
                     f"QUESTION: {case['question']}\nTYPE: {case['type']}\nEXPECTED: {case['expected_facts']}\nANSWER: {ans}"}],
                    model=bb.JUDGE_MODEL, temperature=0, max_tokens=30, json_mode=True)
        try:
            return (int(json.loads(r["text"])["score"]) - 1) / 4
        except (ValueError, KeyError, TypeError):
            return 0.0
    declined = bool(re.search(r"(don.t have|can only help)", ans, re.I))
    if case["type"] in ("out_of_scope", "safety") and not case.get("must_cite"):
        return 1.0 if declined else 0.0
    nums = [n for f in case["expected_facts"] for n in re.findall(r"\d+", f.replace(",", ""))]
    return 1.0 if nums and all(n in ans.replace(",", "") for n in nums) else (0.5 if not nums and not declined else 0.0)


def rec(case, r, cached=False):
    return {"case": case, "model": r["model"], "text": r["text"], "cached": cached,
            "in": 0 if cached else r["tokens_in"], "out": 0 if cached else r["tokens_out"]}


def baseline(seq, a):
    """What the bank runs today: the large model, 4 chunks, long answers allowed."""
    sysm = bb.load_prompt("v1")
    return [rec(c, bb.answer(c["question"], system=sysm, model=bb.LARGE_MODEL, max_tokens=300)) for c in seq]


def trimmed(seq, a):
    sysm = bb.load_prompt("v1_short")
    return [rec(c, bb.answer(c["question"], system=sysm, model=bb.LARGE_MODEL, k=2, max_tokens=120)) for c in seq]


def cache(seq, a):
    store, out, sysm = [], [], bb.load_prompt("v1")
    for c in seq:
        q = np.asarray(bb.embed([c["question"]])[0], dtype=np.float64)
        q /= max(float(np.linalg.norm(q)), 1e-9)
        best = max(((float(bb.cosine_scores(v[None, :], q)[0]), r) for v, r in store), default=(-1, None), key=lambda x: x[0])
        if best[1] is not None and best[0] >= a.cache_threshold:
            out.append(rec(c, best[1], cached=True))
            continue
        r = bb.answer(c["question"], system=sysm, model=bb.LARGE_MODEL, hits=bb.retrieve(c["question"], query_vector=q))
        store.append((q, r))
        out.append(rec(c, r))
    return out


def route(seq, a):
    """Small model when search is confident and the question is short, large model otherwise."""
    out, sysm = [], bb.load_prompt("v1")
    for c in seq:
        hits = bb.retrieve(c["question"])
        easy = hits[0]["score"] >= a.min_score and len(c["question"]) <= 80
        out.append(rec(c, bb.answer(c["question"], system=sysm, model=bb.SMALL_MODEL if easy else bb.LARGE_MODEL, hits=hits)))
    return out


def compare(a):
    bb.ensure_index()
    seq = traffic(a.limit)
    rpd = PRICES["traffic"]["requests_per_day"]
    print(f"{len(seq)} requests per strategy · large {bb.LARGE_MODEL} · small {bb.SMALL_MODEL}\n")
    rows = []
    for name, fn in {"baseline": baseline, "trimmed": trimmed, "cache": cache, "route": route}.items():
        print(f"running {name} ...", flush=True)
        recs = fn(seq, a)
        total = sum(cost(r["model"], r["in"], r["out"]) for r in recs)
        live = [r for r in recs if not r["cached"]] or recs
        row = {"strategy": name, "tok_in": round(statistics.mean(r["in"] for r in live)),
               "tok_out": round(statistics.mean(r["out"] for r in live)), "cache_hits": sum(r["cached"] for r in recs),
               "small": sum(r["model"] == bb.SMALL_MODEL and not r["cached"] for r in recs),
               "usd_1k": total / len(recs) * 1000, "usd_month": total / len(recs) * rpd * 30}
        if a.eval:
            row["correct"] = statistics.mean(correctness(r["case"], r["text"]) for r in recs)
        rows.append(row)
    print(f"\n{'strategy':<10}{'tok in':>8}{'tok out':>8}{'cached':>7}{'small':>6}{'$/1k req':>10}{'$/month':>10}" + ("  correct" if a.eval else ""))
    for r in rows:
        print(f"{r['strategy']:<10}{r['tok_in']:>8}{r['tok_out']:>8}{r['cache_hits']:>7}{r['small']:>6}{r['usd_1k']:>10.3f}{r['usd_month']:>10.0f}"
              + (f"  {r['correct']:.2f}" if a.eval else ""))
    print(f"\n$/month assumes {rpd} requests/day (prices.yaml). Embedding costs are tiny and left out.")
    (bb.ROOT / "cost_latest.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


def breakeven(a):
    sh = PRICES["self_hosting"]
    tin, tout = 700, 80
    p = bb.ROOT / "cost_latest.json"
    if p.exists():
        b = json.loads(p.read_text())[0]
        tin, tout = b["tok_in"], b["tok_out"]
    gpu = a.gpu if a.gpu is not None else sh["gpu_monthly_usd"]
    per = cost(bb.LARGE_MODEL, tin, tout)
    print(f"API: ${per:.5f} per request on {bb.LARGE_MODEL} ({tin} in / {tout} out tokens)")
    print(f"Self-hosted: ${gpu}/GPU/month for {sh['requests_per_gpu_per_month']:,} requests + ops ${sh['ops_monthly_usd']}/month\n")
    print(f"{'requests/month':>15}{'API $':>10}{'self-host $':>13}  cheaper")
    for v in (10_000, 100_000, 250_000, 500_000, 1_000_000, 2_000_000, 5_000_000):
        api, own = v * per, math.ceil(v / sh["requests_per_gpu_per_month"]) * gpu + sh["ops_monthly_usd"]
        print(f"{v:>15,}{api:>10,.0f}{own:>13,.0f}  {'API' if api < own else 'self-host'}")
    print(f"\nBreak-even ≈ {(gpu + sh['ops_monthly_usd']) / per:,.0f} requests/month (one GPU). Also weigh data residency, "
          "engineering time, and whether an open model passes your golden set.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compare")
    c.add_argument("--eval", action="store_true")
    c.add_argument("--limit", type=int)
    c.add_argument("--cache-threshold", type=float, default=0.80 if bb.BACKEND == "mock" else 0.92)
    c.add_argument("--min-score", type=float, default=0.30 if bb.BACKEND == "mock" else 0.45)
    sub.add_parser("breakeven").add_argument("--gpu", type=float)
    a = ap.parse_args()
    bb.banner()
    compare(a) if a.cmd == "compare" else breakeven(a)
