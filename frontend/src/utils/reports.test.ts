import { describe, it, expect } from "vitest";
import { parseReport, redactLog } from "./reports";
import { importRows, noticeLink } from "./format";
describe("真实证据导入边界", () => {
  it("Mock场景保留Mock，统计来自实际明细", () => {
    const r = parseReport(
      JSON.stringify({
        at: "2026-11-04",
        llm_mode: "mock",
        total: 1,
        passed: 1,
        failed: 0,
        results: [
          {
            id: "B01",
            title: "实际场景",
            passed: true,
            llm_mode: "mock",
            run_ids: ["RUN-x"],
          },
        ],
      }),
    );
    expect(r.rows[0]).toMatchObject({
      mode: "mock",
      result: "PASS",
      runIds: ["RUN-x"],
    });
  });
  it("Real拒绝不会冒充模型调用，未知结果保留", () => {
    const r = parseReport(
      JSON.stringify({
        scenarios: [
          {
            scenario_id: "R06",
            result: "PASS",
            llm_mode: "real",
            run_ids: ["RUN-x"],
            execution_origin: "system_safety_gate",
          },
          {
            scenario_id: "R03",
            result: "INCONCLUSIVE",
            llm_mode: "real",
            run_ids: [],
          },
        ],
      }),
    );
    expect(r.rows[0].origin).toBe("system_safety_gate");
    expect(r.rows[1].result).toBe("INCONCLUSIVE");
  });
  it.each([
    "{}",
    "{bad",
    '{"passed":33}',
    '{"scenarios":[{"scenario_id":"x","result":"PASS","llm_mode":"real"}]}',
  ])("非法报告不生成通过率 %s", (raw) =>
    expect(() => parseReport(raw)).toThrow(),
  );
  it("汇总造假不能覆盖失败明细", () => {
    const r = parseReport(
      JSON.stringify({
        llm_mode: "mock",
        total: 100,
        passed: 100,
        failed: 0,
        results: [
          { id: "B01", title: "失败", passed: false, llm_mode: "mock" },
        ],
      }),
    );
    expect(r.warning).toBeTruthy();
    expect(r.rows[0].result).toBe("FAIL");
  });
  it("JSON导入将嵌套payload转换成后端import实际支持字段", () =>
    expect(
      importRows(
        '[{"kind":"bp","payload":{"systolic":120,"diastolic":80}}]',
      )[0],
    ).toMatchObject({ systolic: 120, diastolic: 80 }));
  it.each(["{}", "[]", "[null]", "[1]"])("拒绝无效记录文件 %s", (raw) =>
    expect(() => importRows(raw)).toThrow(),
  );
  it("通知链接携带患者上下文", () =>
    expect(
      noticeLink({ patient_id: "P002", ref_type: "question", ref_id: "Q-1" }),
    ).toBe("/followups?patient=P002&question=Q-1"));
  it("导入日志隐藏疑似凭据且不执行命令", () =>
    expect(
      redactLog(
        "Authorization: Bearer secret\nAGENT_LLM_API_KEY=test\nsk-1234567890123456",
      ),
    ).not.toMatch(/Bearer secret|=test|sk-123/));
});
