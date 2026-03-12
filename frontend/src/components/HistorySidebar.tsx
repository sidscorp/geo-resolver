interface HistoryEntry {
  query: string;
  geojson: GeoJSON.Feature;
  bounds: [number, number, number, number];
  area_km2: number;
  geometry_type: string;
}

interface Props {
  history: HistoryEntry[];
  onSelect: (entry: HistoryEntry) => void;
  isOpen: boolean;
  onToggle: () => void;
}

export default function HistorySidebar({ history, onSelect, isOpen, onToggle }: Props) {
  return (
    <div className="relative">
      <button
        onClick={onToggle}
        className="glass w-9 h-9 flex items-center justify-center text-neutral-400 hover:text-white transition-colors text-sm"
        title="History"
      >
        H
      </button>
      {isOpen && history.length > 0 && (
        <div className="absolute top-full right-0 glass p-3 w-64 max-h-80 overflow-y-auto mt-2">
          <div className="text-xs text-neutral-500 uppercase tracking-wider mb-2">History</div>
          <ul className="space-y-1">
            {history.map((entry, i) => (
              <li key={i}>
                <button
                  onClick={() => onSelect(entry)}
                  className="w-full text-left text-sm text-neutral-300 hover:text-white truncate py-1 px-2 rounded hover:bg-white/5 transition-colors"
                >
                  {entry.query}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export type { HistoryEntry };
