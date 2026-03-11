interface Props {
  area_km2: number | null;
  geometry_type: string | null;
  geojson: GeoJSON.Feature | null;
  query: string | null;
}

function formatArea(km2: number): string {
  if (km2 >= 1_000_000) return `${(km2 / 1_000_000).toFixed(2)}M km²`;
  if (km2 >= 1_000) return `${(km2 / 1_000).toFixed(1)}K km²`;
  return `${km2.toFixed(1)} km²`;
}

export default function ResultMeta({ area_km2, geometry_type, geojson, query }: Props) {
  if (!geojson) return null;

  const handleDownload = () => {
    const blob = new Blob([JSON.stringify(geojson, null, 2)], { type: "application/geo+json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(query || "result").replace(/\s+/g, "_")}.geojson`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="glass p-3 space-y-2 min-w-[140px]">
      {area_km2 !== null && (
        <div>
          <div className="text-xs text-neutral-500">Area</div>
          <div className="text-sm font-mono">{formatArea(area_km2)}</div>
        </div>
      )}
      {geometry_type && (
        <div>
          <div className="text-xs text-neutral-500">Type</div>
          <div className="text-sm font-mono">{geometry_type}</div>
        </div>
      )}
      <button
        onClick={handleDownload}
        className="w-full text-xs text-blue-400 hover:text-blue-300 border border-blue-400/30 hover:border-blue-300/50 rounded-lg px-3 py-1.5 transition-colors"
      >
        Download GeoJSON
      </button>
    </div>
  );
}
