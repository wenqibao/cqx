import { describe, it, expect, vi } from "vitest";
import { HttpAdapter } from "./httpAdapter";
import { createClient } from "./client";
import { traceSchema, runSummarySchema } from "./types";
it("非JSON的502仍保留HTTP错误码", async () => {
  await expect(
    new HttpAdapter(
      "",
      vi.fn().mockResolvedValue(new Response("Bad Gateway", { status: 502 })),
    ).health(),
  ).rejects.toMatchObject({ code: "HTTP_502", detail: "Bad Gateway" });
});

describe("O1 运行详情 summary 契约", () => {
  const summary = {
    goal: "核实健康记录",
    trigger: { label: "患者回答问题", ref: "Q-actual" },
    completed: [],
    unfinished: [{ code: "TOOL_EXECUTION_FAILED", message: null }],
    waiting: {
      kind: "question",
      id: "Q-actual",
      target_field: "medication_taken",
      text: "请补充记录",
    },
    next_owner: { role: "patient", action: "回答待确认问题" },
    partial_success: true,
    warnings: [],
    refs: ["RUN-actual", "Q-actual"],
  };
  const trace = {
    run: {
      id: "RUN-actual",
      patient_id: "P001",
      status: "waiting_user",
      llm_mode: "mock",
      trigger_type: "answer_received",
      started_at: "2026-11-26T00:00:00Z",
    },
    steps: [],
    evidence: [],
    tasks: [],
  };

  it("HTTP详情保留summary、来源与原始扩展字段", async () => {
    const body = { ...trace, summary };
    const adapter = new HttpAdapter(
      "",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(body))),
    );
    expect(await adapter.trace("RUN-actual")).toEqual(body);
  });
  it("旧详情缺少summary或summary为null时仍可读取", () => {
    expect(traceSchema.parse(trace)).toEqual(trace);
    expect(traceSchema.parse({ ...trace, summary: null }).summary).toBeNull();
  });
  it("completed或partial_success类型错误会拒绝解析", () => {
    expect(
      runSummarySchema.safeParse({ ...summary, completed: "已完成" }).success,
    ).toBe(false);
    expect(
      runSummarySchema.safeParse({ ...summary, partial_success: "false" })
        .success,
    ).toBe(false);
  });
});
it("同一客户端请求串行执行", async () => {
  let active = 0,
    max = 0;
  const transport = vi.fn(async () => {
    active++;
    max = Math.max(max, active);
    await new Promise((r) => setTimeout(r, 5));
    active--;
    return new Response(
      JSON.stringify({
        status: "ok",
        llm_mode: "mock",
        database: { ok: true },
      }),
    );
  });
  const api = new HttpAdapter("", transport);
  await Promise.all([api.health(), api.health(), api.health()]);
  expect(max).toBe(1);
});
describe("HTTP adapter错误隔离", () => {
  for (const status of [404, 422, 502])
    it(`HTTP ${status}保留状态与错误正文`, async () => {
      const api = new HttpAdapter(
        "",
        vi.fn().mockResolvedValue(
          new Response(JSON.stringify({ detail: "后端原始错误" }), {
            status,
          }),
        ),
      );
      await expect(api.health()).rejects.toMatchObject({
        code: `HTTP_${status}`,
        detail: { detail: "后端原始错误" },
      });
    });
  it("离线不回退前端模拟", async () => {
    await expect(
      new HttpAdapter(
        "",
        vi.fn().mockRejectedValue(new Error("offline")),
      ).patients(),
    ).rejects.toMatchObject({ code: "NETWORK_ERROR" });
  });
  it("响应结构不符显式失败", async () => {
    await expect(
      new HttpAdapter(
        "",
        vi.fn().mockResolvedValue(new Response("{}")),
      ).health(),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
  it("空患者列表保留空态", async () => {
    expect(
      await new HttpAdapter(
        "",
        vi.fn().mockResolvedValue(new Response('{"items":[]}')),
      ).patients(),
    ).toEqual([]);
  });
  it("超时中止请求", async () => {
    const transport = vi.fn(
      (_url: unknown, init?: RequestInit) =>
        new Promise<Response>((_, reject) =>
          init?.signal?.addEventListener("abort", () =>
            reject(new Error("aborted")),
          ),
        ),
    );
    await expect(
      new HttpAdapter("", transport, 5).health(),
    ).rejects.toMatchObject({ code: "TIMEOUT_OR_ABORT" });
  });
  it("模式严格选择", () => {
    expect(createClient("http").mode).toBe("http");
    expect(createClient("mock").mode).toBe("mock");
    expect(() => createClient("typo")).toThrow();
  });
  it("真实保存仅发送记录接口，原样保留automation", async () => {
    const record = {
      id: 1,
      patient_id: "P001",
      kind: "steps",
      value: 4200,
      unit: "步",
      recorded_at: "2026-11-04T02:00:00Z",
    };
    const transport = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          record,
          automation: { runs: [], events_created: [] },
        }),
      ),
    );
    await new HttpAdapter("", transport).addRecord("P001", {
      kind: "steps",
      value: 4200,
      payload: {},
      trigger_agent: true,
    });
    expect(transport).toHaveBeenCalledTimes(1);
    expect(transport.mock.calls[0][0]).toBe("/patients/P001/records");
    expect(JSON.parse(transport.mock.calls[0][1].body)).toMatchObject({
      kind: "steps",
      trigger_agent: true,
    });
  });
});
