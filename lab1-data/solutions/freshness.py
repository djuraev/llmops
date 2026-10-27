"""Reference solution for the freshness rule (Lab 1, step 4)."""


def apply_freshness_rule(docs):
    newest = {}
    for d in docs:
        current = newest.get(d["doc_id"])
        if current is None or d["valid_from"] > current["valid_from"]:
            newest[d["doc_id"]] = d
    kept = []
    for d in docs:
        winner = newest[d["doc_id"]]
        if winner is d:
            kept.append(d)
        else:
            d["decision"] = f"dropped: superseded by {winner['file']}"
    return kept
