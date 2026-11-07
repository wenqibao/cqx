-- 糖衡智管 Agent 数据模型（SQLite）
-- 约定：所有时间为 UTC ISO8601 字符串；金额/检验值保留原始单位字段。
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- F01 演示患者 F02 基础健康档案
CREATE TABLE IF NOT EXISTS patients (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    age             INTEGER,
    sex             TEXT,
    diabetes_type   TEXT DEFAULT 'T2DM',
    duration_years  REAL,
    complications   TEXT,            -- JSON array
    goals           TEXT,            -- JSON array
    constraints     TEXT,            -- JSON array（患者明确约束/禁忌，仅记录）
    baseline        TEXT,            -- JSON object（身高体重等）
    is_synthetic    INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- F03 健康数据
CREATE TABLE IF NOT EXISTS health_records (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id   TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,      -- fasting_glucose/postprandial_glucose/steps/medication_taken/weight/meal/symptom/bp
    value        REAL,
    unit         TEXT,
    recorded_at  TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'manual',   -- manual/csv_import/json_import/demo
    note         TEXT,
    payload      TEXT,               -- JSON object 额外字段（如 symptom 文本、药名）
    dedupe_key   TEXT,               -- 同一来源重复导入去重
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_patient_time ON health_records(patient_id, recorded_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_records_dedupe ON health_records(patient_id, dedupe_key)
    WHERE dedupe_key IS NOT NULL;

-- F04 状态快照（每次生成后持久化，便于跨会话恢复与对比）
CREATE TABLE IF NOT EXISTS state_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    snapshot    TEXT NOT NULL,       -- JSON
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_state_patient ON state_snapshots(patient_id, version DESC);

-- F05 事件
CREATE TABLE IF NOT EXISTS events (
    id           TEXT PRIMARY KEY,
    patient_id   TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    code         TEXT NOT NULL,
    severity     TEXT NOT NULL,      -- high/medium/low
    status       TEXT NOT NULL,      -- open/handled/merged/dismissed
    message      TEXT NOT NULL,
    evidence     TEXT,               -- JSON: 触发记录/统计数据
    dedupe_key   TEXT NOT NULL,
    source_record_id INTEGER,
    detected_at  TEXT NOT NULL,
    handled_at   TEXT,
    handled_by_run TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_events_dedupe ON events(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_events_patient ON events(patient_id, status, detected_at);

-- F08/F14 Agent 运行
CREATE TABLE IF NOT EXISTS agent_runs (
    id            TEXT PRIMARY KEY,
    patient_id    TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    trigger_type  TEXT NOT NULL,     -- record_created/event_detected/review_due/user_request/answer_received/scheduled_tick
    trigger_ref   TEXT,
    llm_mode      TEXT NOT NULL,     -- mock/real
    model_name    TEXT,
    status        TEXT NOT NULL,     -- running/completed/waiting_user/failed/blocked
    intent        TEXT,
    input         TEXT,
    plan          TEXT,
    output        TEXT,
    error         TEXT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_patient ON agent_runs(patient_id, started_at DESC);

-- F14 执行轨迹（每次工具调用/校验一行）
CREATE TABLE IF NOT EXISTS agent_steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    step_no     INTEGER NOT NULL,
    phase       TEXT NOT NULL,       -- perceive/plan/validate/act/observe/self_check/finalize
    kind        TEXT NOT NULL,       -- tool_call/tool_result/decision/validation/rejection/error
    tool_name   TEXT,
    payload     TEXT,                -- JSON
    status      TEXT NOT NULL,       -- ok/rejected/failed/skipped
    code        TEXT,                -- rejection_code 等
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_steps_run ON agent_steps(run_id, step_no);

-- F11/F23 任务与计划版本
CREATE TABLE IF NOT EXISTS tasks (
    id            TEXT PRIMARY KEY,
    patient_id    TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    task_type     TEXT NOT NULL,
    title         TEXT NOT NULL,
    description   TEXT,
    status        TEXT NOT NULL,     -- pending/done/missed/cancelled
    priority      INTEGER NOT NULL DEFAULT 50,
    due_at        TEXT,
    event_id      TEXT,
    source_run_id TEXT,
    version       INTEGER NOT NULL DEFAULT 1,
    required_fields TEXT,            -- JSON array
    meta          TEXT,              -- JSON
    dedupe_key    TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    completed_at  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_dedupe ON tasks(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_tasks_patient ON tasks(patient_id, status, due_at);

CREATE TABLE IF NOT EXISTS task_versions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    version      INTEGER NOT NULL,
    snapshot     TEXT NOT NULL,      -- JSON（变更前/后的完整快照）
    change_kind  TEXT NOT NULL,      -- create/reschedule/complete/cancel/merge
    reason       TEXT,
    changed_by   TEXT NOT NULL,      -- agent/patient/system
    run_id       TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_versions ON task_versions(task_id, version);

-- F21 主动询问
CREATE TABLE IF NOT EXISTS questions (
    id            TEXT PRIMARY KEY,
    patient_id    TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    run_id        TEXT,
    event_id      TEXT,
    kind          TEXT NOT NULL,     -- missing_field/ambiguous_record/confirm_change
    question      TEXT NOT NULL,
    options       TEXT,              -- JSON array
    target_field  TEXT,
    status        TEXT NOT NULL,     -- waiting/answered/expired/cancelled
    answer        TEXT,              -- JSON
    answer_text   TEXT,
    resume_payload TEXT,             -- JSON：恢复执行所需上下文
    created_at    TEXT NOT NULL,
    answered_at   TEXT,
    expires_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_questions_patient ON questions(patient_id, status, created_at);

-- F12 复评
CREATE TABLE IF NOT EXISTS reviews (
    id          TEXT PRIMARY KEY,
    patient_id  TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    task_id     TEXT,
    event_id    TEXT,
    run_id      TEXT,
    branch      TEXT NOT NULL,       -- CLOSED/MISSING_DATA/HUMAN_REVIEW
    status      TEXT NOT NULL,       -- scheduled/completed/pending_human
    reason      TEXT,
    detail      TEXT,                -- JSON
    scheduled_for TEXT,
    created_at  TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_reviews_patient ON reviews(patient_id, status, scheduled_for);

-- F25 长期偏好
CREATE TABLE IF NOT EXISTS preferences (
    id           TEXT PRIMARY KEY,
    patient_id   TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,      -- preferred_time_window/task_obstacle/contact_window...
    value        TEXT NOT NULL,
    source       TEXT NOT NULL,      -- patient_confirmed/agent_inferred(禁止)/import
    status       TEXT NOT NULL,      -- active/superseded/cleared
    valid_from   TEXT NOT NULL,
    valid_until  TEXT,
    superseded_by TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prefs_patient ON preferences(patient_id, kind, status);

-- F24 知识库
CREATE TABLE IF NOT EXISTS knowledge_docs (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    publisher    TEXT NOT NULL,
    version      TEXT,
    source_url   TEXT,
    published_at TEXT,
    path         TEXT NOT NULL,
    checksum     TEXT
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id        TEXT PRIMARY KEY,
    doc_id    TEXT NOT NULL REFERENCES knowledge_docs(id) ON DELETE CASCADE,
    ordinal   INTEGER NOT NULL,
    anchor    TEXT NOT NULL,         -- 章节锚点，如 "#2.1-1"
    heading   TEXT,
    text      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON knowledge_chunks(doc_id, ordinal);

CREATE TABLE IF NOT EXISTS evidence_items (
    id           TEXT PRIMARY KEY,
    patient_id   TEXT,
    run_id       TEXT,
    doc_id       TEXT NOT NULL,
    chunk_id     TEXT NOT NULL,
    anchor       TEXT NOT NULL,
    quote        TEXT NOT NULL,
    score        REAL,
    query        TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_run ON evidence_items(run_id);

-- 站内待办/提醒（F16）
CREATE TABLE IF NOT EXISTS notifications (
    id          TEXT PRIMARY KEY,
    patient_id  TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,       -- task_created/question_created/review_due/agent_error
    title       TEXT NOT NULL,
    body        TEXT,
    status      TEXT NOT NULL,       -- unread/read
    ref_type    TEXT,
    ref_id      TEXT,
    created_at  TEXT NOT NULL,
    read_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications ON notifications(patient_id, status, created_at);

-- F07 自动调度任务（幂等）
CREATE TABLE IF NOT EXISTS automation_jobs (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,       -- agent_run/event_scan/review_due/reminder
    patient_id  TEXT,
    ref_id      TEXT,
    payload     TEXT,
    run_at      TEXT NOT NULL,
    status      TEXT NOT NULL,       -- pending/running/done/skipped/failed
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
-- JOB-DEDUPE-01 的唯一索引由 backend/app/db/migrations.py 在清理旧数据后创建
CREATE INDEX IF NOT EXISTS idx_jobs_due ON automation_jobs(status, run_at);

-- 自动化副作用 outbox（业务写入成功后，副作用失败可重试补偿）
CREATE TABLE IF NOT EXISTS automation_outbox (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,      -- after_records / after_preference / after_task_completed / scan_later
    patient_id  TEXT NOT NULL,
    payload     TEXT,
    status      TEXT NOT NULL,      -- pending / done / failed
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON automation_outbox(status, created_at);

-- 幂等键（重复提交不重复执行）
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key         TEXT PRIMARY KEY,
    scope       TEXT NOT NULL,
    result      TEXT,
    created_at  TEXT NOT NULL
);

-- 安全与审计（F13/F14/F26）
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    patient_id  TEXT,
    run_id      TEXT,
    actor       TEXT NOT NULL,       -- agent/patient/system
    action      TEXT NOT NULL,
    decision    TEXT NOT NULL,       -- allow/reject/escalate/info
    code        TEXT,
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_patient ON audit_log(patient_id, ts DESC);
