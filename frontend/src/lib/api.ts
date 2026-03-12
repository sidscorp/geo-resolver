export interface ResolveResult {
  query: string;
  geojson: GeoJSON.Feature;
  bounds: [number, number, number, number];
  area_km2: number;
  geometry_type: string;
  steps: StepInfo[];
}

export interface StepInfo {
  tool?: string;
  args?: Record<string, unknown>;
  message?: string;
  type?: string;
}

export async function resolveSync(
  query: string,
  signal?: AbortSignal,
): Promise<ResolveResult> {
  const res = await fetch("/api/resolve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
    signal,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Resolution failed");
  }
  return res.json();
}

export async function resolveStream(
  query: string,
  onStep: (step: StepInfo) => void,
  signal?: AbortSignal,
): Promise<ResolveResult> {
  const res = await fetch("/api/resolve/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
    signal,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Resolution failed");
  }

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: ResolveResult | null = null;
  let errorMsg: string | null = null;

  const parseEvents = () => {
    const parts = buffer.split("\n\n");
    buffer = parts.pop()!;
    for (const part of parts) {
      let eventType = "message";
      let data = "";
      for (const line of part.split("\n")) {
        if (line.startsWith("event:")) eventType = line.slice(6).trim();
        else if (line.startsWith("data:")) data = line.slice(5).trim();
      }
      if (!data) continue;
      if (eventType === "step") onStep(JSON.parse(data));
      else if (eventType === "result") result = JSON.parse(data);
      else if (eventType === "error") errorMsg = JSON.parse(data);
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (value) buffer += decoder.decode(value, { stream: true });
    if (done) buffer += decoder.decode();
    parseEvents();
    if (done) break;
  }

  if (buffer.trim()) {
    buffer += "\n\n";
    parseEvents();
  }

  if (errorMsg) throw new Error(errorMsg);
  if (!result) throw new Error("Stream ended without a result");
  return result;
}
