import { useRef, useEffect, useCallback } from "react";
import Map, { Source, Layer, type MapRef } from "react-map-gl/maplibre";

interface Props {
  geojson: GeoJSON.Feature | null;
  bounds: [number, number, number, number] | null;
}

export default function MapView({ geojson, bounds }: Props) {
  const mapRef = useRef<MapRef>(null);

  const onLoad = useCallback(() => {
    if (bounds && mapRef.current) {
      mapRef.current.fitBounds(
        [
          [bounds[0], bounds[1]],
          [bounds[2], bounds[3]],
        ],
        { padding: 60, duration: 1200 },
      );
    }
  }, [bounds]);

  useEffect(() => {
    if (bounds && mapRef.current) {
      mapRef.current.fitBounds(
        [
          [bounds[0], bounds[1]],
          [bounds[2], bounds[3]],
        ],
        { padding: 60, duration: 1200 },
      );
    }
  }, [bounds]);

  return (
    <Map
      ref={mapRef}
      onLoad={onLoad}
      initialViewState={{ longitude: 0, latitude: 20, zoom: 1.5 }}
      style={{ width: "100%", height: "100%" }}
      mapStyle="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
      attributionControl={false}
    >
      {geojson && (
        <Source id="result" type="geojson" data={geojson}>
          <Layer
            id="result-fill"
            type="fill"
            paint={{
              "fill-color": "#3b82f6",
              "fill-opacity": 0.25,
            }}
          />
          <Layer
            id="result-outline"
            type="line"
            paint={{
              "line-color": "#60a5fa",
              "line-width": 2,
            }}
          />
        </Source>
      )}
    </Map>
  );
}
