import type { Adapter } from "./types";
import { ApiError } from "./httpAdapter";
// Explicit empty transport simulation, never imported as a fallback for HTTP errors.
export const mockAdapter: Adapter = {
  mode: "mock",
  health: async () => ({
    status: "frontend_mock",
    llm_mode: "not_connected",
    database: { ok: false },
  }),
  patients: async () => [],
  state: async () => {
    throw new ApiError("MOCK_EMPTY", "前端模拟数据：没有患者");
  },
  records: async () => [],
  tasks: async () => [],
  runs: async () => [],
  trace: async () => {
    throw new ApiError("MOCK_EMPTY", "前端模拟数据：没有轨迹");
  },
  addRecord: async () => {
    throw new ApiError("MOCK_READ_ONLY", "前端模拟模式不执行保存");
  },
  complete: async () => {
    throw new ApiError("MOCK_READ_ONLY", "前端模拟模式不执行保存");
  },
};
