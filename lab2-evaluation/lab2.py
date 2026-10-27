"""Lab 2, interactive: evaluate MoliyaBot with a golden set and a quality gate.

  python3 lab2.py

Pick actions from the menu. Everything is saved in the same places as evaluate.py
(eval/baseline.json, reports/eval_latest.json, data/my_cases.jsonl), so both tools work together.
"""
import json
import re
from datetime import datetime, timezone

import bankbot as bb
import evaluate as ev

LINE = "-" * 70


def ask(prompt, default=None):
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def pause():
    input("\nPress Enter to return to the menu...")


def prompts():
    return sorted(p.stem for p in bb.PROMPTS_DIR.glob("*.txt"))


def choose_prompt():
    names = prompts()
    print("Prompts: " + ", ".join(names))
    name = ask("Which prompt", "v1")
    if name not in names:
        print(f"No prompt called '{name}', using v1.")
        name = "v1"
    return name


def run_suite(prompt_name, limit=None):
    """Run the golden set (+ my_cases.jsonl) and save the report. Returns (summary, results)."""
    system = bb.load_prompt(prompt_name)
    cases = ev.load_cases(limit)
    print(f"\nRunning {len(cases)} test questions with prompt '{prompt_name}'. Each answer is graded by the judge.\n")
    results = []
    for i, case in enumerate(cases, 1):
        r = ev.run_case(case, system)
        results.append(r)
        mark = "pass" if r["passed"] else "FAIL"
        print(f"  {i:>2}/{len(cases)} {mark}  faithful {r['faithfulness']}/5  correct {r['correctness']}/5  {case['question'][:48]}", flush=True)
    summary = ev.summarize(results)
    run = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "prompt": prompt_name,
           "backend": bb.BACKEND, "chat_model": bb.CHAT_MODEL, "judge_model": bb.JUDGE_MODEL,
           "summary": summary, "cases": results}
    ev.REPORTS.mkdir(exist_ok=True)
    (ev.REPORTS / "eval_latest.json").write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    return run


def show_summary(summary, base=None):
    names = {"faithfulness": "Sticks to the documents", "correctness": "Contains the right facts",
             "context_recall": "Search found the right page", "citation_rate": "Cites its source",
             "language_match": "Replies in the user's language"}
    print(f"\n{'':<32}{'now':>8}{'approved':>10}")
    for m in ev.GATED:
        b = base.get(m) if base else None
        fmt = lambda v: "-" if v is None else f"{v:.0%}"
        print(f"{names[m]:<32}{fmt(summary[m]):>8}{fmt(b):>10}")
    print(f"Critical cases failing: {', '.join(summary['critical_failed']) or 'none'}")


# ------------------------------------------------------------------ menu actions
def action_ask():
    print("\nAsk the bot anything. The judge then checks whether the answer sticks to the documents.")
    q = ask("Question")
    if not q:
        return
    name = choose_prompt()
    r = bb.answer(q, system=bb.load_prompt(name))
    f, why = ev.faithfulness(r["text"], r["contexts"])
    print(f"\n{LINE}\nANSWER: {r['text']}\n{LINE}")
    print(f"Pages the bot read: {', '.join(sorted({h['source'] for h in r['contexts']}))}")
    print(f"Cites a source: {'yes' if ev.CITATION.search(r['text']) else 'NO'}")
    print(f"Faithfulness: {f}/5  ({why})")
    if f <= 3:
        print("-> Low score: the answer contains claims that are not in the bank's documents (a hallucination).")
    pause()


def action_baseline():
    print("\nThe baseline is the approved quality level. Later changes are compared against it.")
    name = choose_prompt()
    limit = ask("How many questions (Enter = all)", "")
    run = run_suite(name, int(limit) if limit.isdigit() else None)
    show_summary(run["summary"])
    if ask("\nSave this as the approved baseline? (y/n)", "y").lower().startswith("y"):
        ev.BASELINE.write_text(json.dumps({k: v for k, v in run.items() if k != "cases"}, indent=2, ensure_ascii=False), encoding="utf-8")
        print("Saved to eval/baseline.json.")
    pause()


def action_gate():
    if not ev.BASELINE.exists():
        print("\nNo baseline yet. Choose option 2 first.")
        return pause()
    print("\nTest a change: run the same questions with another prompt and compare with the baseline.")
    name = choose_prompt()
    limit = ask("How many questions (Enter = all)", "")
    base = json.loads(ev.BASELINE.read_text(encoding="utf-8"))
    run = run_suite(name, int(limit) if limit.isdigit() else None)
    show_summary(run["summary"], base["summary"])
    fails = ev.gate(run["summary"], base["summary"], 0.05)
    if fails:
        print("\nGATE FAILED: this change would be blocked before reaching customers.")
        for f in fails:
            print("  -", f)
        bad = min(run["cases"], key=lambda c: (c["faithfulness"], c["correctness"]))
        print(f"\nWorst answer:\n  Q: {bad['question']}\n  A: {bad['answer'][:300]}\n  Judge: {bad['faithfulness_reason']}")
    else:
        print("\nGATE PASSED: quality is at least as good as the approved baseline.")
    pause()


