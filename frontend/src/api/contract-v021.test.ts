import { expect, it, vi } from "vitest";
import { z } from "zod";
import { HttpAdapter } from "./httpAdapter";
import { writeTimeout } from "./client";
import {
  runHasFailure,
  runNarrative,
  unresolvedRejections,
} from "../utils/business";
import type { Run } from "./types";

const task = {
  id: "TSK-contract",
  patient_id: "P",
  title: "记录",
  status: "done",
  priority: 1,
  due_at: null,
  source_run_id: null,
  event_id: null,
};
const rejection = {
  code: "INVALID_DUE",
  tool: "create_task",
  message: "时间无效",
};
const corrected = {
  status: "completed",
  rejections: [rejection],
  warnings: [{ ...rejection, resolved: true }],
  actions: [{ tool: "create_task", ok: true }],
};
it("已纠正拒绝不误报失败，仍保留原拒绝", () => {
  expect(runHasFailure(corrected)).toBe(false);
  expect(unresolvedRejections(corrected)).toEqual([]);
  expect(corrected.rejections).toEqual([rejection]);
  const run = {
    id: "R",
    patient_id: "P",
    status: "completed",
    llm_mode: "mock",
    trigger_type: "user_request",
    started_at: "",
    output: corrected,
  } as Run;
  expect(runNarrative(run).incomplete).toBe(false);
});
it("未解决拒绝、失败状态、未标记resolved的warning仍失败", () => {
  expect(
    runHasFailure({
      ...corrected,
      warnings: [{ ...rejection, resolved: false }],
    }),
  ).toBe(true);
  expect(runHasFailure({ ...corrected, status: "failed" })).toBe(true);
  expect(
    runHasFailure({
      ...corrected,
      rejections: [rejection, { code: "FORBIDDEN_ACTION" }],
    }),
  ).toBe(true);
  expect(
    runHasFailure({ ...corrected, rejections: [rejection, rejection] }),
  ).toBe(true);
  expect(
    runHasFailure({ ...corrected, actions: [{ tool: "respond", ok: false }] }),
  ).toBe(true);
});
it("真实工具失败后纠正也不把整次运行误报失败，数据库不一致仍失败", () => {
  const failure = {
    code: "TOOL_EXECUTION_FAILED",
    message: "缺少关联任务",
    ok: false,
  };
  const data = {
    status: "completed",
    warnings: [{ ...failure, tool: "schedule_review", resolved: true }],
    actions: [
      { tool: "schedule_review", ok: false, post_check: failure },
      { tool: "schedule_review", ok: true },
    ],
  };
  expect(runHasFailure(data)).toBe(false);
  const run = {
    id: "R",
    patient_id: "P",
    status: "completed",
    llm_mode: "mock",
    trigger_type: "user_request",
    started_at: "",
    output: data,
  } as Run;
  expect(
    runNarrative(run, {
      run,
      tasks: [],
      evidence: [],
      steps: [
        {
          step_no: 1,
          phase: "observe",
          kind: "tool_result",
          tool_name: "schedule_review",
          payload: { post_check: failure },
          status: "failed",
          code: failure.code,
        },
      ],
    }).incomplete,
  ).toBe(false);
  expect(
    runHasFailure({
      ...data,
      actions: [
        {
          tool: "schedule_review",
          ok: true,
          post_check: { ok: false, code: "POSTCHECK_MISMATCH" },
        },
      ],
    }),
  ).toBe(true);
});
for (const flag of ["already_done", "partial_success"])
  it(`${flag}没有reviews时仍读取真实任务`, async () => {
    const body = { task, [flag]: true, run: null, outbox_id: "OUT-test" };
    const transport = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(body)));
    expect(await new HttpAdapter("", transport).complete(task.id)).toEqual(
      body,
    );
    expect(transport).toHaveBeenCalledTimes(1);
  });
it("记录部分成功信息完整保留", async () => {
  const body = {
    record: {
      id: 1,
      patient_id: "P",
      kind: "steps",
      value: 5,
      unit: "步",
      recorded_at: "",
    },
    automation: null,
    partial_success: true,
    outbox_id: "OUT-test",
    error: "failure",
  };
  const transport = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify(body)));
  expect(
    await new HttpAdapter("", transport).addRecord("P", {
      kind: "steps",
      value: 5,
      payload: {},
      trigger_agent: true,
    }),
  ).toEqual(body);
});
it("409保留原文且说明资源重复", async () => {
  const transport = vi
    .fn()
    .mockResolvedValue(
      new Response('{"detail":"患者 ID 已存在: P"}', { status: 409 }),
    );
  await expect(new HttpAdapter("", transport).patients()).rejects.toMatchObject(
    {
      code: "HTTP_409",
      message: expect.stringContaining("资源已存在"),
      detail: { detail: "患者 ID 已存在: P" },
    },
  );
});
it("长写入期间健康探测不会被业务队列阻塞", async () => {
  let finish!: (r: Response) => void;
  const transport = vi.fn((url: string | URL | Request) =>
    String(url).endsWith("/health")
      ? Promise.resolve(
          new Response(
            '{"status":"ok","llm_mode":"mock","database":{"ok":true}}',
          ),
        )
      : new Promise<Response>((resolve) => {
          finish = resolve;
        }),
  );
  const client = new HttpAdapter("", transport);
  const write = client.write("/records", z.object({ ok: z.boolean() }), {});
  await expect(client.health()).resolves.toMatchObject({ status: "ok" });
  finish(new Response('{"ok":true}'));
  await write;
});
it("写超时配置有默认值并拒绝非法值", () => {
  expect(writeTimeout()).toBe(180000);
  expect(writeTimeout("250000")).toBe(250000);
  for (const value of ["0", "-1", "foo"])
    expect(() => writeTimeout(value)).toThrow();
});
