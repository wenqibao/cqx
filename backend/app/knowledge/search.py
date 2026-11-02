"""F24 检索与证据约束：查询有限知识包，返回可定位出处；无结果时明确拒绝臆测。"""
from __future__ import annotations

import math
import sqlite3
from typing import Any

from backend.app.db.connection import dumps, iso, loads, now
from backend.app.knowledge.index import _RE_CJK, _RE_WORD, ensure_index, load_index_yaml
from backend.app.util import new_id

STOP_CHARS = set("的了是在和与及或而也都就还你他我们这那一个有些可以被把对于为以等")


def tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    tokens: list[str] = []
    words = _RE_WORD.findall(text)
    tokens.extend(w for w in words if len(w) > 1)
    cjk_runs = _RE_CJK.findall(text)
    # 逐字 + 双字组合，覆盖中文关键词
    chars = "".join(cjk_runs)
    tokens.extend(ch for ch in chars if ch not in STOP_CHARS)
    for i in range(len(chars) - 1):
        bi = chars[i : i + 2]
        if bi[0] not in STOP_CHARS and bi[1] not in STOP_CHARS:
            tokens.append(bi)
    return tokens


def _score(query_tokens: list[str], text: str, df: dict[str, int], total: int) -> float:
    if not query_tokens:
        return 0.0
    body = text.lower()
    score = 0.0
    for tok in set(query_tokens):
        if tok in body:
            idf = math.log((total + 1) / (df.get(tok, 0) + 1)) + 1.0
            score += idf * (1.5 if len(tok) > 1 else 0.5)
    return round(score, 4)


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    top_k: int | None = None,
    min_score: float | None = None,
) -> dict[str, Any]:
    cfg = load_index_yaml().get("retrieval", {})
    top_k = top_k or int(cfg.get("top_k", 4))
    min_score = float(cfg.get("min_score", 1.0)) if min_score is None else min_score
    ensure_ready(conn)
    rows = conn.execute(
        """SELECT c.id AS chunk_id, c.doc_id, c.anchor, c.heading, c.text, d.title, d.publisher,
                  d.version, d.source_url, d.published_at
           FROM knowledge_chunks c JOIN knowledge_docs d ON d.id = c.doc_id"""
    ).fetchall()
    tokens = tokenize(query)
    df: dict[str, int] = {}
    for r in rows:
        body = (r["heading"] or "") + " " + r["text"]
        for tok in set(tokens):
            if tok in body:
                df[tok] = df.get(tok, 0) + 1
    scored = []
    for r in rows:
        body = (r["heading"] or "") + " " + r["text"]
        s = _score(tokens, body, df, max(len(rows), 1))
        if s >= min_score:
            scored.append((s, r))
    scored.sort(key=lambda t: t[0], reverse=True)
    hits = [
        {
            "chunk_id": r["chunk_id"],
            "doc_id": r["doc_id"],
            "title": r["title"],
            "publisher": r["publisher"],
            "version": r["version"],
            "source_url": r["source_url"],
            "published_at": r["published_at"],
            "anchor": r["anchor"],
            "heading": r["heading"],
            "quote": r["text"][:280],
            "score": s,
        }
        for s, r in scored[:top_k]
    ]
    return {
        "query": query,
        "hits": hits,
        "found": bool(hits),
        "note": None
        if hits
        else "知识包中没有足够相关的已核对资料，系统不对该问题给出结论。",
        "searched_at": iso(now(conn)),
    }


def ensure_ready(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) AS c FROM knowledge_chunks").fetchone()["c"]
    if count == 0:
        ensure_index(conn)


def record_evidence(
    conn: sqlite3.Connection,
    *,
    patient_id: str | None,
    run_id: str | None,
    hits: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    """把检索命中固化为证据条目，供轨迹与报告引用。"""
    created = []
    for hit in hits:
        eid = new_id("evidence")
        conn.execute(
            """INSERT INTO evidence_items(id,patient_id,run_id,doc_id,chunk_id,anchor,quote,score,query,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                eid,
                patient_id,
                run_id,
                hit["doc_id"],
                hit["chunk_id"],
                f"{hit['doc_id']}{hit['anchor']}",
                hit["quote"],
                hit["score"],
                query,
                iso(now(conn)),
            ),
        )
        created.append(
            {
                "id": eid,
                "doc_id": hit["doc_id"],
                "title": hit["title"],
                "publisher": hit["publisher"],
                "anchor": hit["anchor"],
                "citation": f"{hit['title']}·{hit['publisher']}·{hit['anchor']}",
                "quote": hit["quote"],
                "score": hit["score"],
            }
        )
    return created


def evidence_for_run(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT e.*, d.title, d.publisher, d.source_url FROM evidence_items e
           JOIN knowledge_docs d ON d.id = e.doc_id WHERE e.run_id=? ORDER BY e.score DESC""",
        (run_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "doc_id": r["doc_id"],
            "title": r["title"],
            "publisher": r["publisher"],
            "source_url": r["source_url"],
            "anchor": r["anchor"],
            "quote": r["quote"],
            "score": r["score"],
            "citation": f"{r['title']}·{r['publisher']}·{r['anchor']}",
        }
        for r in rows
    ]


def citation_label(hit: dict[str, Any]) -> str:
    return f"{hit['title']}（{hit['publisher']}，{hit.get('version') or ''}）{hit['anchor']}"
