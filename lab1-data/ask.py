"""Ask the bank bot a question using one of your index versions.

  python ask.py "How much does the Premium plan cost per month?" --version v1
"""
import argparse

import bankbot as bb

ap = argparse.ArgumentParser()
ap.add_argument("question")
ap.add_argument("--version", default="v1")
ap.add_argument("--show-prompt", action="store_true", help="print exactly what is sent to OpenAI")
args = ap.parse_args()
bb.banner()
try:
    r = bb.answer(args.question, version=args.version)
except FileNotFoundError:
    raise SystemExit(f"Build the index first: python pipeline.py --version {args.version}")
if args.show_prompt:
    sent = "\n".join(m["content"] for m in bb.build_messages(args.question, r["contexts"]))
    lines = [l for l in sent.splitlines() if bb.redact(l)[1]]
    print("Personal data SENT TO OPENAI in the prompt:")
    for l in lines:
        for pattern in bb.PII_PATTERNS.values():
            l = pattern.sub(lambda m: f">>>{m.group(0)}<<<", l)
        print("  " + l[:200])
    if not lines:
        print("  none")
    print()
answer_pii = bb.redact(r["text"])[1]
print("ANSWER:", r["text"])
if answer_pii:
    print("!! The answer itself contains personal data:", ", ".join(answer_pii))
print("\nWhat the bot was shown (retrieved chunks):")
for h in r["contexts"]:
    print(f"  {h['score']:.3f}  {h['source']:<24} valid from {h['valid_from']:<11} {h['text'][:60]!r}")

# Did the search hand the model two versions of the same document?
versions = {}
for h in r["contexts"]:
    versions.setdefault(h.get("doc_id", h["source"]), set()).add((h["valid_from"], h["source"]))
conflicts = {d: sorted(v) for d, v in versions.items() if len({date for date, _ in v}) > 1}
if conflicts:
    for doc_id, v in conflicts.items():
        print(f"\nWARNING: the bot was given {len(v)} versions of '{doc_id}': "
              + ", ".join(f"{src} (valid from {date})" for date, src in v))
    print("Whatever the answer says, the model had to guess which one is current. "
          "Next time it may guess wrong. Fix the index, not the model.")
else:
    print("\nNo conflicting document versions in what the bot was shown.")
