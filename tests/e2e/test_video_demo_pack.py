"""视频演示数据包离线结构检查（BVD01-BVD18 中的结构项）。

只验证数据包结构，不写数据库、不调用模型。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PACK_DIR = Path(__file__).resolve().parents[2] / "evaluation" / "demo_pack"
PATIENTS_DIR = PACK_DIR / "patients"
MANIFEST = PACK_DIR / "manifest.json"

# 与 backend/app/services/records.py 的 KIND_SPEC 保持一致
KIND_RANGES = {
    "fasting_glucose": (2.0, 35.0),
    "postprandial_glucose": (2.0, 35.0),
    "steps": (0.0, 100000.0),
    "weight": (25.0, 300.0),
    "medication_taken": (0.0, 1.0),
    "symptom": None,
    "meal": None,
    "bp": None,
}

# 实际配置中存在的事件码（config/event_rules.yaml）
KNOWN_EVENTS = {
    "GLUCOSE_RISING", "HYPOGLYCEMIA_RECORD", "HYPERGLYCEMIA_RECORD",
    "LOW_ACTIVITY", "MEDICATION_NONADHERENCE",
}

PII_KEYS = {"phone", "mobile", "id_card", "address", "real_name", "身份证", "手机", "地址", "电话"}


def _load_all() -> list[dict]:
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(PATIENTS_DIR.glob("*.json"))]


def test_patient_ids_unique():
    pack = _load_all()
    ids = [p["patient"]["id"] for p in pack]
    assert len(ids) == len(set(ids)), "患者 ID 必须唯一"


def test_all_patients_synthetic():
    for p in _load_all():
        assert p["patient"].get("is_synthetic") is True, f"{p['patient']['id']} 必须 is_synthetic=true"


def test_patient_structure_valid():
    required = ["id", "name", "diabetes_type"]
    for p in _load_all():
        pat = p["patient"]
        for k in required:
            assert pat.get(k), f"{pat.get('id')} 缺少 {k}"


def test_record_kinds_supported():
    for p in _load_all():
        for r in p["records"]:
            assert r["kind"] in KIND_RANGES, f"{p['patient']['id']}: 不支持的记录类型 {r['kind']}"


def test_record_values_in_range():
    for p in _load_all():
        pid = p["patient"]["id"]
        for r in p["records"]:
            rng = KIND_RANGES.get(r["kind"])
            if rng is None:
                continue
            lo, hi = rng
            # VEDGE-202 的 99.9 是预期失败行，允许超范围
            if pid == "VEDGE-202" and r.get("value") == 99.9:
                continue
            assert lo <= r["value"] <= hi, f"{pid}: {r['kind']} 值 {r['value']} 超出 {lo}-{hi}"


def test_hours_ago_nonnegative():
    for p in _load_all():
        for r in p["records"]:
            assert r["hours_ago"] >= 0, f"{p['patient']['id']}: hours_ago 必须非负"


def test_record_count_matches_manifest():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    pack = _load_all()
    assert len(pack) == manifest["patient_count"]
    total = sum(len(p["records"]) for p in pack)
    assert total == manifest["record_count"]


def test_no_pii_fields():
    for p in _load_all():
        blob = json.dumps(p, ensure_ascii=False)
        for key in PII_KEYS:
            assert key not in blob, f"{p['patient']['id']}: 存在疑似 PII 字段 {key}"


def test_expected_events_are_known():
    for p in _load_all():
        for code in p.get("expected_event_codes", []):
            assert code in KNOWN_EVENTS, f"{p['patient']['id']}: 未知事件码 {code}"


def test_bp_and_symptom_payload():
    for p in _load_all():
        for r in p["records"]:
            if r["kind"] == "bp":
                pl = r.get("payload") or {}
                assert pl.get("systolic") and pl.get("diastolic"), "bp 需要 payload.systolic/diastolic"
            if r["kind"] == "symptom":
                pl = r.get("payload") or {}
                assert pl.get("text"), "symptom 需要 payload.text"