def action_inspect():
    p = ev.REPORTS / "eval_latest.json"
    if not p.exists():
        print("\nNo results yet. Run option 2 or 3 first.")
        return pause()
    run = json.loads(p.read_text(encoding="utf-8"))
    cases = sorted(run["cases"], key=lambda c: (c["passed"], c["faithfulness"] + c["correctness"]))
    print(f"\nLast run (prompt '{run['prompt']}'), weakest first:")
    for i, c in enumerate(cases, 1):
        print(f"  {i:>2}. {'pass' if c['passed'] else 'FAIL'}  F{c['faithfulness']} C{c['correctness']}  {c['question'][:55]}")
    pick = ask("Number to inspect (Enter = back)", "")
    if not pick.isdigit() or not 1 <= int(pick) <= len(cases):
        return
    c = cases[int(pick) - 1]
    print(f"\n{LINE}\nQuestion:  {c['question']}\nAnswer:    {c['answer']}\n{LINE}")
    print(f"Pages read:   {', '.join(c['retrieved'])}")
    print(f"Faithfulness {c['faithfulness']}/5: {c['faithfulness_reason']}")
    print(f"Correctness  {c['correctness']}/5: {c['correctness_reason']}")
    recall = c["checks"]["context_recall"]
    if recall is False:
        print("-> Diagnosis: the SEARCH failed (the right page was never found). Fix chunking or retrieval.")
    elif c["correctness"] < 4:
        print("-> Diagnosis: the right page was found, but the MODEL answered badly. Fix the prompt or model.")
    else:
        print("-> This answer looks fine.")
    pause()


def action_add_case():
    print("\nTurn a real failure into a test (every failure becomes a test case).")
    print("Example (Air Canada style): 'I paid a fee for a wrong transfer last week. Can I get the fee back now?'")
    q = ask("Customer question")
    if not q:
        return
    kind = ask("Type: factual / procedural / out_of_scope / safety", "factual")
    facts = [f.strip() for f in ask("Facts a correct answer must contain (separate with ;)",
                                     "transfer fees are never refunded").split(";") if f.strip()]
    cite = ask("Document it should cite (Enter = none)", "transfers-policy.md")
    critical = ask("Critical? A failure blocks every release (y/n)", "y").lower().startswith("y")
    lang = "ru" if re.search(r"[\u0400-\u04FF]", q) else "en"
    case = {"id": f"my-{datetime.now().strftime('%H%M%S')}", "question": q, "lang": lang, "type": kind,
            "expected_facts": facts, "must_cite": [cite] if cite else [], "critical": critical}
    with open(ev.DATA / "my_cases.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(case, ensure_ascii=False) + "\n")
    print(f"Saved to data/my_cases.jsonl as {case['id']}. Testing it now...")
    r = ev.run_case(case, bb.load_prompt("v1"))
    print(f"\nAnswer: {r['answer']}\nCorrectness {r['correctness']}/5: {r['correctness_reason']}  ->  {'PASS' if r['passed'] else 'FAIL'}")
    pause()


def action_write_prompt():
    print("\nWrite your own system prompt, then test it with option 3. End with an empty line.")
    print("Tip: start from v1 and remove or change ONE rule, so you can see its effect.")
    lines = []
    while True:
        line = input("> ")
        if not line:
            break
        lines.append(line)
    if lines:
        name = ask("Name for this prompt", "my_prompt")
        (bb.PROMPTS_DIR / f"{name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Saved as prompts/{name}.txt")
    pause()


MENU = [
    ("Ask the bot a question (with a live faithfulness check)", action_ask),
    ("Run the golden set and save the approved baseline", action_baseline),
    ("Test a change against the baseline (quality gate)", action_gate),
    ("Inspect answers from the last run (weakest first)", action_inspect),
    ("Add your own test case (e.g. the Air Canada case)", action_add_case),
    ("Write a new prompt to test", action_write_prompt),
]


def main():
    bb.banner()
    bb.ensure_index()
    while True:
        print(f"\n{LINE}\nLAB 2 · Evaluation and quality gate\n{LINE}")
        for i, (label, _) in enumerate(MENU, 1):
            print(f"  {i}. {label}")
        print("  0. Exit")
        choice = ask("Choose")
        if choice == "0":
            break
        if choice.isdigit() and 1 <= int(choice) <= len(MENU):
            try:
                MENU[int(choice) - 1][1]()
            except KeyboardInterrupt:
                print("\nCancelled.")
        else:
            print("Please type a number from the menu.")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nBye.")
