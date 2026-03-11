import type { StepInfo } from "../lib/api";

interface Props {
  steps: StepInfo[];
  isLoading: boolean;
}

function formatArgs(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(", ");
}

export default function StepsPanel({ steps, isLoading }: Props) {
  if (steps.length === 0 && !isLoading) return null;

  return (
    <div className="glass p-3 max-w-xs max-h-64 overflow-y-auto">
      <div className="text-xs text-neutral-500 uppercase tracking-wider mb-2">Steps</div>
      <ol className="space-y-1 text-xs font-mono text-neutral-300 list-decimal list-inside">
        {steps.map((s, i) => (
          <li key={i} className="truncate" title={`${s.tool}(${formatArgs(s.args)})`}>
            <span className="text-blue-400">{s.tool}</span>
            <span className="text-neutral-500">({formatArgs(s.args)})</span>
          </li>
        ))}
      </ol>
      {isLoading && (
        <div className="mt-2 text-xs text-neutral-500 animate-pulse">Resolving...</div>
      )}
    </div>
  );
}
