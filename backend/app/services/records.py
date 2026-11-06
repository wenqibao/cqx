"""F03 健康数据录入与导入（CSV / JSON 回放）。"""
from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime
from typing import Any, Iterable

from backend.app.db.connection import dumps, iso, loads, now, parse_ts
from backend.app.services.patients import get_patient
from backend.app.util import normalize_kind, safe_float, short_hash

# 允许的健康记录类型与默认单位；未列出的 kind 会被拒绝，避免脏数据进入状态计算
KIND_SPEC: dict[str, dict[str, Any]] = {
    "fasting_glucose": {"label": "空腹血糖", "unit": "mmol/L", "value_required": True, "range": (2.0, 35.0)},
    "postprandial_glucose": {"label": "餐后血糖", "unit": "mmol/L", "value_required": True, "range": (2.0, 35.0)},
    "steps": {"label": "步数", "unit": "步", "value_required": True, "range": (0.0, 100000.0)},
    "weight": {"label": "体重", "unit": "kg", "value_required": True, "range": (25.0, 300.0)},
    "medication_taken": {"label": "服药确认", "unit": "", "value_required": True, "range": (0.0, 1.0)},
    "symptom": {"label": "症状记录", "unit": "", "value_required": False, "range": None},
    "meal": {"label": "饮食记录", "unit": "", "value_required": False, "range": None},
    "bp": {"label": "血压", "unit": "mmHg", "value_required": False, "range": None},
}


class RecordValidationError(ValueError):
    pass


def _validate(kind: str, value: float | None, payload: dict[str, Any] | None) -> None:
    spec = KIND_SPEC[kind]
    if spec["value_required"] and value is None:
        raise RecordValidationError(f"{kind} 需要数值型 value")
    lo_hi = spec.get("range")
    if value is not None and lo_hi:
        lo, hi = lo_hi
        if not (lo <= value <= hi):
            raise RecordValidationError(f"{kind} 数值 {value} 超出合理范围 {lo}-{hi}")
    if kind == "bp":
        payload = payload or {}
        if safe_float(payload.get("systolic")) is None or safe_float(payload.get("diastolic")) is None:
            raise RecordValidationError("bp 记录需要 payload.systolic / payload.diastolic")
    if kind == "symptom" and not (payload or {}).get("text"):
        raise RecordValidationError("symptom 记录需要 payload.text")


def _recorded_at(raw: Any, fallback: datetime) -> str:
    if raw is None or raw == "":
        return iso(fallback)
    dt = parse_ts(str(raw))
    if dt is None:
        raise RecordValidationError(f"recorded_at 不是合法时间: {raw}")
    return iso(dt)


# 参与"同一观察"判定的 payload 字段：血压、症状、药名、标签
OBSERVATION_KEYS = ("text", "systolic", "diastolic", "medication_name", "tags")


def _norm_number(value: Any) -> str:
    """数值规范化：120 / 120.0 / "120.00" 视为同一值。"""
    number = safe_float(value)
    if number is None:
        return ""
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{round(number, 3):.3f}".rstrip("0").rstrip(".")


def _norm_text(value: Any) -> str:
    return " ".join(str(value).split())


def canonical_observation(kind: str, value: Any, payload: dict[str, Any] | None) -> str:
    """把一条记录归一化成"这次到底观察到了什么"，用于去重键。

    BUG A-WB-02：原先只把 value 与 payload.text 放入去重键，血压的 value 恒为 None，
    同一分钟 120/80 与 130/85 会算出同一个键而被 INSERT OR IGNORE 吞掉。
    """
    payload = payload or {}
    parts = [_norm_number(value)]
    for key in OBSERVATION_KEYS:
        raw = payload.get(key)
        if raw in (None, "", []):
            continue
        if key in ("systolic", "diastolic"):
            parts.append(f"{key}={_norm_number(raw)}")
        elif key == "tags":
            parts.append(f"tags={_norm_text(raw)}")
        else:
            parts.append(f"{key}={_norm_text(raw)}")
    return "|".join(parts)


def _dedupe_keys(patient_id: str, kind: str, ts: str, value: Any, payload: dict[str, Any]) -> tuple[str, str]:
    """返回 (新键, 兼容旧键)。旧键用于升级前已有数据的幂等兼容。"""
    canonical = canonical_observation(kind, value, payload)
    new_key = short_hash(f"{patient_id}|{kind}|{ts[:16]}|{canonical}"[:400])
    legacy_key = short_hash(f"{patient_id}|{kind}|{ts[:16]}|{value}|{payload.get('text', '')}"[:400])
    return new_key, legacy_key


