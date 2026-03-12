# GeoResolver Frontend

React + MapLibre GL client for the GeoResolver API. Streams LLM resolution steps via SSE and renders the resulting GeoJSON boundary on a dark basemap.

## Development

```bash
npm install
npm run dev        # Vite dev server on :5173
npm run build      # Production build to dist/
```

## Stack

- React 19, TypeScript, Tailwind CSS 4
- MapLibre GL via `react-map-gl`
- Vite 7, ESLint with typescript-eslint
