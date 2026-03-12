import { useState, useCallback, useRef, useEffect } from "react";
import { useResolve } from "./hooks/useResolve";
import MapView from "./components/MapView";
import SearchBar from "./components/SearchBar";
import StepsPanel from "./components/StepsPanel";
import ResultMeta from "./components/ResultMeta";
import HistorySidebar, { type HistoryEntry } from "./components/HistorySidebar";

export default function App() {
  const { geojson, bounds, area_km2, geometry_type, steps, isLoading, error, query, resolve } =
    useResolve();
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [displayState, setDisplayState] = useState<{
    geojson: GeoJSON.Feature | null;
    bounds: [number, number, number, number] | null;
    area_km2: number | null;
    geometry_type: string | null;
    query: string | null;
  }>({ geojson: null, bounds: null, area_km2: null, geometry_type: null, query: null });

  const handleSearch = useCallback(
    (q: string) => {
      resolve(q);
    },
    [resolve],
  );

  const prevGeojsonRef = useRef<GeoJSON.Feature | null>(null);
  useEffect(() => {
    if (geojson && geojson !== prevGeojsonRef.current) {
      prevGeojsonRef.current = geojson;
      setDisplayState({ geojson, bounds, area_km2, geometry_type, query });
      if (bounds && area_km2 !== null && geometry_type && query) {
        setHistory((h) => [{ query, geojson, bounds, area_km2, geometry_type }, ...h.slice(0, 19)]);
      }
    }
  }, [geojson, bounds, area_km2, geometry_type, query]);

  const handleHistorySelect = useCallback((entry: HistoryEntry) => {
    setDisplayState({
      geojson: entry.geojson,
      bounds: entry.bounds,
      area_km2: entry.area_km2,
      geometry_type: entry.geometry_type,
      query: entry.query,
    });
    setHistoryOpen(false);
  }, []);

  return (
    <div className="relative w-full h-full">
      <MapView geojson={displayState.geojson} bounds={displayState.bounds} />

      <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10 flex items-start gap-2 px-4 w-full max-w-2xl">
        <div className="flex-1">
          <SearchBar onSearch={handleSearch} isLoading={isLoading} />
        </div>
        <HistorySidebar
          history={history}
          onSelect={handleHistorySelect}
          isOpen={historyOpen}
          onToggle={() => setHistoryOpen((o) => !o)}
        />
      </div>

      {error && (
        <div className="absolute top-20 left-1/2 -translate-x-1/2 z-10 glass px-4 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      <div className="absolute bottom-4 left-4 z-10">
        <StepsPanel steps={steps} isLoading={isLoading} />
      </div>

      <div className="absolute bottom-4 right-4 z-10">
        <ResultMeta
          area_km2={displayState.area_km2}
          geometry_type={displayState.geometry_type}
          geojson={displayState.geojson}
          query={displayState.query}
        />
      </div>
    </div>
  );
}
