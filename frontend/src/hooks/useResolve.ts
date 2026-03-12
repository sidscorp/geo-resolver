import { useState, useCallback, useRef } from "react";
import { resolveStream } from "../lib/api";
import type { StepInfo } from "../lib/api";

export interface ResolveState {
  geojson: GeoJSON.Feature | null;
  bounds: [number, number, number, number] | null;
  area_km2: number | null;
  geometry_type: string | null;
  steps: StepInfo[];
  isLoading: boolean;
  error: string | null;
  query: string | null;
}

export function useResolve() {
  const [state, setState] = useState<ResolveState>({
    geojson: null,
    bounds: null,
    area_km2: null,
    geometry_type: null,
    steps: [],
    isLoading: false,
    error: null,
    query: null,
  });

  const abortRef = useRef<AbortController | null>(null);

  const resolve = useCallback((query: string) => {
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    setState({
      geojson: null,
      bounds: null,
      area_km2: null,
      geometry_type: null,
      steps: [],
      isLoading: true,
      error: null,
      query,
    });

    resolveStream(
      query,
      (step) => {
        if (ctrl.signal.aborted) return;
        setState((s) => ({ ...s, steps: [...s.steps, step] }));
      },
      ctrl.signal,
    )
      .then((result) => {
        if (ctrl.signal.aborted) return;
        setState({
          geojson: result.geojson,
          bounds: result.bounds,
          area_km2: result.area_km2,
          geometry_type: result.geometry_type,
          steps: result.steps,
          isLoading: false,
          error: null,
          query: result.query,
        });
      })
      .catch((e) => {
        if (ctrl.signal.aborted) return;
        setState((s) => ({
          ...s,
          isLoading: false,
          error: e.message || "Resolution failed",
        }));
      });
  }, []);

  return { ...state, resolve };
}
