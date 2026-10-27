"""Ask the bank bot one question with a chosen prompt, and let the judge check the answer.

  python3 ask.py "Can I get my transfer fee back?" --prompt v1
  python3 ask.py "Can I get my transfer fee back?" --prompt v2_friendly
"""
import argparse

import bankbot as bb
import evaluate as ev

ap = argparse.ArgumentParser()
ap.add_argument("question")
ap.add_argument("--prompt", default="v1")
args = ap.parse_args()
bb.banner()
bb.ensure_index()
r = bb.answer(args.question, system=bb.load_prompt(args.prompt))
score, why = ev.faithfulness(r["text"], r["contexts"])
print(f"PROMPT: {args.prompt}\nANSWER: {r['text']}\n")
print(f"Cites a source:  {'yes' if ev.CITATION.search(r['text']) else 'NO'}")
print(f"Faithfulness:    {score}/5  ({why})")
if score <= 3:
    print("!! The answer contains claims that are not in the bank's documents (hallucination).")
