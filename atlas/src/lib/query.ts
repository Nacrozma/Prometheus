import { useCallback, useEffect, useRef, useState } from "react";
import { AtlasError } from "./bridge";
import { onChange } from "./events";
import type { Topic } from "./schemas";

export interface Query<T> {
  data: T | undefined;
  error: AtlasError | undefined;
  loading: boolean;
  reload: () => void;
}

/**
 * Load data from the core and refetch when any of `topics` changes. Refetches are debounced so a
 * burst of change events causes one request.
 */
export function useAtlasQuery<T>(key: string, fetcher: () => Promise<T>, topics: readonly Topic[] = []): Query<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<AtlasError>();
  const [loading, setLoading] = useState(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const seq = useRef(0);

  const run = useCallback(() => {
    const mine = ++seq.current;
    fetcherRef
      .current()
      .then((d) => {
        if (mine !== seq.current) return;
        setData(d);
        setError(undefined);
      })
      .catch((e: unknown) => {
        if (mine !== seq.current) return;
        setError(e instanceof AtlasError ? e : new AtlasError("internal", String(e)));
      })
      .finally(() => {
        if (mine === seq.current) setLoading(false);
      });
  }, []);

  useEffect(() => {
    setLoading(true);
    run();
  }, [key, run]);

  const topicKey = topics.join(",");
  useEffect(() => {
    if (!topicKey) return;
    const wanted = new Set(topicKey.split(","));
    let timer: ReturnType<typeof setTimeout> | undefined;
    const off = onChange((topic) => {
      if (!wanted.has(topic)) return;
      clearTimeout(timer);
      timer = setTimeout(run, 120);
    });
    return () => {
      off();
      clearTimeout(timer);
    };
  }, [topicKey, run]);

  return { data, error, loading, reload: run };
}
