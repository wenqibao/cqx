import { z } from "zod";
import { client } from "./client";
import { patientSchema, recordSchema, taskSchema, runSchema } from "./types";
const object = z.record(z.string(), z.unknown());
const list = <T>(item: z.ZodType<T>) => z.object({ items: z.array(item) });
export const eventSchema = z
  .object({
    id: z.string(),
    patient_id: z.string(),
    code: z.string(),
    severity: z.string(),
    status: z.string(),
    message: z.string(),
    detected_at: z.string(),
    handled_by_run: z.string().nullable().optional(),
    evidence: z.unknown().optional(),
  })
  .passthrough();
export const questionSchema = z
  .object({
    id: z.string(),
    patient_id: z.string(),
    question: z.string(),
    status: z.string(),
    options: z.array(z.string()),
    target_field: z.string().nullable(),
    run_id: z.string().nullable(),
    answer: z.unknown().nullable(),
    answer_text: z.string().nullable(),
    created_at: z.string(),
  })
  .passthrough();
export const reviewSchema = z
  .object({
    id: z.string(),
    patient_id: z.string(),
    task_id: z.string().nullable(),
    run_id: z.string().nullable(),
    branch: z.string(),
    status: z.string(),
    reason: z.string(),
    detail: object,
    scheduled_for: z.string().nullable(),
    resolved_at: z.string().nullable(),
  })
  .passthrough();
export const prefSchema = z
  .object({
    id: z.string(),
    patient_id: z.string(),
    kind: z.string(),
    value: z.string(),
    source: z.string(),
    status: z.string(),
    valid_from: z.string(),
    valid_to: z.string().nullable().optional(),
  })
  .passthrough();
export const noticeSchema = z
  .object({
    id: z.string(),
    patient_id: z.string(),
    kind: z.string(),
    title: z.string(),
    body: z.string(),
    status: z.string(),
    ref_type: z.string().nullable(),
    ref_id: z.string().nullable(),
    created_at: z.string(),
  })
  .passthrough();
export const versionSchema = z
  .object({
    version: z.number(),
    change_kind: z.string(),
    reason: z.string().nullable(),
    changed_by: z.string(),
    run_id: z.string().nullable(),
    created_at: z.string(),
    snapshot: taskSchema,
  })
  .passthrough();
export const jobSchema = z
  .object({
    id: z.string(),
    kind: z.string(),
    patient_id: z.string().nullable(),
    status: z.string(),
    run_at: z.string(),
    attempts: z.number(),
    last_error: z.string().nullable().optional(),
    result: z.unknown().optional(),
  })
  .passthrough();
export const auditSchema = z.object({
  items: z.array(
    z
      .object({
        id: z.number(),
        ts: z.string(),
        patient_id: z.string().nullable(),
        run_id: z.string().nullable(),
        actor: z.string(),
        action: z.string(),
        decision: z.string(),
        code: z.string().nullable(),
        detail: z.unknown(),
      })
      .passthrough(),
  ),
  forbidden_executed: z.number(),
  rejection_codes: z.array(z.string()),
});
export const knowledgeSchema = z
  .object({
    id: z.string(),
    title: z.string(),
    publisher: z.string(),
    version: z.string(),
    source_url: z.string(),
    published_at: z.string(),
  })
  .passthrough();
export const hitSchema = z
  .object({
    doc_id: z.string(),
    title: z.string(),
    publisher: z.string(),
    version: z.string(),
    source_url: z.string(),
    anchor: z.string(),
    quote: z.string(),
    score: z.number(),
  })
  .passthrough();
export const agentResultSchema = z
  .object({
    run_id: z.string(),
    patient_id: z.string(),
    status: z.string(),
    llm_mode: z.string(),
    model: z.string().nullable().optional(),
    actions: z.array(object),
    responses: z.array(z.string()),
    rejections: z.array(object),
  })
  .passthrough();
