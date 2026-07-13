"use client";

import { Fragment, useState } from "react";
import { BookOpen, ChevronDown, ChevronRight } from "lucide-react";
import type { Asset, BearGate, LedgerRow, PositionAction } from "@/lib/types";
import { cn, formatCurrency, formatDate, formatPct } from "@/lib/utils";

const ASSET_BADGE: Record<Asset, string> = {
  SNAS: "bg-short-muted text-short",
  SAFE: "bg-safe-muted text-safe",
};

const ACTION_LABEL: Record<PositionAction, string> = {
  ENTER: "Enter",
  HOLD: "Hold",
  EXIT: "Exit",
  CASH: "Cash",
};

const ACTION_BADGE: Record<PositionAction, string> = {
  ENTER: "bg-short-muted text-short",
  HOLD: "bg-accent-muted text-accent",
  EXIT: "bg-base-700 text-[var(--text-muted)]",
  CASH: "bg-base-800 text-[var(--text-muted)]",
};

const GATE_LABELS: Record<keyof BearGate, string> = {
  trendBreakdown: "Trend breakdown",
  trendAlignment: "GMMA trend alignment",
  relativeStrength: "Relative strength",
  liquidity: "Above-average liquidity",
  pullbackNotExtended: "Pullback, not extended",
  volatilitySpike: "Volatility spike",
  overboughtPrecondition: "Fell from 5y overbought high",
  knnConfidence: "k-NN confidence ≥ 60%",
};

function GateDots({ gate }: { gate: BearGate }) {
  const keys = Object.keys(gate) as (keyof BearGate)[];
  return (
    <div className="flex items-center gap-1" title={keys.map((k) => `${GATE_LABELS[k]}: ${gate[k].pass ? "pass" : "fail"}`).join(" · ")}>
      {keys.map((k) => (
        <span key={k} className={cn("h-2 w-2 rounded-full", gate[k].pass ? "bg-long" : "bg-short")} />
      ))}
    </div>
  );
}

export default function LedgerTable({ ledger, holdoutWindowWeeks }: { ledger: LedgerRow[]; holdoutWindowWeeks?: number }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <div className="rounded-xl border border-base-700 bg-base-850 p-5">
      <h2 className="flex items-center gap-2 text-sm font-medium text-[var(--text-secondary)]">
        <BookOpen size={16} className="text-[var(--series-profit)]" />
        Trading Ledger
        <span className="ml-1 rounded-full bg-base-800 px-2 py-0.5 text-xs text-[var(--text-muted)]">
          {ledger.length} rows{holdoutWindowWeeks ? ` · ${holdoutWindowWeeks}-week holdout` : ""}
        </span>
      </h2>
      <p className="mt-1 text-xs text-[var(--text-muted)]">
        Click a row to see that session&apos;s raw k-NN call and all 8 gate conditions behind the action taken.
      </p>

      {ledger.length === 0 ? (
        <p className="mt-6 py-8 text-center text-sm text-[var(--text-secondary)]">
          The ledger populates once the first walk-forward backtest run completes.
        </p>
      ) : (
        <div className="mt-4 max-h-[520px] overflow-auto rounded-lg border border-base-700">
          <table className="w-full min-w-[920px] border-collapse text-sm">
            <thead className="sticky top-0 z-10 bg-base-800 text-xs text-[var(--text-muted)]">
              <tr>
                <th className="w-6 px-2 py-2"></th>
                <th className="px-3 py-2 text-left font-medium">Date</th>
                <th className="px-3 py-2 text-left font-medium">Asset</th>
                <th className="px-3 py-2 text-left font-medium">Action</th>
                <th className="px-3 py-2 text-left font-medium">Gate</th>
                <th className="px-3 py-2 text-right font-medium">SNAS Price</th>
                <th className="px-3 py-2 text-right font-medium">Safe Price</th>
                <th className="px-3 py-2 text-right font-medium">Interval Return</th>
                <th className="px-3 py-2 text-right font-medium">Portfolio Value</th>
                <th className="px-3 py-2 text-right font-medium">Cumulative</th>
              </tr>
            </thead>
            <tbody>
              {ledger
                .slice()
                .reverse()
                .map((row) => {
                  const positive = row.intervalReturnPct > 0;
                  const isCash = row.asset === "SAFE";
                  const isOpen = expanded === row.date;
                  return (
                    <Fragment key={row.date}>
                      <tr
                        onClick={() => setExpanded(isOpen ? null : row.date)}
                        className="cursor-pointer border-t border-base-700 hover:bg-base-800/60"
                      >
                        <td className="px-2 py-2 text-[var(--text-muted)]">
                          {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </td>
                        <td className="px-3 py-2 text-[var(--text-secondary)]">{formatDate(row.date)}</td>
                        <td className="px-3 py-2">
                          <span className={cn("rounded-md px-2 py-0.5 text-xs font-semibold", ASSET_BADGE[row.asset])}>
                            {row.asset === "SAFE" ? "CASH" : row.asset}
                          </span>
                        </td>
                        <td className="px-3 py-2">
                          <span className={cn("rounded-md px-2 py-0.5 text-xs font-medium", ACTION_BADGE[row.action])}>
                            {ACTION_LABEL[row.action]}
                          </span>
                        </td>
                        <td className="px-3 py-2">
                          <GateDots gate={row.gate} />
                        </td>
                        <td className="px-3 py-2 text-right tabular">${row.snasPrice.toFixed(3)}</td>
                        <td className="px-3 py-2 text-right tabular">${row.safePrice.toFixed(3)}</td>
                        <td
                          className={cn(
                            "px-3 py-2 text-right tabular font-medium",
                            isCash ? "text-[var(--text-muted)]" : positive ? "text-[var(--status-good)]" : "text-[var(--status-critical)]"
                          )}
                        >
                          {formatPct(row.intervalReturnPct, { signed: true })}
                        </td>
                        <td className="px-3 py-2 text-right tabular">{formatCurrency(row.portfolioValueAfter)}</td>
                        <td
                          className={cn(
                            "px-3 py-2 text-right tabular font-medium",
                            row.cumulativeReturnPct >= 0 ? "text-[var(--status-good)]" : "text-[var(--status-critical)]"
                          )}
                        >
                          {formatPct(row.cumulativeReturnPct, { signed: true })}
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="border-t border-base-700 bg-base-800/40">
                          <td colSpan={10} className="px-4 py-3">
                            <div className="mb-2 text-xs text-[var(--text-muted)]">
                              Raw k-NN call: <span className="font-medium text-[var(--text-secondary)]">{row.rawPrediction}</span> @{" "}
                              {(row.rawConfidence * 100).toFixed(0)}% confidence
                            </div>
                            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
                              {(Object.keys(row.gate) as (keyof BearGate)[]).map((k) => (
                                <div key={k} className="flex items-center justify-between gap-2 rounded-lg border border-base-700 bg-base-850 px-3 py-2">
                                  <div className="min-w-0">
                                    <div className="text-xs font-medium text-[var(--text-primary)]">{GATE_LABELS[k]}</div>
                                    <div className="truncate text-[11px] text-[var(--text-muted)]">{row.gate[k].detail}</div>
                                  </div>
                                  <span
                                    className={cn(
                                      "flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold",
                                      row.gate[k].pass ? "bg-long-muted text-long" : "bg-short-muted text-short"
                                    )}
                                  >
                                    {row.gate[k].pass ? "✓" : "✗"}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
