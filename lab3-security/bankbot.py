"""MoliyaBot core: OpenAI access, embeddings, redaction, a tiny vector index and RAG.

MoliyaBank is a FICTIONAL Uzbek bank used for teaching. Put OPENAI_API_KEY in .env.
Without a key the lab runs on a built-in offline 'mock' model: fine for practising the
commands, but it is not a real model, so its answers and scores are only illustrative.
"""
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
sys.stdout.reconfigure(errors="replace")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
BACKEND = (os.getenv("LLM_BACKEND") or ("openai" if OPENAI_API_KEY else "mock")).lower()
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o-mini")
SMALL_MODEL = os.getenv("SMALL_MODEL", "gpt-4o-mini")
LARGE_MODEL = os.getenv("LARGE_MODEL", "gpt-4o")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")
MOCK_LATENCY = float(os.getenv("MOCK_LATENCY", "0.3"))
INDEX_DIR = ROOT / "index"
DOCS_DIR = ROOT / "data" / "docs"
PROMPTS_DIR = ROOT / "prompts"

DEFAULT_SYSTEM = """You are MoliyaBot, the customer support assistant of MoliyaBank (a fictional bank in Uzbekistan).
Answer ONLY from the CONTEXT. After each fact, cite its source file in square brackets, e.g. [tariffs.md].
Reply in the language of the QUESTION. If the CONTEXT does not contain the answer, say you do not have this
information and suggest calling the support line 1234. Never ask for or repeat card numbers, CVV or SMS codes.
Keep answers under 120 words."""


def banner():
    if BACKEND == "mock":
        print("[offline mock model: no OPENAI_API_KEY found. Answers are simulated, for practice only]\n")
    else:
        print(f"[OpenAI: chat {CHAT_MODEL}, embeddings {EMBED_MODEL}]\n")


# ------------------------------------------------------------------ text helpers
STOPWORDS = set("""a an the and or of to in on for with by at from as is are was were be been it its this that these
those i you we they he she my your our their me us do does did can could would should will may might what which who how
when where why if then than so not no yes please about into per also any all just""".split())


