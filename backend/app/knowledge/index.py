"""F24 知识检索：索引有限、来源明确的健康管理资料，并支持段落级引用。"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from backend.app.config import KNOWLEDGE_DIR, ROOT
from backend.app.db.connection import iso, now

_RE_CJK = re.compile(r"[\u4e00-\u9fff]")
_RE_WORD = re.compile(r"[a-z0-9]+")


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            meta = yaml.safe_load(parts[1]) or {}
            return meta, parts[2].lstrip("\n")
    return {}, text


def _slug(heading: str) -> str:
    clean = re.sub(r"[^\w\u4e00-\u9fff]+", "-", heading).strip("-")
    return clean[:40] or "section"


def _chunk(body: str) -> list[dict[str, Any]]:
    """按二级标题切段，段内再按空行切块；每块保留标题与序号作为锚点。"""
    chunks: list[dict[str, Any]] = []
    sections = re.split(r"\n(?=## )", body)
    for sec in sections:
        lines = sec.strip().splitlines()
        if not lines:
            continue
        heading = lines[0][3:].strip() if lines[0].startswith("## ") else "概述"
        content = "\n".join(lines[1:]).strip() if lines[0].startswith("## ") else sec.strip()
        paras = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
        for i, para in enumerate(paras, start=1):
            chunks.append(
                {
                    "heading": heading,
                    "ordinal": len(chunks) + 1,
                    "anchor": f"#{_slug(heading)}-{i}",
                    "text": re.sub(r"\s+", " ", para).strip(),
                }
            )
    return chunks


def load_index_yaml() -> dict[str, Any]:
    path = KNOWLEDGE_DIR / "INDEX.yaml"
    if not path.exists():
        return {"docs": []}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"docs": []}


def ensure_index(conn: sqlite3.Connection, *, force: bool = False) -> dict[str, Any]:
    """把 knowledge/ 下的 Markdown 索引进数据库（按 checksum 判断是否需重建）。"""
    manifest = load_index_yaml()
    indexed = 0
    skipped = 0
    for doc in manifest.get("docs", []):
        path = ROOT / doc["path"] if not str(doc["path"]).startswith(str(ROOT)) else Path(doc["path"])
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8")
        meta, body = _split_front_matter(raw)
        checksum = _checksum(raw)
        row = conn.execute("SELECT * FROM knowledge_docs WHERE id=?", (doc["id"],)).fetchone()
        if row and row["checksum"] == checksum and not force:
            skipped += 1
            continue
        conn.execute("DELETE FROM knowledge_chunks WHERE doc_id=?", (doc["id"],))
        conn.execute(
            """INSERT INTO knowledge_docs(id,title,publisher,version,source_url,published_at,path,checksum)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET title=excluded.title,publisher=excluded.publisher,
                 version=excluded.version,source_url=excluded.source_url,published_at=excluded.published_at,
                 path=excluded.path,checksum=excluded.checksum""",
            (
                doc["id"],
                meta.get("title") or doc.get("title"),
                meta.get("publisher") or doc.get("publisher"),
                str(meta.get("version") or doc.get("version") or ""),
                meta.get("source_url") or doc.get("source_url"),
                str(meta.get("published_at") or ""),
                doc["path"],
                checksum,
            ),
        )
        for ch in _chunk(body):
            conn.execute(
                "INSERT INTO knowledge_chunks(id,doc_id,ordinal,anchor,heading,text) VALUES(?,?,?,?,?,?)",
                (f"{doc['id']}-C{ch['ordinal']:03d}", doc["id"], ch["ordinal"], ch["anchor"], ch["heading"], ch["text"]),
            )
        indexed += 1
    total = conn.execute("SELECT COUNT(*) AS c FROM knowledge_docs").fetchone()["c"]
    return {"indexed": indexed, "unchanged": skipped, "documents": total, "at": iso(now(conn))}


def documents(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM knowledge_docs ORDER BY id").fetchall()
    out = []
    for r in rows:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM knowledge_chunks WHERE doc_id=?", (r["id"],)
        ).fetchone()["c"]
        out.append({**dict(r), "chunks": count})
    return out
