import { describe, expect, it } from "vitest";
import type { Run } from "../api/types";
import {
  actionSummary,
  businessName,
  businessText,
  runNarrative,
  relatedQuestions,
  runHasFailure,
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
    expect(n.summary).toContain("暂无已完成");
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
    expect(n.summary).not.toContain("已完成：");
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
    expect(businessText(raw)).toContain("操作超出系统允许范围，已拦截");
    expect(businessText(raw)).toContain("请求医护人员复核");
    expect(raw).toContain("RUN-123");
  });
  it("结构化未知枚举提示核实，正文保留原词和量纲", () => {
    expect(businessName("future_action")).toContain("信息待核实");
    expect(businessName("respond")).toBe("给出管理说明");
    const prose = "自我血糖监测（SMBG）和 CGM，单位 mmol/L、mmHg。patient can respond. future_action constructor";
    expect(businessText(prose)).toBe(prose);
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

describe("待回答问题关联", () => {
  const q = {
    id: "Q-one",
    patient_id: "P001",
    run_id: "RUN-test",
    status: "waiting",
  };
  it("按当前运行和患者匹配问题", () => {
    expect(
      relatedQuestions({ id: "RUN-test", patient_id: "P001" }, [q]),
    ).toEqual([q]);
  });
  it("复用已有问题时按实际动作结果的question_id关联", () => {
    expect(
      relatedQuestions(
        {
          run_id: "RUN-new",
          patient_id: "P001",
          actions: [{ result: { question_id: q.id } }],
        },
        [q],
      ),
    ).toEqual([q]);
  });
  it("不把其他患者或其他运行的问题作为本次问题", () => {
    expect(
      relatedQuestions({ id: "RUN-new", patient_id: "P001" }, [
        q,
        { ...q, patient_id: "P002", run_id: "RUN-new" },
      ]),
    ).toEqual([]);
  });
  it("只计划提问没有实际结果时不编造问题关联", () => {
    expect(
      relatedQuestions(
        {
          id: "RUN-new",
          patient_id: "P001",
          plan: { actions: [{ tool: "ask_user" }] },
        },
        [q],
      ),
    ).toEqual([]);
  });
});

describe("操作结果不掩盖失败", () => {
  it("后端整体completed但动作失败时仍提示未完成", () => {
    expect(
      runHasFailure({ status: "completed", actions: [{ ok: false }] }),
    ).toBe(true);
    expect(
      runHasFailure({
        status: "completed",
        actions: [{ ok: true, post_check: { ok: false } }],
      }),
    ).toBe(true);
  });
  it("拦截和拒绝保留失败提示", () => {
    expect(runHasFailure({ status: "blocked" })).toBe(true);
    expect(
      runHasFailure({
        status: "completed",
        rejections: [{ code: "FORBIDDEN_ACTION" }],
      }),
    ).toBe(true);
  });
  it("成功动作不制造失败提示", () => {
    expect(
      runHasFailure({
        status: "completed",
        actions: [{ ok: true, post_check: { ok: true } }],
      }),
    ).toBe(false);
  });
});
