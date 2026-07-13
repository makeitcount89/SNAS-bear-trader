import { CircleDollarSign, LineChart, Percent, ShieldCheck, Scale, TrendingUp, Trophy, Wallet } from "lucide-react";
import type { PortfolioMetrics } from "@/lib/types";
import { formatCurrency, formatPct } from "@/lib/utils";
import StatTile from "./StatTile";

export default function PortfolioStats({ portfolio }: { portfolio: PortfolioMetrics }) {
  const positive = portfolio.totalReturnPct >= 0;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-8">
      <StatTile
        label="Portfolio Value"
        value={formatCurrency(portfolio.currentValue)}
        icon={<Wallet size={14} />}
      />
      <StatTile
        label="Total Return"
        value={formatPct(portfolio.totalReturnPct, { signed: true })}
        icon={<TrendingUp size={14} />}
        tone={positive ? "good" : "bad"}
      />
      <StatTile
        label="Win Rate (SNAS trades)"
        value={`${portfolio.winRatePct.toFixed(1)}%`}
        icon={<Percent size={14} />}
      />
      <StatTile
        label="SNAS Trades / Streak"
        value={
          portfolio.totalTrades === 0
            ? "0"
            : `${portfolio.wins + portfolio.losses} · ${portfolio.currentStreak?.type ?? "–"}${portfolio.currentStreak?.length ?? ""}`
        }
        icon={<Trophy size={14} />}
      />
      <StatTile
        label="Cash Sessions"
        value={`${portfolio.cashSessions}`}
        icon={<CircleDollarSign size={14} />}
      />
      <StatTile
        label="Avoided Drawdown vs LNAS"
        value={formatPct(portfolio.avoidedDrawdownVsLnasPct, { signed: true })}
        icon={<ShieldCheck size={14} />}
        tone={portfolio.avoidedDrawdownVsLnasPct >= 0 ? "good" : "bad"}
      />
      <StatTile
        label="vs Buy & Hold LNAS"
        value={formatPct(portfolio.buyHoldLnasReturnPct, { signed: true })}
        icon={<Scale size={14} />}
        tone={portfolio.beatBuyHoldLnas ? "good" : "bad"}
      />
      <StatTile
        label="vs Buy & Hold ^NDX"
        value={formatPct(portfolio.buyHoldNdxReturnPct, { signed: true })}
        icon={<LineChart size={14} />}
        tone={portfolio.beatBuyHoldNdx ? "good" : "bad"}
      />
    </div>
  );
}
