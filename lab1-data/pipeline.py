"""Lab 1: prepare the bank's knowledge base, following the preprocessing pipeline of Chapter 4.

  python pipeline.py --raw --version v0                # NO cleaning: every file as-is (the "before" picture)
  python pipeline.py                                   # cleaned index v1
  python pipeline.py --version v2 --solution           # cleaned + freshness rule (reference solution)
  python pipeline.py --version v3 --strategy fixed --size 60 --solution
  python demo.py                                       # same questions against v0, v1 and v2
"""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import bankbot as bb

RAW = bb.ROOT / "data" / "raw"
TARGET_LANG = "en"          # this index serves the English knowledge base
MIN_WORDS = 30              # shorter documents are treated as junk


def sha256(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def decode(raw):
    """Step 6: detect encoding. Try UTF-8 first, then the common Windows code page."""
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp1252"), "cp1252 (converted)"


def detect_language(text):
    """Step 7: a small rule-based detector for the languages our customers use."""
    cyr = len(re.findall(r"[\u0400-\u04FF]", text))
    lat = len(re.findall(r"[A-Za-z]", text))
    if cyr > lat:
        return "uz-cyrl" if re.search(r"[ўқғҳЎҚҒҲ]", text) else "ru"
    words = set(re.findall(r"[a-z']+", text.lower()))
    if len(words & {"va", "uchun", "bilan", "qanday", "mumkin", "emas", "kerak", "haqida"}) >= 2:
        return "uz-latn"
    return "en"


def shingles(text, n=5):
    w = re.findall(r"\w+", text.lower())
    return {" ".join(w[i:i + n]) for i in range(max(1, len(w) - n + 1))}


def apply_freshness_rule(docs):
    """TODO (Lab 1, exercise 4): keep only the NEWEST version of each doc_id.

    Each document is a dict with keys like "file", "doc_id", "valid_from" (YYYY-MM-DD) and "decision".
    Return the list of documents to keep. For each document you drop, set
    d["decision"] = "dropped: superseded by <file of the newer version>".
    Hint: ISO dates compare correctly as strings: "2026-09-01" > "2025-09-01".
    """
    return docs


def clean(docs, args):
    """Steps 2, 3, 4, 7 and the freshness rule. Returns (documents to index, redaction totals)."""
    total = {}
    for d in docs:                                            # Step 2: privacy
        d["body"], d["pii"] = bb.redact(d["body"])
        for k, v in d["pii"].items():
            total[k] = total.get(k, 0) + v
    print("2. Privacy: redacted", ", ".join(f"{k}={v}" for k, v in sorted(total.items())) or "nothing")
    for d in docs:                                            # Step 3: filter
        if d["status"] == "draft" or len(d["body"].split()) < MIN_WORDS:
            d["decision"] = "dropped: draft or too short"
    kept_sh = []                                              # Step 4: deduplicate
    for d in docs:
        if d["decision"] != "kept":
            continue
        sh = shingles(d["body"])
        twin = next((f for f, osh in kept_sh if len(sh & osh) / max(1, len(sh | osh)) >= 0.8), None)
        if twin:
            d["decision"] = f"dropped: near-duplicate of {twin}"
        else:
            kept_sh.append((d["file"], sh))
    for d in docs:                                            # Step 7: language
        if d["decision"] == "kept" and d["lang"] != TARGET_LANG:
            d["decision"] = f"dropped: language {d['lang']}, needs translation review"
    live = [d for d in docs if d["decision"] == "kept"]
    seen = {}
    for d in live:
        seen.setdefault(d["doc_id"], []).append(d["file"])
    for doc_id, files in seen.items():
        if len(files) > 1:
            print(f"   WARNING: {len(files)} documents share doc_id '{doc_id}': {', '.join(files)}")
    if args.solution:
        from solutions.freshness import apply_freshness_rule as rule
    else:
        rule = apply_freshness_rule
    return rule(live), total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", default="v1")
    ap.add_argument("--raw", action="store_true", help="skip all cleaning steps (builds the 'before' index)")
    ap.add_argument("--strategy", choices=["heading", "fixed"], default="heading")
    ap.add_argument("--size", type=int, default=60, help="words per chunk (fixed strategy)")
    ap.add_argument("--overlap", type=int, default=10)
    ap.add_argument("--solution", action="store_true", help="use solutions/freshness.py")
    args = ap.parse_args()
    bb.banner()

    # Steps 1 + 5: catalog and collect (and step 6, encoding, unless --raw)
    docs = []
    for path in sorted(RAW.glob("*.md"), key=lambda p: ("copy" in p.stem, p.name)):
        raw = path.read_bytes()
        if args.raw:
            text, encoding = raw.decode("utf-8", errors="replace"), "read as-is"
        else:
            text, encoding = decode(raw)
        meta, body = bb.read_front_matter(text)
        docs.append({"file": path.name, "sha256": sha256(raw), "doc_id": meta.get("doc_id", path.stem),
                     "valid_from": meta.get("valid_from", ""), "status": meta.get("status", "final"),
                     "encoding": encoding, "body": body, "lang": detect_language(body), "pii": {}, "decision": "kept"})
    print(f"1. Catalog: {len(docs)} files in data/raw")

    if args.raw:
        print("RAW MODE: no privacy, filter, deduplication, encoding, language or freshness steps.")
        live, total = docs, {}
        for d in docs:
            d["pii"] = bb.redact(d["body"])[1]          # counted for the report, NOT removed
            d["decision"] = "kept (no cleaning)"
    else:
        live, total = clean(docs, args)

    print("\n   file                     decision                                     lang     encoding")
    for d in docs:
        print(f"   {d['file']:<24} {d['decision'][:44]:<44} {d['lang']:<8} {d['encoding']}")

    # Step 8: chunk
    chunks = []
    for d in live:
        body = bb.linearize_tables(d["body"])
        pieces = bb.chunk_by_heading(body) if args.strategy == "heading" else bb.chunk_fixed(body, args.size, args.overlap)
        for i, (section, text) in enumerate(pieces):
            chunks.append({"id": f"{Path(d['file']).stem}-{i}", "text": text, "source": d["file"],
                           "doc_id": d["doc_id"], "status": d["status"], "lang": d["lang"],
                           "section": section, "valid_from": d["valid_from"]})
    lengths = [len(c["text"].split()) for c in chunks]
    print(f"\n8. Chunk: {len(chunks)} chunks ({args.strategy}), {min(lengths)}-{max(lengths)} words each")

    vectors = bb.embed([c["text"] for c in chunks])
    manifest = {"version": args.version, "cleaned": not args.raw,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "embedder": bb.embedder_id(), "chunking": {"strategy": args.strategy, "size": args.size, "overlap": args.overlap},
                "documents": [{k: d[k] for k in ("file", "doc_id", "valid_from", "sha256", "lang", "encoding", "pii", "decision")} for d in docs],
                "chunks": len(chunks), "pii_redacted": total}
    bb.save_index(args.version, chunks, vectors, manifest)
    # Steps 9 + 10: back up and maintain
    out = bb.ROOT / "manifests"
    out.mkdir(exist_ok=True)
    (out / f"index_manifest_{args.version}.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"9. Back up: index saved to index/{args.version}/, manifest to manifests/index_manifest_{args.version}.json")
    print("10. Maintain: re-run this pipeline whenever a file in data/raw changes, with a new --version")
    if args.raw:
        print(f"\nPersonal data left IN this index: "
              + (", ".join(f"{k}={v}" for d in docs for k, v in d["pii"].items()) or "none"))


if __name__ == "__main__":
    main()
