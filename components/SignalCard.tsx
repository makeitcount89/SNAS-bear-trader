"use client";

import { ArrowDownRight, CircleDollarSign, RefreshCw, Zap } from "lucide-react";
import type { Asset, BearGate, FilterCheck, LiveSignal, PositionAction } from "@/lib/types";
import { cn, formatDateTime } from "@/lib/utils";

interface Props {
  signal: LiveSignal | null;
  loading: boolean;
  onRefresh: () => void;
}

const ASSET_PRESENTATION: Record<Asset, { label: string; subtitle: string; badge: string; icon: React.ReactNode }> = {
  SNAS: {
    label: "SNAS",
    subtitle: "SNAS.AX (Short Geared)",
    badge: "bg-short-muted text-short",
    icon: <ArrowDownRight size={30} />,
  },
  SAFE: {
    label: "CASH",
    subtitle: "AAA.AX (Safe Asset)",
    badge: "bg-safe-muted text-safe",
    icon: <CircleDollarSign size={28} />,
  },
};

const ACTION_LABEL: Record<PositionAction, string> = {
  ENTER: "Entering SNAS",
  HOLD: "Holding",
  EXIT: "Exiting to cash",
  CASH: "Staying in cash",
};

const ACTION_BADGE: Record<PositionAction, string> = {
  ENTER: "bg-short-muted text-short",
  HOLD: "bg-accent-muted text-accent",
  EXIT: "bg-base-700 text-[var(--text-muted)]",
  CASH: "bg-base-800 text-[var(--text-muted)]",
};

const GATE_LABELS: Record<keyof BearGate, string> = {
  trendBreakdown: "Trend breakdown (close < MA20 < MA50)",
  trendAlignment: "GMMA trend alignment",
  relativeStrength: "Relative strength (20d & 60d)",
  liquidity: "Above-average liquidity",
  pullbackNotExtended: "Pullback, not extended",
  volatilitySpike: "Volatility spike",
  overboughtPrecondition: "Fell from a 5-year overbought high",
  knnConfidence: "k-NN confidence ≥ 60%",
};

// Entry requires all 8 gate conditions to agree at once. Once in SNAS, only the
// first 5 (trendBreakdown, trendAlignment, relativeStrength, liquidity,
// pullbackNotExtended) are re-checked each session to decide whether to keep
// holding; volatilitySpike, overboughtPrecondition and knnConfidence are
// entry-only triggers, matching the asymmetric entry/hold design in engine.py.
const CONTINUATION_KEYS: (keyof BearGate)[] = [
  "trendBreakdown",
  "trendAlignment",
  "relativeStrength",
  "liquidity",
  "pullbackNotExtended",
];

function GateRow({ label, check, dimmed }: { label: string; check: FilterCheck; dimmed?: boolean }) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 rounded-lg border border-base-700 bg-base-800/60 px-3 py-2",
        dimmed && "opacity-60"
      )}
    >
      <div className="min-w-0">
        <div className="text-xs font-medium text-[var(--text-primary)]">{label}</div>
        <div className="truncate text-[11px] text-[var(--text-muted)]">{check.detail}</div>
      </div>
      <span
        className={cn(
          "flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold",
          check.pass ? "bg-long-muted text-long" : "bg-short-muted text-short"
        )}
      >
        {check.pass ? "✓" : "✗"}
      </span>
    </div>
  );
}

