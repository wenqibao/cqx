import { z } from "zod";
export const patientSchema = z
  .object({
    id: z.string(),
    name: z.string(),
    age: z.number().nullable(),
    duration_years: z.number().nullable(),
    goals: z.array(z.string()),
    constraints: z.array(z.string()),
    is_synthetic: z.union([z.boolean(), z.number()]),
  })
  .passthrough();
export const recordSchema = z
  .object({
    id: z.number(),
    patient_id: z.string(),
    kind: z.string(),
    value: z.number().nullable(),
    unit: z.string(),
    recorded_at: z.string(),
  })
  .passthrough();
export const taskSchema = z
  .object({
    id: z.string(),
    patient_id: z.string(),
    title: z.string(),
    status: z.string(),
    priority: z.number(),
    due_at: z.string().nullable(),
    source_run_id: z.string().nullable(),
    event_id: z.string().nullable(),
  })
  .passthrough();
export const runSchema = z
  .object({
    id: z.string(),
    patient_id: z.string(),
    status: z.string(),
    llm_mode: z.string(),
    trigger_type: z.string(),
    started_at: z.string(),
  })
  .passthrough();
export const stateSchema = z
  .object({
    patient: patientSchema,
    latest: z.record(
      z.string(),
      z
        .object({
          value: z.number().nullable(),
          unit: z.string(),
          recorded_at: z.string(),
        })
        .passthrough(),
    ),
    missing_fields: z.array(z.string()),
    open_tasks: z.array(z.record(z.string(), z.unknown())),
    open_events: z.array(z.record(z.string(), z.unknown())),
    pending_questions: z.array(z.record(z.string(), z.unknown())),
    trend: z.record(z.string(), z.unknown()),
    generated_at: z.string(),
  })
  .passthrough();
export const healthSchema = z
  .object({
    status: z.string(),
    llm_mode: z.string(),
    database: z.object({ ok: z.boolean() }),
  })
  .passthrough();
export const traceSchema = z
  .object({
    run: runSchema,
    steps: z.array(
      z
        .object({
          step_no: z.number(),
          phase: z.string(),
          kind: z.string(),
          tool_name: z.string().nullable(),
          payload: z.record(z.string(), z.unknown()),
          status: z.string(),
          code: z.string().nullable(),
        })
        .passthrough(),
    ),
    evidence: z.array(z.record(z.string(), z.unknown())),
    tasks: z.array(taskSchema),
  })
  .passthrough();
export const recordKinds = [
  "fasting_glucose",
  "postprandial_glucose",
  "steps",
  "weight",
  "medication_taken",
  "symptom",
  "meal",
  "bp",
] as const;
export interface RecordCreate {
  kind: (typeof recordKinds)[number];
  value?: number | null;
  unit?: string | null;
  recorded_at?: string | null;
  note?: string | null;
  payload: Record<string, unknown>;
  trigger_agent: boolean;
}
export type Patient = z.infer<typeof patientSchema>;
export type HealthRecord = z.infer<typeof recordSchema>;
export type Task = z.infer<typeof taskSchema>;
export type Run = z.infer<typeof runSchema>;
export type State = z.infer<typeof stateSchema>;
export type Health = z.infer<typeof healthSchema>;
export type Trace = z.infer<typeof traceSchema>;
export interface RecordResult {
  record: HealthRecord;
  automation: Record<string, unknown> | null;
}
export interface CompleteResult {
  task: Task;
  reviews: Record<string, unknown>[];
}
export interface Adapter {
  mode: "http" | "mock";
  health(signal?: AbortSignal): Promise<Health>;
  patients(signal?: AbortSignal): Promise<Patient[]>;
  state(id: string, signal?: AbortSignal): Promise<State>;
  records(id: string, signal?: AbortSignal): Promise<HealthRecord[]>;
  tasks(id: string, signal?: AbortSignal): Promise<Task[]>;
  runs(id: string, signal?: AbortSignal): Promise<Run[]>;
  trace(id: string, signal?: AbortSignal): Promise<Trace>;
  addRecord(id: string, data: RecordCreate): Promise<RecordResult>;
  complete(id: string): Promise<CompleteResult>;
}
