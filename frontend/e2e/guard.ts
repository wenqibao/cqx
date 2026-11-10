export default async function guard() {
  const base = process.env.WORKBENCH_API_BASE || "http://127.0.0.1:8020/api";
  const health = await (await fetch(base + "/health")).json();
  if (
    health.llm_mode !== "mock" ||
    !String(health.database?.path)
      .replaceAll("\\", "/")
      .endsWith("/frontend/.runtime/workbench-test.db")
  )
    throw new Error(
      "E2E只允许专用workbench-test.db与后端mock，防止重置共享数据或意外收费",
    );
}
