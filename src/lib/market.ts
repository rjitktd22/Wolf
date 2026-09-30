export type CandlePack = {
  t0: string;
  barMin: number;
  t: number[];
  o: number[];
  h: number[];
  l: number[];
  c: number[];
  v: number[];
  offset?: number;
  nFull?: number;
};

export type Zone = {
  id: number;
  dir: "BUY" | "SELL";
  t0: string;
  t1: string;
  i0: number;
  i1: number;
  lo: number;
  hi: number;
  mid: number;
  exp: number;
  score: number;
  model: string;
  touched?: boolean;
  hit04?: boolean;
  mfe?: number;
};

export type MonthlyRow = {
  n: number;
  touch: number;
  hit: number;
  hit_given_touch: number;
};

export type SplitMetrics = {
  n: number;
  touch: number;
  touch_pct: number;
  hit04: number;
  hit04_pct: number;
  hit04_given_touch: number;
  avg_mfe: number;
  avg_mae: number;
  payoff: number;
  buy: number;
  sell: number;
};

export type FamilyRow = {
  model: string;
  label: string;
  n: number;
  hit04_given_touch: number;
  touch_pct: number;
  hit04_pct: number;
  oos_hit: number;
  oos_n: number;
  payoff: number;
  note: string;
};

export type Metrics = {
  n: number;
  touch: number;
  touch_pct: number;
  hit04: number;
  hit04_pct: number;
  hit04_given_touch: number;
  inval_first: number;
  avg_mfe: number;
  avg_mae: number;
  payoff: number;
  avg_exp: number;
  median_exp: number;
  buy: number;
  sell: number;
  model: string;
  name: string;
  min_move: number;
  half_ratio: number;
  bars: number;
  from: string;
  to: string;
  split: string;
  monthly: Record<string, MonthlyRow>;
  is: SplitMetrics;
  oos: SplitMetrics;
  families: FamilyRow[];
  extra?: string;
  dev?: number;
};

export type MarketBundle = {
  candles: CandlePack;
  zones: Zone[];
  metrics: Metrics;
  rawZones: Zone[];
};

function px(tenths: number) {
  return tenths / 10;
}

export function candleTime(pack: CandlePack, i: number): Date {
  const t0 = new Date(pack.t0);
  return new Date(t0.getTime() + pack.t[i]! * 60_000);
}

export function ohlc(pack: CandlePack, i: number) {
  return {
    t: candleTime(pack, i),
    o: px(pack.o[i]!),
    h: px(pack.h[i]!),
    l: px(pack.l[i]!),
    c: px(pack.c[i]!),
    v: pack.v[i]!,
  };
}

function shiftZones(zones: Zone[], offset: number): Zone[] {
  return zones
    .filter((z) => z.i1 >= offset)
    .map((z) => ({
      ...z,
      i0: Math.max(0, z.i0 - offset),
      i1: z.i1 - offset,
    }));
}

export async function loadMarket(): Promise<MarketBundle> {
  const [candles, zones, metrics] = await Promise.all([
    fetch("/data/candles-1m.json").then((r) => {
      if (!r.ok) throw new Error("Не удалось загрузить свечи");
      return r.json() as Promise<CandlePack>;
    }),
    fetch("/data/zones.json").then((r) => {
      if (!r.ok) throw new Error("Не удалось загрузить зоны");
      return r.json() as Promise<Zone[]>;
    }),
    fetch("/data/metrics.json").then((r) => {
      if (!r.ok) throw new Error("Не удалось загрузить метрики");
      return r.json() as Promise<Metrics>;
    }),
  ]);
  const offset = candles.offset ?? 0;
  return {
    candles,
    zones: shiftZones(zones, offset),
    rawZones: zones,
    metrics,
  };
}

export async function loadFullCandles(): Promise<CandlePack> {
  const r = await fetch("/data/candles.json");
  if (!r.ok) throw new Error("Не удалось загрузить полную ленту");
  return r.json() as Promise<CandlePack>;
}

export function formatPx(n: number, digits = 1) {
  return n.toLocaleString("ru-RU", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatPct(n: number, digits = 1) {
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}%`;
}

export function formatWhen(d: Date) {
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mi = String(d.getMinutes()).padStart(2, "0");
  return `${dd}.${mm} ${hh}:${mi}`;
}

export const RANGE_PRESETS = [
  { id: "1D", bars: 220, label: "1Д" },
  { id: "5D", bars: 1100, label: "5Д" },
  { id: "1M", bars: 4500, label: "1М" },
  { id: "3M", bars: 14000, label: "3М" },
  { id: "6M", bars: 28000, label: "6М" },
  { id: "ALL", bars: 0, label: "Всё" },
] as const;

export type RangeId = (typeof RANGE_PRESETS)[number]["id"];
