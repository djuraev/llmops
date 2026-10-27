"""Lab 1, exercise 5: the same questions against the raw index (v0), the cleaned one (v1)
and the cleaned + fresh one (v2). Look at the answers AND at what the bot was given.

  python demo.py
  python demo.py --versions v0 v2
"""
import argparse
import re

import bankbot as bb
from pipeline import TARGET_LANG

QUESTIONS = [
    "How much does the Premium plan cost per month?",
    "How much does a card reissue cost and how long does it take?",
    "Why was the customer's payment declined in the support transcript?",
]
LABELS = {"v0": "raw, no cleaning", "v1": "cleaned", "v2": "cleaned + fresh"}


def data_problems(hits):
    """What was wrong with the chunks the bot was given?"""
    problems = []
    pii = {}
    for h in hits:
        for k, v in bb.redact(h["text"])[1].items():
            pii[k] = pii.get(k, 0) + v
    if pii:
        problems.append("personal data sent to the model (" + ", ".join(sorted(pii)) + ")")
    texts = [" ".join(h["text"].lower().split()) for h in hits]
    files_per_doc = {}
    for h in hits:
        files_per_doc.setdefault((h.get("doc_id"), h["valid_from"]), set()).add(h["source"])
    if len(set(texts)) < len(texts) or any(len(f) > 1 for f in files_per_doc.values()):
        problems.append("duplicate page")
    if any(h.get("status") == "draft" for h in hits):
        problems.append("unfinished draft")
    langs = sorted({h.get("lang", TARGET_LANG) for h in hits} - {TARGET_LANG})
    if langs:
        problems.append("outdated translation (" + ", ".join(langs) + ")")
    if any("\ufffd" in h["text"] for h in hits):
        problems.append("garbled characters")
    versions = {}
    for h in hits:
        versions.setdefault(h.get("doc_id", h["source"]), set()).add(h["valid_from"])
    for doc_id, dates in versions.items():
        if len(dates) > 1:
            problems.append(f"{len(dates)} versions of '{doc_id}' ({', '.join(sorted(dates))})")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--versions", nargs="+", default=["v0", "v1", "v2"])
    args = ap.parse_args()
    bb.banner()
    for v in args.versions:
        try:
            bb.load_index(v)
        except FileNotFoundError:
            raise SystemExit(f"Index '{v}' is missing. Build it first (see the README, exercises 1-4).")
    for q in QUESTIONS:
        print("=" * 100)
        print(f"Q: {q}")
        for v in args.versions:
            r = bb.answer(q, version=v)
            problems = data_problems(r["contexts"])
            leaked = bb.redact(r["text"])[1]
            print(f"\n  [{v} · {LABELS.get(v, '')}]")
            print(f"  A: {r['text'][:300]}")
            print(f"  shown: {', '.join(sorted({h['source'] for h in r['contexts']}))}")
            print(f"  data problems: {'; '.join(problems) if problems else 'none'}")
            if leaked:
                print(f"  !! the ANSWER itself contains personal data: {', '.join(leaked)}")
        print()
    print("Same model, same prompt, same questions. The only thing that changed is the data.")


if __name__ == "__main__":
    main()
