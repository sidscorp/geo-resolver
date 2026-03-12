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
    <div className="glass p-3 max-w-sm max-h-72 overflow-y-auto">
      <div className="text-xs text-neutral-500 uppercase tracking-wider mb-2">Progress</div>
      <ul className="space-y-1.5 text-sm text-neutral-300">
        {steps.map((s, i) => {
          const isThinking = s.type === "thinking";
          const isLast = i === steps.length - 1;
          return (
            <li
              key={i}
              className={`flex items-start gap-2 ${isLast && isLoading ? "animate-pulse" : ""}`}
              title={s.tool ? `${s.tool}(${formatArgs(s.args ?? {})})` : undefined}
            >
              <span className="mt-0.5 text-xs shrink-0">
                {isThinking ? (
                  <span className="text-yellow-400/70">💭</span>
                ) : s.tool === "finalize" ? (
                  <span className="text-green-400">✓</span>
                ) : (
                  <span className="text-blue-400">→</span>
                )}
              </span>
              <span className={isThinking ? "text-neutral-400 italic text-xs" : ""}>
                {s.message || (s.tool ? `${s.tool}(${formatArgs(s.args ?? {})})` : "...")}
              </span>
            </li>
          );
        })}
      </ul>
      {isLoading && (
        <div className="mt-2 text-xs text-neutral-500 animate-pulse">Resolving...</div>
      )}
    </div>
  );
}
