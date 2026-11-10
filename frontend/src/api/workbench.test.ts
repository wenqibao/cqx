import { it, expect, vi } from "vitest";
import { HttpAdapter } from "./httpAdapter";
import { z } from "zod";
it("长业务写请求超过GET超时仍等待，失败不自动重试", async () => {
  const transport = vi.fn(async () => {
    await new Promise((r) => setTimeout(r, 20));
    return new Response('{"ok":true}');
  });
  const client = new HttpAdapter("", transport, 5, 100);
  await expect(
    client.write("/patients/P/agent/runs", z.object({ ok: z.boolean() }), {
      message: "test",
    }),
  ).resolves.toEqual({ ok: true });
  expect(transport).toHaveBeenCalledTimes(1);
});
it("写请求超时明确提示可能已保存，只有一次请求", async () => {
  const transport = vi.fn(
    (_u: unknown, i?: RequestInit) =>
      new Promise<Response>((_resolve, reject) =>
        i?.signal?.addEventListener("abort", () =>
          reject(new Error("aborted")),
        ),
      ),
  );
  const client = new HttpAdapter("", transport, 100, 5);
  await expect(
    client.write("/records", z.object({}), {}),
  ).rejects.toMatchObject({
    code: "TIMEOUT_OR_ABORT",
    message: expect.stringContaining("可能已保存"),
  });
  expect(transport).toHaveBeenCalledTimes(1);
});
it("人工完成任务使用staff_demo，避免记成患者本人", async () => {
  const task = {
    id: "T",
    patient_id: "P",
    title: "记录",
    status: "done",
    priority: 50,
    due_at: null,
    source_run_id: null,
    event_id: null,
  };
  const transport = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify({ task, reviews: [] })));
  await new HttpAdapter("", transport).complete("T");
  expect(JSON.parse(transport.mock.calls[0][1].body)).toMatchObject({
    changed_by: "staff_demo",
    run_agent: false,
  });
});
it("已取消读取不会发往后端", async () => {
  const c = new AbortController();
  c.abort();
  const transport = vi.fn();
  await expect(
    new HttpAdapter("", transport).health(c.signal),
  ).rejects.toMatchObject({ code: "CANCELLED" });
  expect(transport).not.toHaveBeenCalled();
});
it("500作为真实错误保留，不回退Mock", async () => {
  await expect(
    new HttpAdapter(
      "",
      vi
        .fn()
        .mockResolvedValue(new Response('{"detail":"error"}', { status: 500 })),
    ).health(),
  ).rejects.toMatchObject({ code: "HTTP_500" });
});
