import { z } from "zod";
import {
  healthSchema,
  patientSchema,
  stateSchema,
  recordSchema,
  taskSchema,
  runSchema,
  traceSchema,
} from "./types";
import type { Adapter, RecordCreate } from "./types";
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
  }
}
export class HttpAdapter implements Adapter {
  readonly mode = "http" as const;
  private queue: Promise<void> = Promise.resolve();
  constructor(
    private base = "http://127.0.0.1:8000/api",
    private transport: typeof fetch = (...args) => globalThis.fetch(...args),
    private timeout = 15000,
    private actionTimeout = 180000,
  ) {}
  request<T>(
    path: string,
    schema: z.ZodType<T>,
    body?: unknown,
    signal?: AbortSignal,
    method: "GET" | "POST" | "DELETE" = body === undefined ? "GET" : "POST",
  ): Promise<T> {
    // 有界读取：同一客户端最多一个在途请求；写入不重试，不以超时推断未保存。
    const result = this.queue.then(() =>
      this.perform(path, schema, body, signal, method),
    );
    this.queue = result.then(
      () => undefined,
      () => undefined,
    );
    return result;
  }
  private async perform<T>(
    path: string,
    schema: z.ZodType<T>,
    body?: unknown,
    signal?: AbortSignal,
    method: "GET" | "POST" | "DELETE" = "GET",
  ): Promise<T> {
    if (signal?.aborted) throw new ApiError("CANCELLED", "读取已取消");
    const controller = new AbortController();
    const isWrite = method !== "GET";
    const timer = setTimeout(
      () => controller.abort(),
      isWrite ? this.actionTimeout : this.timeout,
    );
    const abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) controller.abort();
    try {
      const response = await this.transport(
        this.base.replace(/\/$/, "") + path,
        {
          method,
          headers: {
            Accept: "application/json",
            ...(body === undefined
              ? {}
              : { "Content-Type": "application/json" }),
          },
          body: body === undefined ? undefined : JSON.stringify(body),
          signal: controller.signal,
        },
      );
      const raw = await response.text();
      let data: unknown = raw;
      try {
        data = JSON.parse(raw);
      } catch {
        /* Preserve the HTTP error even for non-JSON proxy responses. */
      }
      if (!response.ok) {
        const labels: Record<number, string> = {
          404: "资源不存在",
          422: "输入校验失败",
          500: "后端执行异常",
          502: "后端 Agent 或工具调用失败",
        };
        throw new ApiError(
          `HTTP_${response.status}`,
          `${labels[response.status] || "接口请求失败"}（${response.status}）`,
          data,
        );
      }
      const parsed = schema.safeParse(data);
      if (!parsed.success)
        throw new ApiError(
          "INVALID_RESPONSE",
          "接口响应字段不符合当前源码模型",
          parsed.error.issues,
        );
      return parsed.data;
    } catch (e) {
      if (e instanceof ApiError) throw e;
      throw new ApiError(
        controller.signal.aborted ? "TIMEOUT_OR_ABORT" : "NETWORK_ERROR",
        controller.signal.aborted
          ? isWrite
            ? "等待超时：操作可能已保存，请先查询记录、任务或运行状态；不会自动重试"
            : "请求超时或已取消"
          : "后端连接失败；未切换前端模拟数据",
        e instanceof Error ? e.message : String(e),
      );
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
  }
  read<T>(path: string, schema: z.ZodType<T>, signal?: AbortSignal) {
    return this.request(path, schema, undefined, signal, "GET");
  }
  write<T>(
    path: string,
    schema: z.ZodType<T>,
    body: unknown,
    method: "POST" | "DELETE" = "POST",
  ) {
    return this.request(path, schema, body, undefined, method);
  }
  health(signal?: AbortSignal) {
    return this.request("/health", healthSchema, undefined, signal);
  }
  patients(signal?: AbortSignal) {
    return this.request(
      "/patients",
      z.object({ items: z.array(patientSchema) }),
      undefined,
      signal,
    ).then((r) => r.items);
  }
  async state(id: string, signal?: AbortSignal) {
    const s = await this.request(
      `/patients/${encodeURIComponent(id)}/state`,
      stateSchema,
      undefined,
      signal,
    );
    if (s.patient.id !== id)
      throw new ApiError("PATIENT_MISMATCH", "返回患者与当前选择不一致");
    return s;
  }
  records(id: string, signal?: AbortSignal) {
    return this.request(
      `/patients/${encodeURIComponent(id)}/records?days=7`,
      z.object({ items: z.array(recordSchema) }),
      undefined,
      signal,
    ).then((r) => r.items);
  }
  tasks(id: string, signal?: AbortSignal) {
    return this.request(
      `/patients/${encodeURIComponent(id)}/tasks`,
      z.object({ items: z.array(taskSchema) }),
      undefined,
      signal,
    ).then((r) => r.items);
  }
  runs(id: string, signal?: AbortSignal) {
    return this.request(
      `/patients/${encodeURIComponent(id)}/runs`,
      z.object({ items: z.array(runSchema) }),
      undefined,
      signal,
    ).then((r) => r.items);
  }
  trace(id: string, signal?: AbortSignal) {
    return this.request(
      `/runs/${encodeURIComponent(id)}`,
      traceSchema,
      undefined,
      signal,
    );
  }
  addRecord(id: string, data: RecordCreate) {
    return this.request(
      `/patients/${encodeURIComponent(id)}/records`,
      z.object({
        record: recordSchema,
        automation: z.record(z.string(), z.unknown()).nullable(),
      }),
      data,
    );
  }
  complete(id: string) {
    return this.request(
      `/tasks/${encodeURIComponent(id)}/complete`,
      z
        .object({
          task: taskSchema,
          reviews: z.array(z.record(z.string(), z.unknown())),
        })
        .passthrough(),
      {
        changed_by: "staff_demo",
        note: "医护演示工作人员人工确认完成",
        run_agent: false,
      },
    );
  }
}
