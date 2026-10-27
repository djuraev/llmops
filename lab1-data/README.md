# Lab 1: Prepare the bank's knowledge base (30 min)

**Book:** Chapter 4, Data Engineering for LLMs · **Industry anchor:** Samsung, 2023

MoliyaBank (a fictional Uzbek bank) wants a support chatbot. Its documents in `data/raw/` are
realistically messy: personal data in a transcript, a duplicated page, an outdated Russian
translation, a draft, an old price list and a file saved in the wrong encoding.

## Setup (5 min)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp env.example .env              # Windows: copy env.example .env  -> paste your OpenAI key
```

No key yet? Everything still runs on an offline mock model, which is fine for practising.

## Steps

1. **The "before" picture: index everything as-is.**
   `python pipeline.py --raw --version v0`
   No cleaning at all. Note the last line: how much personal data is now inside the index?
   Ask: `python ask.py "Why was the customer's payment declined in the support transcript?" --version v0`
   Look at the chunks the bot was shown: card and phone numbers were just sent to OpenAI.
2. **Run the cleaning pipeline.** `python pipeline.py` (builds v1)
   Read the report: which step dropped each file, and why? Find `[PHONE]` in `index/v1/chunks.json`.
   **Privacy check.** `python3 ask.py "What contact details did the customer give in the support transcript?" --version v0 --show-prompt`
   prints the exact prompt sent to OpenAI with personal data marked `>>> <<<`. Run the same command
   with `--version v1`: the same places now say `[PHONE]`, `[CARD]`, `[PINFL]`.
3. **Find what cleaning missed.**
   `python ask.py "How much does the Premium plan cost per month?" --version v1`
   Read the chunk list and the warning: an old marketing page (39,000 UZS, 2025) and the current
   tariff list (49,000 UZS, 2026) both reached the model. It passed every cleaning step, because it
   is clean, unique and in English. Even if the answer looks right, the model had to guess.
4. **Add the rule.** Implement `apply_freshness_rule()` in `pipeline.py` so only the newest version
   of each `doc_id` survives, then `python pipeline.py --version v2`.
   Stuck? `python pipeline.py --version v2 --solution` uses the reference in `solutions/`.
5. **Before and after.** `python demo.py` asks the same three questions against v0, v1 and v2.
   Same model, same prompt: the only difference is the data. For each version, read the answer
   and the "data problems" line.
6. **Chunking and the manifest.** `python pipeline.py --version v3 --strategy fixed --size 60 --solution`,
   then ask the price question with `--version v3`: where did the tariff table end up? Finally open
   `manifests/index_manifest_v2.json`: could a classmate rebuild exactly this index from it?

## You leave with

Three indexes of the same documents (raw, cleaned, cleaned + fresh), proof of what cleaning removed, and a manifest that records exactly what went into the final one.

## Discussion

Which of the ten pipeline steps would have stopped the Samsung leak? Which steps matter for
training data but not for a retrieval system?

**Costs:** embedding these files with `text-embedding-3-small` costs a fraction of a cent.
