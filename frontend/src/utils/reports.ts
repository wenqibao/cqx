import { z } from "zod";
import { obj } from "./format";
const result = z.enum(["PASS", "FAIL", "BLOCKED", "INCONCLUSIVE", "NOT_RUN"]);
const mode = z.enum(["mock", "real", "stub", "unknown"]);
export type ReportResult = z.infer<typeof result>;
export const reportResultDisplay = {
  PASS: { label: "通过", color: "success" },
  FAIL: { label: "失败", color: "error" },
  BLOCKED: { label: "阻塞", color: "warning" },
  INCONCLUSIVE: { label: "不确定", color: "processing" },
  NOT_RUN: { label: "未执行", color: "default" },
} satisfies Record<ReportResult, { label: string; color: string }>;
export type ReportRow = {
  id: string;
  title: string;
  mode: string;
  result: ReportResult;
  runIds: string[];
  reason: string;
  origin: string;
  raw: unknown;
};
export type Report = {
  at: string | null;
  git: string | null;
  environment: unknown;
  rows: ReportRow[];
  raw: unknown;
  warning: string | null;
};
export function parseReport(raw: string): Report {
  if (raw.length > 5 * 1024 * 1024) throw new Error("报告不得超过5MB");
  const parsed: unknown = JSON.parse(raw.replace(/^\uFEFF/, ""));
  const root = obj(parsed);
  let rows: ReportRow[];
  if (Array.isArray(root.results)) {
    const schema = z
      .object({
        at: z.string().optional(),
        llm_mode: mode,
        total: z.number().int().nonnegative(),
        passed: z.number().int().nonnegative(),
        failed: z.number().int().nonnegative(),
        results: z.array(
          z
            .object({
              id: z.string(),
              title: z.string(),
              passed: z.boolean(),
              llm_mode: mode,
              run_ids: z.array(z.string()).optional(),
              errors: z.array(z.string()).optional(),
            })
            .passthrough(),
        ),
      })
      .passthrough();
    const r = schema.parse(root);
    rows = r.results.map((v) => ({
      id: v.id,
      title: v.title,
      mode: v.llm_mode,
      result: v.passed ? "PASS" : "FAIL",
      runIds: v.run_ids || [],
      reason: (v.errors || []).join("；"),
      origin: "场景回放报告",
      raw: v,
    }));
  } else if (Array.isArray(root.scenarios)) {
    const r = z
      .object({
        scenarios: z.array(
          z
            .object({
              scenario_id: z.string(),
              result,
              llm_mode: mode,
              run_ids: z.array(z.string()),
              explanation: z.string().optional(),
              execution_origin: z.string().optional(),
              error: z.unknown().optional(),
            })
            .passthrough(),
        ),
      })
      .passthrough()
      .parse(root);
    rows = r.scenarios.map((v) => ({
      id: v.scenario_id,
      title: v.explanation || v.scenario_id,
      mode: v.llm_mode,
      result: v.result,
      runIds: v.run_ids,
      reason: v.error ? JSON.stringify(v.error) : "",
      origin: v.execution_origin || "报告未注明动作来源",
      raw: v,
    }));
  } else
    throw new Error(
      "不支持的报告格式：需要真实场景 results 或验收 scenarios 数组；未生成任何通过率",
    );
  const reported = root.total;
  const passed = rows.filter((v) => v.result === "PASS").length;
  const warning =
    typeof reported === "number" &&
    (reported !== rows.length || root.passed !== passed)
      ? "报告汇总与明细不一致；页面只按导入明细统计，请核对原报告。"
      : null;
  return {
    at:
      typeof (root.at || root.generated_at) === "string"
        ? String(root.at || root.generated_at)
        : null,
    git:
      typeof (root.delivery_git_sha || root.source_git_sha || root.git_sha) ===
      "string"
        ? String(root.delivery_git_sha || root.source_git_sha || root.git_sha)
        : null,
    environment: root.environment || null,
    rows,
    raw: parsed,
    warning,
  };
}
export function redactLog(raw: string) {
  return raw
    .replace(/(?:sk|ds)-[a-zA-Z0-9_-]{12,}/g, "[已隐藏疑似密钥]")
    .replace(/(authorization\s*[:=]\s*)([^\r\n]+)/gi, "$1[已隐藏]")
    .replace(/(AGENT_LLM_API_KEY\s*[:=]\s*)([^\r\n]+)/gi, "$1[已隐藏]");
}