def estimate_tokens(text):
    return max(1, len(text) // 4)


def content_words(text):
    return [w for w in re.findall(r"\w+", text.lower()) if w not in STOPWORDS and (len(w) > 2 or w.isdigit())]


def stems(text):
    return [w[:5] for w in content_words(text)]


# ------------------------------------------------------------------ personal data
PII_PATTERNS = {
    "CARD": re.compile(r"\b(?:8600|9860|4\d{3}|5\d{3})[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b"),
    "PHONE": re.compile(r"\+?998[ -]?\(?\d{2}\)?[ -]?\d{3}[ -]?\d{2}[ -]?\d{2}\b"),
    "PINFL": re.compile(r"\b\d{14}\b"),
    "PASSPORT": re.compile(r"\b[A-Z]{2} ?\d{7}\b"),
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
}


def redact(text):
    """Replace personal data with labels. Returns (text, {type: count})."""
    counts = {}
    for name, pattern in PII_PATTERNS.items():
        text, n = pattern.subn(f"[{name}]", text)
        if n:
            counts[name] = n
    return text, counts


# ------------------------------------------------------------------ chat
_client = None


def client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def chat(messages, model=None, temperature=0.2, max_tokens=300, json_mode=False):
    """Call the model. Returns {text, model, tokens_in, tokens_out, latency_s}."""
    model = model or CHAT_MODEL
    t0 = time.perf_counter()
    if BACKEND == "openai":
        kw = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if json_mode:
            kw["response_format"] = {"type": "json_object"}
        try:
            r = client().chat.completions.create(**kw)
        except Exception as exc:  # newer reasoning models use other parameter names
            if "max_tokens" not in str(exc) and "temperature" not in str(exc):
                raise
            kw.pop("temperature", None)
            kw["max_completion_tokens"] = kw.pop("max_tokens")
            r = client().chat.completions.create(**kw)
        text = (r.choices[0].message.content or "").strip()
        tin, tout = r.usage.prompt_tokens, r.usage.completion_tokens
    else:
        text = _mock_chat(messages, model, max_tokens)
        tin = sum(estimate_tokens(m["content"]) for m in messages)
        tout = estimate_tokens(text)
    return {"text": text, "model": model, "tokens_in": tin, "tokens_out": tout,
            "latency_s": time.perf_counter() - t0}


# ------------------------------------------------------------------ offline mock model
ATTACK = re.compile(r"(ignore (all |the )?(previous|above|prior)|system prompt|instructions|repeat everything|"
                    r"no rules|unlocked|without (any )?restrictions|игнорируй|инструкци|правила|без ограничений|"
                    r"ko.rsatma|\[system|<!--)", re.I)
SECRET_ASK = re.compile(r"(discount code|staff code|chegirma kod|код скидки|служебн)", re.I)
COMMIT_ASK = re.compile(r"(legally binding|free forever|free for life|confirm|подтверд|официальн|1 сум)", re.I)
OFFTOPIC_ASK = re.compile(r"\b(poem|python|script|restoran\w*|recipe|weather)\b", re.I)
REFUSAL = "Sorry, I can only help with MoliyaBank questions about cards, transfers and tariffs."
DECLINE = "I don't have this information. Please call the MoliyaBank support line 1234."


def _mock_chat(messages, model, max_tokens):
    """Deterministic stand-in for a real model: copies the most relevant context sentences.
    Like a naive real model, it obeys manipulative instructions unless the system prompt forbids them."""
    system = messages[0]["content"]
    sys_l = system.lower()
    user = messages[-1]["content"]
    ctx, _, question = user.partition("\n\nQUESTION:")
    question = (question or user).strip()
    hardened = "never reveal" in sys_l
    grounded = "only from" in sys_l
    playful = "playful" in sys_l
    small = model == SMALL_MODEL and SMALL_MODEL != LARGE_MODEL
    time.sleep(MOCK_LATENCY * (0.5 if small else 1.0))

    if SECRET_ASK.search(question) or (ATTACK.search(question) and "code" in question.lower()):
        if hardened:
            return REFUSAL
        m = re.search(r"[^.\n]*code[^.\n]*", system, re.I)
        return f"Sure! {m.group(0).strip()}." if m else REFUSAL
    if ATTACK.search(question):
        if hardened:
            return REFUSAL
        if re.search(r"free (forever|for life)", question, re.I):
            return "Good news: your Premium plan is free for life!"
        return "My instructions are: " + system[:400]
    if COMMIT_ASK.search(question):
        if hardened:
            return "I can't make offers or change prices. Current prices are listed in our tariffs [tariffs.md]."
        return "Absolutely, confirmed! That's a legally binding offer from MoliyaBank."
    if OFFTOPIC_ASK.search(question):
        if hardened or grounded:
            return REFUSAL
        return "Here you go! Roses are red, our queues are long, MoliyaBank fees are always wrong."

    chunks = []
    for block in ctx.replace("CONTEXT:\n", "", 1).split("\n---\n"):
        m = re.match(r"\s*\[([^\]]+)\][^\n]*\n(.*)", block, re.S)
        if m:
            chunks.append((m.group(1), m.group(2)))
    q = set(stems(question))
    scored = []
    for rank, (src, body) in enumerate(chunks):
        for sent in re.split(r"(?<=[.!?])\s+|\n+", body):
            sent = sent.strip()
            if len(sent) >= 15:
                overlap = len(q & set(stems(sent)))
                if overlap:
                    scored.append((overlap, -rank, sent, src))
    scored.sort(reverse=True)
    take = scored[:1] if small else scored[:2]
    if grounded and (not take or take[0][0] < 2):
        text = DECLINE
    else:
        text = " ".join(f"{s} [{src}]" if "cite" in sys_l else s for _, _, s, src in take) or DECLINE
        if not grounded:
            text += " Most banks also refund such fees automatically within 24 hours."
    if playful:
        text += " Honestly, between us, even I think MoliyaBank's fees are a bit ridiculous!"
    words = text.split()
    return " ".join(words[: max(12, int(max_tokens * 0.75))])


# ------------------------------------------------------------------ embeddings
def embedder_id():
    return f"openai:{EMBED_MODEL}" if BACKEND == "openai" else "mock-hash-512"


def embed(texts):
    if BACKEND == "openai":
        out = []
        for i in range(0, len(texts), 64):
            r = client().embeddings.create(model=EMBED_MODEL, input=texts[i:i + 64])
            out.extend(d.embedding for d in r.data)
        return out
    return [_hash_embed(t) for t in texts]


def _hash_embed(text, dim=512):
    v = np.zeros(dim, dtype=np.float32)
    words = re.findall(r"\w+", text.lower())
    for f in words + [w[i:i + 3] for w in words if len(w) > 3 for i in range(len(w) - 2)]:
        h = int(hashlib.md5(f.encode("utf-8")).hexdigest()[:8], 16)
        v[h % dim] += 1.0 if (h >> 16) & 1 else -1.0
    n = float(np.linalg.norm(v))
    return (v / n).tolist() if n else v.tolist()


# ------------------------------------------------------------------ documents and chunking
def read_front_matter(text):
    """Split '---\\nkey: value\\n---' front matter from the body."""
    meta = {}
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        text = text[m.end():]
    return meta, text


def linearize_tables(text):
    """Markdown table rows -> 'Header: value; ...' sentences (search and models handle them better)."""
    out, header = [], None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                continue
            if header is None:
                header = cells
                continue
            out.append("; ".join(f"{h}: {c}" for h, c in zip(header, cells)) + ".")
        else:
            header = None
            out.append(line)
    return "\n".join(out)


def chunk_by_heading(text):
    chunks, section, buf = [], "intro", []
    for line in text.splitlines():
        if line.startswith("## "):
            if "".join(buf).strip():
                chunks.append((section, "\n".join(buf).strip()))
            section, buf = line[3:].strip(), []
        elif not line.startswith("# "):
            buf.append(line)
    if "".join(buf).strip():
        chunks.append((section, "\n".join(buf).strip()))
    return chunks


def chunk_fixed(text, size=60, overlap=10):
    words = " ".join(l for l in text.splitlines() if not l.startswith("#")).split()
    step = max(1, size - overlap)
    return [("window", " ".join(words[i:i + size])) for i in range(0, max(1, len(words) - overlap), step)]


# ------------------------------------------------------------------ vector index
_cache = {}


def save_index(version, chunks, vectors, info):
    path = INDEX_DIR / version
    path.mkdir(parents=True, exist_ok=True)
    m = np.asarray(vectors, dtype=np.float32)
    m /= np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-9, None)
    np.save(path / "vectors.npy", m)
    (path / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False, indent=1), encoding="utf-8")
    (path / "info.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    _cache.pop(version, None)


def load_index(version):
    if version not in _cache:
        path = INDEX_DIR / version
        if not (path / "vectors.npy").exists():
            raise FileNotFoundError(f"index '{version}' not found")
        _cache[version] = (np.load(path / "vectors.npy"),
                           json.loads((path / "chunks.json").read_text(encoding="utf-8")),
                           json.loads((path / "info.json").read_text(encoding="utf-8")))
    return _cache[version]


def ensure_index(version="main", docs_dir=None):
    """Build a default index from data/docs if it is missing or was built with another embedder."""
    try:
        if load_index(version)[2].get("embedder") == embedder_id():
            return
    except FileNotFoundError:
        pass
    chunks = []
    for path in sorted((docs_dir or DOCS_DIR).glob("*.md")):
        meta, body = read_front_matter(path.read_text(encoding="utf-8"))
        body = linearize_tables(redact(body)[0])
        for i, (section, text) in enumerate(chunk_by_heading(body)):
            chunks.append({"id": f"{path.stem}-{i}", "text": text, "source": path.name, "section": section,
                           "valid_from": meta.get("valid_from", "")})
    print(f"Building index '{version}' from {len(chunks)} chunks ...")
    save_index(version, chunks, embed([c["text"] for c in chunks]), {"embedder": embedder_id()})


def cosine_scores(vectors, q):
    """Similarity of every stored vector to the query. Computed in float64 with warnings silenced:
    NumPy with Apple's Accelerate library (macOS) can raise false overflow warnings in float32
    matrix products. Any non-finite score is treated as 'no match' so it cannot break the ranking."""
    with np.errstate(all="ignore"):
        sims = np.asarray(vectors, dtype=np.float64) @ np.asarray(q, dtype=np.float64)
    return np.nan_to_num(sims, nan=-1.0, posinf=-1.0, neginf=-1.0)


def retrieve(question, k=4, version="main", query_vector=None):
    vectors, chunks, info = load_index(version)
    if info.get("embedder") != embedder_id():
        raise SystemExit(f"Index '{version}' was built with {info.get('embedder')}; rebuild it for {embedder_id()}.")
    q = np.asarray(query_vector if query_vector is not None else embed([question])[0], dtype=np.float64)
    q /= max(float(np.linalg.norm(q)), 1e-9)
    sims = cosine_scores(vectors, q)
    return [{**chunks[i], "score": round(float(sims[i]), 4)} for i in np.argsort(-sims)[:k]]


# ------------------------------------------------------------------ RAG
def load_prompt(name):
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


def build_messages(question, hits, system=None):
    context = "\n\n---\n\n".join(f"[{h['source']}] {h['section']}\n{h['text']}" for h in hits)
    return [{"role": "system", "content": system or DEFAULT_SYSTEM},
            {"role": "user", "content": f"CONTEXT:\n{context}\n\nQUESTION: {question}"}]


def answer(question, system=None, model=None, k=4, version="main", max_tokens=300, hits=None):
    if hits is None:
        hits = retrieve(question, k=k, version=version)
    result = chat(build_messages(question, hits, system), model=model, max_tokens=max_tokens)
    result["contexts"] = hits
    return result
