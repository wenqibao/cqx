import { useEffect, useState } from "react";
export function useResource<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{
    key: string;
    revision: number;
    data?: T;
    error?: unknown;
    loading: boolean;
  }>({ key: "", revision: 0, loading: true });
  useEffect(() => {
    const c = new AbortController();
    setState({ key, revision, loading: true });
    load(c.signal)
      .then((data) => {
        if (!c.signal.aborted)
          setState({ key, revision, data, loading: false });
      })
      .catch((error) => {
        if (!c.signal.aborted)
          setState({ key, revision, error, loading: false });
      });
    return () => c.abort();
  }, [key, revision]);
  // key变化的第一帧就隐藏旧患者数据，不能等effect执行后再清空。
  return {
    ...(state.key === key && state.revision === revision
      ? state
      : { loading: true, data: undefined, error: undefined }),
    reload: () => setRevision((n) => n + 1),
  };
}
