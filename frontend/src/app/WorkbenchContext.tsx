import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { client } from "../api/client";
import { ApiError } from "../api/httpAdapter";
import { api } from "../api/workbench";
import { useResource } from "../hooks/useResource";
import type { Patient } from "../api/types";
type Boot = {
  patients: Patient[];
  health: Awaited<ReturnType<typeof client.health>>;
  mode: Awaited<ReturnType<typeof api.mode>>;
};
type Context = {
  boot?: Boot;
  error?: unknown;
  loading: boolean;
  patientId: string;
  patient?: Patient;
  busy: boolean;
  recovery?: {
    patientId: string;
    checked: boolean;
    data?: unknown;
    error?: unknown;
  };
  checkRecovery: () => Promise<void>;
  clearRecovery: () => void;
  setPatient: (id: string) => void;
  refresh: () => void;
  perform: <T>(action: () => Promise<T>) => Promise<T>;
};
const Context = createContext<Context | null>(null);
export function WorkbenchProvider({ children }: { children: ReactNode }) {
  const resource = useResource("boot", async (s) => {
    const health = await client.health(s);
    const patients = await client.patients(s);
    const mode = await api.mode(s);
    return { health, patients, mode };
  });
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const writeLock = useRef(false);
  const [recovery, setRecovery] = useState<Context["recovery"]>();
  const [heartbeat, setHeartbeat] = useState<{
    health?: Boot["health"];
    mode?: Boot["mode"];
    failed?: boolean;
  }>();
  useEffect(() => {
    if (!resource.data) return;
    const controller = new AbortController();
    let checking = false;
    const timer = setInterval(async () => {
      if (checking) return;
      checking = true;
      try {
        const health = await client.health(controller.signal);
        const mode = await api.mode(controller.signal);
        if (!controller.signal.aborted) setHeartbeat({ health, mode });
      } catch {
        if (!controller.signal.aborted) setHeartbeat({ failed: true });
      } finally {
        checking = false;
      }
    }, 30000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [resource.data]);
  const currentBoot = resource.data
    ? {
        ...resource.data,
        health: heartbeat?.failed
          ? {
              ...resource.data.health,
              status: "unreachable",
              database: { ...resource.data.health.database, ok: false },
            }
          : heartbeat?.health || resource.data.health,
        mode: heartbeat?.failed
          ? { ...resource.data.mode, llm_mode: "unknown", ok: false }
          : heartbeat?.mode || resource.data.mode,
      }
    : undefined;
  const pathId = location.pathname.startsWith("/patients/")
    ? decodeURIComponent(location.pathname.split("/")[2])
    : "";
  const requested = pathId || params.get("patient") || "";
  const saved = localStorage.getItem("workbench-patient") || "";
  const patientId =
    requested ||
    (resource.data?.patients.some((p) => p.id === saved)
      ? saved
      : resource.data?.patients[0]?.id) ||
    "";
  const patient = resource.data?.patients.find((p) => p.id === patientId);
  const setPatient = (id: string) => {
    if (busy) return;
    localStorage.setItem("workbench-patient", id);
    const next = new URLSearchParams(params);
    next.set("patient", id);
    for (const key of ["run", "task", "question", "review"]) next.delete(key);
    if (pathId) navigate("/patients/" + encodeURIComponent(id) + "?" + next);
    else setParams(next);
  };
  // Promise本身拒绝时仍由调用方展示，绝不将失败变成成功。
  async function perform<T>(action: () => Promise<T>): Promise<T> {
    if (recovery) throw new Error("上次操作结果待核对，请先查看已保存结果");
    if (writeLock.current) throw new Error("已有操作进行中，请勿重复提交");
    writeLock.current = true;
    setBusy(true);
    try {
      return await action();
    } catch (error) {
      if (
        error instanceof ApiError &&
        [
          "TIMEOUT_OR_ABORT",
          "NETWORK_ERROR",
          "INVALID_RESPONSE",
          "HTTP_500",
          "HTTP_502",
        ].includes(error.code)
      ) {
        setRecovery({ patientId, checked: false });
      }
      throw error;
    } finally {
      writeLock.current = false;
      setBusy(false);
    }
  }
  async function checkRecovery() {
    if (!recovery) return;
    const id = recovery.patientId;
    try {
      const records = await client.records(id);
      const runs = await client.runs(id);
      const tasks = await client.tasks(id);
      const questions = await api.questions(id);
      setRecovery({
        patientId: id,
        checked: true,
        data: { records, runs, tasks, questions },
      });
    } catch (error) {
      setRecovery({ patientId: id, checked: false, error });
    }
  }
  return (
    <Context.Provider
      value={{
        boot: currentBoot,
        error: resource.error,
        loading: resource.loading,
        patientId,
        patient,
        busy,
        recovery,
        checkRecovery,
        clearRecovery: () => {
          if (recovery?.checked) setRecovery(undefined);
        },
        setPatient,
        refresh: resource.reload,
        perform,
      }}
    >
      {children}
    </Context.Provider>
  );
}
export function useWorkbench() {
  const value = useContext(Context);
  if (!value) throw new Error("工作台上下文缺失");
  return value;
}
