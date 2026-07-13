export type Asset = "SNAS" | "SAFE";
export type BenchmarkAsset = "LNAS";
export type RawPrediction = "UP" | "FLAT" | "DOWN";
export type PositionAction = "ENTER" | "HOLD" | "EXIT" | "CASH";

export interface Streak {
  type: "W" | "L";
  length: number;
}

export interface FilterCheck {
  pass: boolean;
  detail: string;
}

export interface BearGate {
  trendBreakdown: FilterCheck;
  trendAlignment: FilterCheck;
  relativeStrength: FilterCheck;
  liquidity: FilterCheck;
  pullbackNotExtended: FilterCheck;
  volatilitySpike: FilterCheck;
  overboughtPrecondition: FilterCheck;
  knnConfidence: FilterCheck;
}

export interface LiveSignal {
  asOfSessionDate: string;
  asOfTimestamp: string;
  rawPrediction: RawPrediction;
  recommendedAsset: Asset;
  action: PositionAction;
  currentlyHolding: Asset;
  confidence: number;
  sessionsSinceLastExit: number | null;
  cooldownActive: boolean;
  gate: BearGate;
  lastPrices: {
    SNAS: number;
    SAFE: number;
    LNAS: number;
  };
  trainingSamples: number;
}

export interface AssetBreakdownEntry {
  trades: number;
  wins: number;
  losses: number;
  winRatePct: number;
  dollarPnl: number;
  contributionPct: number;
}

export interface AssetBreakdown {
  SNAS: AssetBreakdownEntry;
  SAFE: AssetBreakdownEntry;
}

export interface LedgerRow {
  date: string;
  asset: Asset;
  action: PositionAction;
  rawPrediction: RawPrediction;
  rawConfidence: number;
  gate: BearGate;
  snasPrice: number;
  safePrice: number;
  intervalReturnPct: number;
  portfolioValueBefore: number;
  portfolioValueAfter: number;
  cumulativeReturnPct: number;
}

export interface PortfolioMetrics {
  initialCapital: number;
  currentValue: number;
  totalReturnPct: number;
  totalTrades: number;
  wins: number;
  losses: number;
  cashSessions: number;
  winRatePct: number;
  maxDrawdownPct: number;
  sharpeRatio: number;
  sortinoRatio: number;
  calmarRatio: number;
  currentStreak: Streak | null;
  assetBreakdown: AssetBreakdown;
  ledger: LedgerRow[];
  buyHoldLnasReturnPct: number;
  buyHoldLnasMaxDrawdownPct: number;
  beatBuyHoldLnas: boolean;
  avoidedDrawdownVsLnasPct: number;
  buyHoldNdxReturnPct: number;
  beatBuyHoldNdx: boolean;
}

export interface ChartPoint {
  date: string | null;
  portfolioValue: number;
  cumulativeProfit: number;
}

export interface ValidationWindow extends Omit<PortfolioMetrics, "ledger"> {
  windowIndex: number;
  startDate: string;
  endDate: string;
}

export interface ValidationSummary {
  windowsEvaluated: number;
  meanWinRatePct?: number;
  stdDevWinRatePct?: number;
  meanTotalReturnPct?: number;
  stdDevTotalReturnPct?: number;
  meanTradesPerWindow?: number;
  meanCashSessionsPerWindow?: number;
  meanSharpeRatio?: number;
  stdDevSharpeRatio?: number;
  meanMaxDrawdownPct?: number;
  meanBuyHoldLnasReturnPct?: number;
  windowsBeatingBuyHoldLnas?: number;
  meanAvoidedDrawdownVsLnasPct?: number;
  meanBuyHoldNdxReturnPct?: number;
  windowsBeatingBuyHoldNdx?: number;
}

export interface Validation {
  windows: ValidationWindow[];
  summary: ValidationSummary;
}

export interface StrategyMeta {
  strategy: string;
  relationToLnasSnas: string;
  tickers: { bear: string; safe: string; lnasBenchmark: string; reference: string };
  model: {
    type: string;
    k: number;
    distance: string;
    classes: string[];
    flatBandPct: number;
    minKnnConfidence: number;
    features: string[];
    entryGate: string[];
    continuationGate: string;
    cooldownSessionsAfterExit: number;
  };
  rebalanceSchedule: string;
  decisionCutoffLocal: string;
  trainWindowWeeks: number;
  holdoutWindowWeeks: number;
  timezone: string;
  brokerageFees: number;
  splitHandling: string;
}

export interface StrategyData {
  generatedAt: string | null;
  status?: "awaiting_first_run";
  meta: StrategyMeta;
  liveSignal: LiveSignal | null;
  portfolio: PortfolioMetrics;
  chartSeries: ChartPoint[];
  validation: Validation;
}

export interface WorkflowStatus {
  status: string | null;
  conclusion: string | null;
  name: string | null;
  runStartedAt: string | null;
  updatedAt: string | null;
  htmlUrl: string | null;
  event: string | null;
  runNumber: number | null;
  error?: string;
}