def add_record(
    conn: sqlite3.Connection,
    patient_id: str,
    data: dict[str, Any],
    *,
    allow_duplicate: bool = False,
) -> dict[str, Any]:
    """写入一条健康记录；同一患者、同一分钟、同一组观察值重复写入会被幂等跳过。"""
    get_patient(conn, patient_id)
    kind = normalize_kind(data.get("kind", ""))
    if kind not in KIND_SPEC:
        raise RecordValidationError(f"不支持的健康记录类型: {data.get('kind')!r}")
    payload = dict(data.get("payload") or {})
    for extra in ("text", "systolic", "diastolic", "medication_name", "tags"):
        if extra in data and extra not in payload:
            payload[extra] = data[extra]
    value = safe_float(data.get("value"))
    _validate(kind, value, payload)
    ts = _recorded_at(data.get("recorded_at"), now(conn))
    dedupe = None
    legacy_key = None
    if not allow_duplicate:
        explicit = data.get("dedupe_key")
        if explicit:
            dedupe = explicit
        else:
            dedupe, legacy_key = _dedupe_keys(patient_id, kind, ts, value, payload)
    if dedupe and not allow_duplicate:
        # 升级兼容：旧版本写入的行只带旧键，若同一观察已存在，仍按重复处理。
        candidates = [dedupe] + ([legacy_key] if legacy_key and legacy_key != dedupe else [])
        placeholders = ",".join("?" for _ in candidates)
        for row in conn.execute(
            f"SELECT * FROM health_records WHERE patient_id=? AND dedupe_key IN ({placeholders})",
            (patient_id, *candidates),
        ).fetchall():
            if canonical_observation(row["kind"], row["value"], loads(row["payload"], {})) == canonical_observation(
                kind, value, payload
            ):
                record = row_to_record(row)
                record["duplicate"] = True
                return record
    cur = conn.execute(
        """INSERT OR IGNORE INTO health_records(patient_id,kind,value,unit,recorded_at,source,note,payload,dedupe_key,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            patient_id,
            kind,
            value,
            data.get("unit") or KIND_SPEC[kind]["unit"],
            ts,
            data.get("source", "manual"),
            data.get("note"),
            dumps(payload) if payload else None,
            dedupe,
            iso(now(conn)),
        ),
    )
    if cur.rowcount == 0 and dedupe:
        row = conn.execute(
            "SELECT * FROM health_records WHERE patient_id=? AND dedupe_key=?",
            (patient_id, dedupe),
        ).fetchone()
        record = row_to_record(row) if row else None
        if record:
            record["duplicate"] = True
            return record
    row = conn.execute("SELECT * FROM health_records WHERE id=?", (cur.lastrowid,)).fetchone()
    record = row_to_record(row)
    record["duplicate"] = False
    return record


def row_to_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "kind": row["kind"],
        "label": KIND_SPEC.get(row["kind"], {}).get("label", row["kind"]),
        "value": row["value"],
        "unit": row["unit"],
        "recorded_at": row["recorded_at"],
        "source": row["source"],
        "note": row["note"],
        "payload": loads(row["payload"], {}),
        "created_at": row["created_at"],
    }


def list_records(
    conn: sqlite3.Connection,
    patient_id: str,
    *,
    kind: str | None = None,
    since: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    get_patient(conn, patient_id)
    sql = "SELECT * FROM health_records WHERE patient_id=?"
    args: list[Any] = [patient_id]
    if kind:
        sql += " AND kind=?"
        args.append(normalize_kind(kind))
    if since:
        sql += " AND recorded_at>=?"
        args.append(since)
    sql += " ORDER BY recorded_at DESC, id DESC LIMIT ?"
    args.append(limit)
    return [row_to_record(r) for r in conn.execute(sql, args).fetchall()]


def _parse_csv(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    out = []
    for i, row in enumerate(reader, start=2):
        item = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}
        item["_row"] = i
        out.append(item)
    return out


def import_records(
    conn: sqlite3.Connection,
    patient_id: str,
    *,
    csv_text: str | None = None,
    json_rows: Iterable[dict[str, Any]] | None = None,
    source: str = "csv_import",
) -> dict[str, Any]:
    """批量导入：逐行校验，坏行不阻塞好行；重复行幂等跳过。"""
    get_patient(conn, patient_id)
    rows: list[dict[str, Any]] = []
    if csv_text:
        rows.extend(_parse_csv(csv_text))
    if json_rows:
        for i, r in enumerate(json_rows, start=1):
            item = dict(r)
            item.setdefault("_row", i)
            rows.append(item)
    created: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for row in rows:
        raw_kind = row.get("kind") or row.get("type")
        try:
            # 单条 API 用嵌套 payload；CSV/扁平 JSON 把字段放在行上；两种都支持，语义一致
            payload: dict[str, Any] = dict(row.get("payload") or {})
            for k in ("text", "systolic", "diastolic", "medication_name", "tags"):
                if k in row and row[k] not in (None, "") and k not in payload:
                    payload[k] = row[k]
            data = {
                "kind": raw_kind,
                "value": row.get("value"),
                "unit": row.get("unit") or None,
                "recorded_at": row.get("recorded_at") or row.get("time"),
                "note": row.get("note"),
                "source": source,
                "payload": payload,
            }
            record = add_record(conn, patient_id, data)
            if record.get("duplicate"):
                duplicates.append(record)
            else:
                created.append(record)
        except (RecordValidationError, ValueError) as exc:
            errors.append({"row": row.get("_row"), "error": str(exc), "raw": {k: v for k, v in row.items() if k != "_row"}})
    return {
        "patient_id": patient_id,
        "imported": len(created),
        "duplicates": len(duplicates),
        "failed": len(errors),
        "records": created,
        "duplicate_records": duplicates,
        "errors": errors,
    }
