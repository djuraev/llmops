# Lab 2: Build a quality gate (30 min)

**Book:** Chapter 3 (did the prompt change help?) and Chapter 7 (evaluation) · **Industry anchor:** Air Canada, 2024

## Setup

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp env.example .env                                     # paste your OpenAI key
```

The bot answers with `CHAT_MODEL` and a second model (`JUDGE_MODEL`) grades every answer with a
1–5 rubric. A full run is 14 questions × 3 calls; with gpt-4o-mini that costs about a cent.

## Steps

1. **Look at the golden set.** Open `data/golden_set.jsonl`. Each line is one test: a customer
   question, the facts a correct answer must contain, the document it should cite, and whether it
   is critical. 14 tests in Uzbek, Russian and English.
2. **Ask the good bot (prompt v1):**
   `python3 ask.py "I paid a 0.5% fee on a transfer to the wrong card last week. Can I get the fee refunded if I apply now?" --prompt v1`
   It says fees are never refunded, cites `transfers-policy.md`, and gets a faithfulness score of 5/5.
3. **Ask the "friendly" bot (prompt v2_friendly):**
   `python3 ask.py "I paid a 0.5% fee on a transfer to the wrong card last week. Can I get the fee refunded if I apply now?" --prompt v2_friendly`
   This prompt drops the rule "answer only from the documents". The answer becomes vague or
   invents a refund possibility: the Air Canada mistake. Faithfulness drops and `!!` flags it.
   (Compare the two files in `prompts/`: one missing sentence changed the product.)
4. **Save the baseline (approved quality):** `python3 evaluate.py --save-baseline`
   All 14 tests run; a second model (the judge) grades each answer. Scores go to `eval/baseline.json`.
5. **Find the weakest answer.** Open `reports/eval_latest.json`, find the lowest score, read the
   judge's reason. Did the search fail (`context_recall` false) or the model?
6. **The quality gate:** `python3 evaluate.py --prompt v2_friendly`
   Same tests, new prompt. Expected: **GATE FAILED** with the reasons (faithfulness and citation
   rate dropped). This change would be blocked before reaching customers.
7. **Every failure becomes a test.** Turn the Air Canada mistake into a permanent test:
   `cp data/my_cases.example.jsonl data/my_cases.jsonl` (Windows: `copy`), then run
   `python3 evaluate.py --prompt v2_friendly` again. The new critical test fails, so the gate
   blocks the change on its own. With `--prompt v1` it passes.
8. **Automation.** Read `.gitlab-ci.yml`: the same check runs automatically before every release.

Quick run on a slow connection: add `--limit 5` to any `evaluate.py` command.

**Key message:** a prompt is code. Change one sentence and the product changes, so every change
must pass the golden set before customers see it.

## Discussion

The judge is also a model. Pick one judge reason in the report you disagree with. Who should
check the judge, and how often?
