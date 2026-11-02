"""F24 知识检索与证据约束。"""
from __future__ import annotations

from backend.app.knowledge import search as knowledge
from backend.app.knowledge.index import documents, ensure_index


def test_index_builds_all_docs(conn):
    summary = ensure_index(conn, force=True)
    assert summary["documents"] == 4
    docs = documents(conn)
    assert {d["id"] for d in docs} == {"KD-001", "KD-002", "KD-003", "KD-004"}
    for doc in docs:
        assert doc["publisher"]
        assert doc["source_url"].startswith("http")
        assert doc["chunks"] > 0


def test_search_returns_citable_hits(conn):
    ensure_index(conn)
    result = knowledge.search(conn, "为什么需要连续记录血糖")
    assert result["found"] is True
    top = result["hits"][0]
    assert top["anchor"].startswith("#")
    assert top["publisher"]
    assert len(top["quote"]) > 10
    assert top["score"] > 0


def test_search_without_match_refuses(conn):
    ensure_index(conn)
    result = knowledge.search(conn, "量子纠缠与超导材料能谱")
    assert result["found"] is False
    assert result["hits"] == []
    assert "没有" in (result["note"] or "")


def test_evidence_is_persisted(conn):
    ensure_index(conn)
    result = knowledge.search(conn, "低血糖 识别")
    saved = knowledge.record_evidence(
        conn, patient_id="P001", run_id="RUN-test", hits=result["hits"], query="低血糖"
    )
    assert saved
    assert saved[0]["citation"].count("·") >= 1
    listed = knowledge.evidence_for_run(conn, "RUN-test")
    assert len(listed) == len(saved)
    assert listed[0]["source_url"]
