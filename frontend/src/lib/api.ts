export interface ResolveResult {
  query: string;
  geojson: GeoJSON.Feature;
  bounds: [number, number, number, number];
  area_km2: number;
  geometry_type: string;
  steps: StepInfo[];
}

export interface StepInfo {
  tool: string;
  args: Record<string, unknown>;
}

export async function resolveSync(query: string): Promise<ResolveResult> {
  const res = await fetch("/api/resolve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Resolution failed");
  }
  return res.json();
}

export function resolveStream(
  query: string,
  onStep: (step: StepInfo) => void,
  onResult: (result: ResolveResult) => void,
  onError: (error: string) => void,
): () => void {
  const ctrl = new AbortController();

  (async () => {
    try {
      const res = await fetch("/api/resolve/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
        signal: ctrl.signal,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        onError(err.detail || "Resolution failed");
        return;
      }

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let eventType = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            const data = JSON.parse(line.slice(6));
            if (eventType === "step") onStep(data);
            else if (eventType === "result") onResult(data);
            else if (eventType === "error") onError(data);
          }
        }
      }
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      onError(e instanceof Error ? e.message : "Stream failed");
    }
  })();

  return () => ctrl.abort();
}
