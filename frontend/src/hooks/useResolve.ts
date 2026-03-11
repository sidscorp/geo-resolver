import { useState, useCallback, useRef } from "react";
import { resolveStream, resolveSync } from "../lib/api";
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

  const cancelRef = useRef<(() => void) | null>(null);

  const resolve = useCallback((query: string) => {
    if (cancelRef.current) cancelRef.current();

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

    const cancel = resolveStream(
      query,
      (step) => {
        setState((s) => ({ ...s, steps: [...s.steps, step] }));
      },
      (result) => {
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
      },
      (error) => {
        // Fallback to sync
        resolveSync(query)
          .then((result) => {
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
            setState((s) => ({
              ...s,
              isLoading: false,
              error: e.message || error,
            }));
          });
      },
    );

    cancelRef.current = cancel;
  }, []);

  return { ...state, resolve };
}
