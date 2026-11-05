import { describe, expect, it } from "vitest";
import type { Run } from "../api/types";
import {
  actionSummary,
  businessName,
  businessText,
  runNarrative,
} from "./business";

const run: Run = {
  id: "RUN-test",
  patient_id: "P001",
  status: "completed",
  llm_mode: "mock",
  trigger_type: "answer_received",
  started_at: "2026-11-05T00:00:00Z",
  input: { message: "患者回答：记不清" },
};
describe("业务展示保持结果边界", () => {
  it("关键字段有中文业务映射", () => {
    expect(
      [
        "waiting_user",
        "answer_received",
        "medication_taken",
        "request_human_review",
        "FORBIDDEN_ACTION",
      ].map(businessName),
    ).toEqual([
      "等待患者补充信息",
      "患者已回答",
      "是否按时服药",
      "请求医护人员复核",
      "操作超出系统允许范围，已拦截",
    ]);
  });
  it("失败运行即使读取成功，也不显示整次业务完成", () => {
    const n = runNarrative({
      ...run,
      status: "failed",
      output: {
        actions: [{ tool: "query_history", ok: true }],
        rejections: [{ code: "POSTCHECK_MISMATCH" }],
      },
    });
    expect(n.incomplete).toBe(true);
    expect(n.summary).toContain("查阅健康记录");
    expect(n.title).toContain("未全部完成");
    expect(n.next).toContain("人工核查");
  });
  it("计划动作不能被描述为实际成功", () => {
    const n = runNarrative({
      ...run,
      plan: { actions: [{ tool: "create_task" }] },
    });
    expect(n.summary).toContain("尚未返回可确认成功");
    expect(n.summary).not.toContain("安排健康管理任务");
  });
  it("执行后核对失败优先于工具返回成功", () => {
    const n = runNarrative({
      ...run,
      output: {
        actions: [{ tool: "create_task", ok: true, post_check: { ok: false } }],
      },
    });
    expect(n.incomplete).toBe(true);
    expect(n.summary).not.toContain("已返回成功的动作");
    expect(
      actionSummary(
        "create_task",
        {
          result: { ok: true },
          post_check: { ok: false, message: "任务未入库" },
        },
        "ok",
      ),
    ).toBe("任务未入库");
  });
  it("不确定回答仅在真实成功动作支持时概括后续任务", () => {
    expect(
      runNarrative({
        ...run,
        output: { actions: [{ tool: "create_task", ok: true }] },
      }).title,
    ).toBe("患者回答不确定，已安排记录核实任务");
    expect(runNarrative(run).title).not.toContain("已安排");
  });
  it("默认摘要移开编号，但不修改原始数据", () => {
    const raw =
      "FORBIDDEN_ACTION request_human_review RUN-123 EVT-456 TSK-789 Q-abc KD-def";
    expect(businessText(raw)).not.toMatch(/RUN-|EVT-|TSK-|Q-|KD-/);
    expect(raw).toContain("RUN-123");
  });
  it("未知枚举不猜测含义，原文通过技术详情保留", () => {
    expect(businessName("future_action")).toContain("未映射");
    expect(businessText("future_action")).toContain("技术详情");
  });
  it("知识无命中不写成已有依据", () => {
    expect(
      actionSummary(
        "search_knowledge",
        { result: { ok: true, found: false } },
        "ok",
      ),
    ).toBe("未检索到匹配依据");
  });
});
