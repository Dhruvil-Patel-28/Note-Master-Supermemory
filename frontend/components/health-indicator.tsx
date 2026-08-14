"use client";

import { useEffect, useState } from "react";
import { api, HealthStatus } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export default function HealthIndicator() {
  const [health, setHealth] = useState<HealthStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const h = await api.health();
        if (!cancelled) setHealth(h);
      } catch {
        if (!cancelled) setHealth(null);
      }
    }
    check();
    const t = setInterval(check, 30000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  const ok = health?.status === "ok";
  const degraded = health?.status === "degraded";
  const offline = health === null;

  const label = offline
    ? "Backend unreachable"
    : degraded
      ? "Backend up, Ollama unreachable"
      : "All systems up";

  const dot = offline
    ? "bg-destructive"
    : degraded
      ? "bg-yellow-500"
      : "bg-green-500";

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={label}
          className={cn(
            "inline-flex size-8 items-center justify-center rounded-lg hover:bg-muted",
            offline && "animate-pulse"
          )}
        >
          <span className={cn("size-2 rounded-full", dot)} />
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom" align="end">
        {label}
        {health && (
          <div className="mt-1 space-y-0.5 text-xs">
            <div>Database: {health.database ? "ok" : "down"}</div>
            <div>Ollama: {health.ollama ? "ok" : "down"}</div>
          </div>
        )}
      </TooltipContent>
    </Tooltip>
  );
}