import { HttpAdapter } from "./httpAdapter";
import { mockAdapter } from "./mockAdapter";
import type { Adapter } from "./types";
export function createClient(mode: string, base?: string): Adapter {
  if (mode === "http") return new HttpAdapter(base);
  if (mode === "mock") return mockAdapter;
  throw new Error("VITE_API_MODE只允许http或mock");
}
export const client = createClient(
  import.meta.env.VITE_API_MODE || "http",
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api",
);