export default function SignalCard({ signal, loading, onRefresh }: Props) {
  const presentation = signal ? ASSET_PRESENTATION[signal.recommendedAsset] : null;
  const gateEntries = signal ? (Object.keys(signal.gate) as (keyof BearGate)[]) : [];
  const allPass = signal ? gateEntries.every((k) => signal.gate[k].pass) : false;

  return (
    <div className="rounded-xl border border-base-700 bg-base-850 p-5">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-medium text-[var(--text-secondary)]">
          <Zap size={16} className="text-[var(--series-profit)]" />
          Live Actionable Signal
        </h2>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-md border border-base-600 bg-base-800 px-3 py-1.5 text-xs font-medium text-[var(--text-primary)] transition hover:bg-base-700 disabled:opacity-50"
        >
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          Query Live Signal Now
        </button>
      </div>

      {!signal || !presentation ? (
        <div className="mt-6 flex flex-col items-center justify-center gap-2 py-8 text-center">
          <p className="text-sm text-[var(--text-secondary)]">
            No live signal yet. The engine publishes one after its first scheduled Tuesday/Friday run.
          </p>
        </div>
      ) : (
        <>
          <div className="mt-5 flex items-center gap-4">
            <div className={cn("flex h-16 w-16 shrink-0 items-center justify-center rounded-full text-2xl font-bold", presentation.badge)}>
              {presentation.icon}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <div className="text-3xl font-bold tracking-tight">
                  {presentation.label}
                  <span className="ml-2 text-base font-normal text-[var(--text-muted)]">{presentation.subtitle}</span>
                </div>
                <span className={cn("rounded-md px-2 py-0.5 text-xs font-medium", ACTION_BADGE[signal.action])}>
                  {ACTION_LABEL[signal.action]}
                </span>
              </div>
              <div className="mt-1 text-sm text-[var(--text-secondary)]">
                k-NN confidence: <span className="font-semibold text-[var(--text-primary)]">{(signal.confidence * 100).toFixed(0)}%</span>
              </div>
              {signal.recommendedAsset === "SAFE" && signal.currentlyHolding === "SAFE" && (
                <div className="mt-1 text-xs text-[var(--text-muted)]">
                  {allPass
                    ? "All 8 gate conditions currently agree, but a cooldown from a recent exit is blocking re-entry."
                    : "Default cash position — not all 8 gate conditions below agree yet, so no reason to leave cash."}
                </div>
              )}
              {signal.recommendedAsset === "SNAS" && signal.action === "ENTER" && (
                <div className="mt-1 text-xs text-[var(--text-muted)]">
                  All 8 gate conditions below agree simultaneously — rotating out of cash into SNAS.
                </div>
              )}
              {signal.recommendedAsset === "SNAS" && signal.action === "HOLD" && (
                <div className="mt-1 text-xs text-[var(--text-muted)]">
                  The 5 continuation conditions (dimmed rows are entry-only) still hold, so staying in SNAS.
                </div>
              )}
              {signal.action === "EXIT" && (
                <div className="mt-1 text-xs text-[var(--text-muted)]">
                  At least one continuation condition failed below — exiting SNAS back to cash.
                </div>
              )}
              {signal.cooldownActive && (
                <div className="mt-1 text-xs text-[var(--status-warning)]">
                  Cooldown active — {signal.sessionsSinceLastExit} of 4 sessions since the last exit; re-entry is blocked
                  regardless of the gate below.
                </div>
              )}
            </div>
          </div>

          <div className="mt-5 border-t border-base-700 pt-4">
            <div className="mb-2 text-xs text-[var(--text-muted)]">
              Entry gate — all 8 must agree to leave cash. Dimmed rows (volatility spike, overbought precondition,
              k-NN confidence) are entry-only triggers and aren&apos;t required to keep holding once in SNAS.
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {gateEntries.map((key) => (
                <GateRow
                  key={key}
                  label={GATE_LABELS[key]}
                  check={signal.gate[key]}
                  dimmed={!CONTINUATION_KEYS.includes(key)}
                />
              ))}
            </div>
          </div>

          <dl className="mt-4 grid grid-cols-3 gap-4 border-t border-base-700 pt-4 text-sm">
            <div>
              <dt className="text-xs text-[var(--text-muted)]">SNAS.AX price</dt>
              <dd className="tabular font-medium">${signal.lastPrices.SNAS.toFixed(3)}</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--text-muted)]">AAA.AX (safe) price</dt>
              <dd className="tabular font-medium">${signal.lastPrices.SAFE.toFixed(3)}</dd>
            </div>
            <div>
              <dt className="text-xs text-[var(--text-muted)]">LNAS.AX price (benchmark only)</dt>
              <dd className="tabular font-medium">${signal.lastPrices.LNAS.toFixed(3)}</dd>
            </div>
          </dl>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--text-muted)]">
            <span>As of {formatDateTime(signal.asOfTimestamp)}</span>
            <span>{signal.trainingSamples} training samples</span>
          </div>
        </>
      )}
    </div>
  );
}
