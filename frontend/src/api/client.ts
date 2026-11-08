import { HttpAdapter } from "./httpAdapter";
import { mockAdapter } from "./mockAdapter";
import type { Adapter } from "./types";
export function createClient(mode: string, base?: string): Adapter {
  if (mode === "http")
    return new HttpAdapter(
      base,
      undefined,
      undefined,
      writeTimeout(import.meta.env.VITE_API_WRITE_TIMEOUT_MS),
    );
  if (mode === "mock") return mockAdapter;
  throw new Error("VITE_API_MODE只允许http或mock");
}
export function writeTimeout(value?: string) {
  if (!value) return 180000;
  const timeout = Number(value);
  if (!Number.isFinite(timeout) || timeout <= 0)
    throw new Error("VITE_API_WRITE_TIMEOUT_MS 必须为正数毫秒");
  return timeout;
}
export const client = createClient(
  import.meta.env.VITE_API_MODE || "http",
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api",
);