const pid = (id: string) => `/patients/${encodeURIComponent(id)}`;
const item = (kind: string, id: string) => `/${kind}/${encodeURIComponent(id)}`;
export const api = {
  mode: (signal?: AbortSignal) =>
    client.read(
      "/system/mode",
      z.object({
        llm_mode: z.string(),
        ok: z.boolean(),
        model: z.string().optional(),
        error: z.string().optional(),
      }),
      signal,
    ),
  version: (signal?: AbortSignal) =>
    client.read(
      "/version",
      z.object({ name: z.string(), version: z.string() }),
      signal,
    ),
  patient: (id: string, s?: AbortSignal) =>
    client.read(pid(id), patientSchema, s),
  createPatient: (data: {
    name: string;
    age?: number;
    duration_years?: number;
    goals: string[];
    constraints: string[];
  }) =>
    client.write("/patients", patientSchema, { ...data, is_synthetic: true }),
  history: (id: string, s?: AbortSignal) =>
    client.read(
      pid(id) + "/state/history",
      z.object({
        patient_id: z.string(),
        snapshots: z.array(
          z.object({ version: z.number(), created_at: z.string() }),
        ),
      }),
      s,
    ),
  events: (id: string, s?: AbortSignal) =>
    client.read(pid(id) + "/events", list(eventSchema), s).then((r) => r.items),
  scan: (id: string) =>
    client.write(
      pid(id) + "/events/scan",
      z
        .object({
          created: z.array(eventSchema),
          existing: z.array(eventSchema).optional(),
        })
        .passthrough(),
      {},
    ),
  questions: (id: string, s?: AbortSignal) =>
    client
      .read(pid(id) + "/questions", list(questionSchema), s)
      .then((r) => r.items),
  answer: (id: string, text: string) =>
    client.write(
      item("questions", id) + "/answer",
      z
        .object({
          question: questionSchema,
          resume: z
            .object({
              question_id: z.string(),
              recorded: recordSchema.nullable(),
              uncertain: z.boolean(),
              run: agentResultSchema,
            })
            .nullable(),
        })
        .passthrough(),
      { answer_text: text, trigger_agent: true },
    ),
  reviews: (id: string, s?: AbortSignal) =>
    client
      .read(pid(id) + "/reviews", list(reviewSchema), s)
      .then((r) => r.items),
  resolve: (id: string, decision: string, note: string) =>
    client.write(item("reviews", id) + "/resolve", reviewSchema, {
      decision,
      note,
    }),
  task: (id: string, s?: AbortSignal) =>
    client.read(
      item("tasks", id),
      z.object({ task: taskSchema, versions: z.array(versionSchema) }),
      s,
    ),
  versions: (id: string, s?: AbortSignal) =>
    client.read(
      item("tasks", id) + "/versions",
      z.object({ task_id: z.string(), versions: z.array(versionSchema) }),
      s,
    ),
  reschedule: (id: string, due_at: string, reason: string) =>
    client.write(
      item("tasks", id) + "/reschedule",
      z.object({ task: taskSchema, versions: z.array(versionSchema) }),
      { due_at, reason, changed_by: "staff_demo" },
    ),
  preferences: (id: string, s?: AbortSignal) =>
    client
      .read(pid(id) + "/preferences?include_history=true", list(prefSchema), s)
      .then((r) => r.items),
  savePreference: (id: string, kind: string, value: string, source: string) =>
    client.write(
      pid(id) + "/preferences",
      z
        .object({
          preference: prefSchema,
          applied_to_tasks: z.array(z.unknown()),
          partial_success: z.boolean().optional(),
          outbox_id: z.string().optional(),
          error: z.string().optional(),
        })
        .passthrough(),
      { kind, value, source },
    ),
  clearPreference: (id: string, kind: string) =>
    client.write(
      pid(id) + "/preferences/" + encodeURIComponent(kind),
      object,
      undefined,
      "DELETE",
    ),
  notifications: (id: string, s?: AbortSignal) =>
    client
      .read(pid(id) + "/notifications", list(noticeSchema), s)
      .then((r) => r.items),
  readNotification: (id: string) =>
    client.write(item("notifications", id) + "/read", noticeSchema, {}),
  records: (id: string, days: number, s?: AbortSignal) =>
    client
      .read(pid(id) + `/records?days=${days}`, list(recordSchema), s)
      .then((r) => r.items),
  importRecords: (
    id: string,
    body: {
      csv_text?: string;
      json_rows?: Record<string, unknown>[];
      trigger_agent: boolean;
    },
  ) =>
    client.write(
      pid(id) + "/records/import",
      z
        .object({
          patient_id: z.string(),
          imported: z.number(),
          duplicates: z.number(),
          failed: z.number(),
          records: z.array(recordSchema),
          errors: z.array(object),
          automation: object.optional(),
        })
        .passthrough(),
      body,
    ),
  run: (id: string, message: string) =>
    client.write(pid(id) + "/agent/runs", agentResultSchema, { message }),
  knowledge: (s?: AbortSignal) =>
    client.read("/knowledge", list(knowledgeSchema), s).then((r) => r.items),
  search: (q: string, s?: AbortSignal) =>
    client.read(
      "/knowledge/search?q=" + encodeURIComponent(q),
      z.object({
        found: z.boolean(),
        hits: z.array(hitSchema),
        note: z.string().nullable().optional(),
        query: z.string(),
      }),
      s,
    ),
  jobs: (s?: AbortSignal) =>
    client
      .read("/automation/jobs?limit=100", list(jobSchema), s)
      .then((r) => r.items),
  tick: () => client.write("/automation/tick", object, { limit: 50 }),
  clock: (advance_seconds: number) =>
    client.write(
      "/automation/clock",
      z.object({ clock_offset_seconds: z.number(), now: z.string() }),
      { advance_seconds },
    ),
  audit: (s?: AbortSignal) =>
    client.read("/system/audit?limit=200", auditSchema, s),
};
export type Event = z.infer<typeof eventSchema>;
export type Question = z.infer<typeof questionSchema>;
export type Review = z.infer<typeof reviewSchema>;
export type Preference = z.infer<typeof prefSchema>;
export type Notice = z.infer<typeof noticeSchema>;
export type Version = z.infer<typeof versionSchema>;
