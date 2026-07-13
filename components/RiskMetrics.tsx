import { Activity, ArrowDownToLine, Gauge, Target } from "lucide-react";
import type { PortfolioMetrics } from "@/lib/types";
import StatTile from "./StatTile";

function toneForRatio(value: number): "good" | "bad" | "neutral" {
  if (value > 1) return "good";
  if (value < 0) return "bad";
  return "neutral";
}

export default function RiskMetrics({ portfolio }: { portfolio: PortfolioMetrics }) {
  const { sharpeRatio: sharpe, sortinoRatio: sortino, maxDrawdownPct: maxDrawdown, calmarRatio: calmar } = portfolio;

  return (
    <div className="rounded-xl border border-base-700 bg-base-850 p-5">
      <h2 className="mb-1 flex items-center gap-2 text-sm font-medium text-[var(--text-secondary)]">
        <Activity size={16} className="text-[var(--series-profit)]" />
        Risk-Adjusted Performance
      </h2>
      <p className="mb-4 text-xs text-[var(--text-muted)]">
        Annualized off the fixed Tuesday/Friday rebalance cadence, zero risk-free rate. Computed over every
        session (cash included), not just sessions holding SNAS.
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label="Sharpe Ratio" value={sharpe.toFixed(2)} icon={<Gauge size={14} />} tone={toneForRatio(sharpe)} />
        <StatTile label="Sortino Ratio" value={sortino.toFixed(2)} icon={<Activity size={14} />} tone={toneForRatio(sortino)} />
        <StatTile
          label="Max Drawdown"
          value={`${maxDrawdown.toFixed(2)}%`}
          icon={<ArrowDownToLine size={14} />}
          tone={maxDrawdown < -20 ? "bad" : "neutral"}
        />
        <StatTile label="Calmar Ratio" value={calmar.toFixed(2)} icon={<Target size={14} />} tone={toneForRatio(calmar)} />
      </div>
    </div>
  );
}
