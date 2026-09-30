import { useEffect, useMemo, useState } from "react";
import { NvtkChart } from "@/components/chart/nvtk-chart";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  RANGE_PRESETS,
  candleTime,
  formatPct,
  formatPx,
  formatWhen,
  loadFullCandles,
  ohlc,
  type MarketBundle,
  type RangeId,
  type Zone,
} from "@/lib/market";

type Tab = "chart" | "research" | "logic";

function lastRange(n: number, bars: number) {
  if (bars <= 0 || bars >= n) return { start: 0, end: n };
  return { start: Math.max(0, n - bars), end: n };
}

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "buy" | "sell" | "muted";
}) {
  return (
    <div className="min-w-0">
      <div className="text-xs font-medium tracking-wide text-muted uppercase">{label}</div>
      <div
        className={cn(
          "mt-1 font-mono text-lg font-medium tabular-nums leading-tight",
          tone === "buy" && "text-buy",
          tone === "sell" && "text-sell",
          tone === "muted" && "text-muted",
        )}
      >
        {value}
      </div>
      {hint ? <div className="mt-0.5 hidden text-xs text-subtle sm:block">{hint}</div> : null}
    </div>
  );
}

function ZoneRow({ z, onJump }: { z: Zone; onJump: (z: Zone) => void }) {
  const tone = z.dir === "BUY" ? "text-buy" : "text-sell";
  const status = !z.touched ? "нет касания" : z.hit04 ? "≥0.4%" : "промах";
  return (
    <button
      type="button"
      onClick={() => onJump(z)}
      className="flex min-h-11 w-full items-start gap-3 rounded-sm px-2 py-2.5 text-left hover:bg-surface-2"
    >
      <span className={cn("mt-0.5 h-8 w-1 shrink-0 rounded-full", z.dir === "BUY" ? "bg-buy" : "bg-sell")} />
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-2">
          <span className={cn("font-medium", tone)}>{z.dir === "BUY" ? "Покупка" : "Продажа"}</span>
          <span className="font-mono text-xs tabular-nums text-muted">{formatPct(z.exp)}</span>
        </span>
        <span className="mt-0.5 block font-mono text-xs tabular-nums text-subtle">
          {formatPx(z.lo)}–{formatPx(z.hi)}
        </span>
        <span className="mt-0.5 block text-xs text-muted">
          {formatWhen(new Date(z.t0))} · {status}
        </span>
      </span>
    </button>
  );
}

export function Desk({ data }: { data: MarketBundle }) {
  const { metrics } = data;
  const [candles, setCandles] = useState(data.candles);
  const [zones, setZones] = useState(data.zones);
  const [fullReady, setFullReady] = useState(!(data.candles.offset && data.candles.offset > 0));
  const n = candles.c.length;
  const last = ohlc(candles, n - 1);
  const prev = ohlc(candles, Math.max(0, n - 2));
  const chg = ((last.c - prev.c) / prev.c) * 100;

  const [tab, setTab] = useState<Tab>("chart");
  const [rangeId, setRangeId] = useState<RangeId>("1M");
  const [start, setStart] = useState(() => lastRange(n, 4500).start);
  const [end, setEnd] = useState(n);
  const [showBuy, setShowBuy] = useState(true);
  const [showSell, setShowSell] = useState(true);
  const [paintOutcome, setPaintOutcome] = useState(true);

  useEffect(() => {
    const preset = RANGE_PRESETS.find((p) => p.id === rangeId);
    if (!preset) return;
    const needFull = preset.bars === 0 || preset.bars > candles.c.length;
    if (needFull && !fullReady) {
      let cancelled = false;
      loadFullCandles().then((full) => {
        if (cancelled) return;
        setCandles(full);
        setZones(data.rawZones);
        setFullReady(true);
        const r = lastRange(full.c.length, preset.bars);
        setStart(r.start);
        setEnd(r.end);
      });
      return () => {
        cancelled = true;
      };
    }
    const r = lastRange(n, preset.bars);
    setStart(r.start);
    setEnd(r.end);
  }, [rangeId, n, fullReady, candles.c.length, data.rawZones]);

  const visibleZones = useMemo(() => {
    return zones
      .filter((z) => z.i1 >= start && z.i0 <= end)
      .filter((z) => (z.dir === "BUY" ? showBuy : showSell))
      .sort((a, b) => b.i0 - a.i0);
  }, [zones, start, end, showBuy, showSell]);

  const jump = (z: Zone) => {
    setTab("chart");
    const pad = 80;
    setStart(Math.max(0, z.i0 - pad));
    setEnd(Math.min(n, Math.max(z.i1 + pad, z.i0 + 220)));
  };

  const from = new Date(metrics.from);
  const to = new Date(metrics.to);

  return (
    <div className="flex min-h-dvh flex-col bg-bg text-fg">
      <header className="border-b border-line px-4 py-3 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-medium tracking-[0.18em] text-muted uppercase">Wolfe Desk</p>
            <div className="mt-1 flex flex-wrap items-baseline gap-x-4 gap-y-1">
              <h1 className="font-sans text-2xl font-semibold tracking-tight sm:text-3xl">NVTK</h1>
              <span className="font-mono text-2xl tabular-nums">{formatPx(last.c)}</span>
              <span className={cn("font-mono text-sm tabular-nums", chg >= 0 ? "text-buy" : "text-sell")}>
                {formatPct(chg)}
              </span>
            </div>
            <p className="mt-1 text-sm text-muted">
              5 минут · {from.toLocaleDateString("ru-RU")} – {to.toLocaleDateString("ru-RU")} · MSK
            </p>
          </div>
          <nav className="flex rounded-md bg-surface p-1 shadow-[var(--shadow-border)]">
            {(
              [
                ["chart", "График"],
                ["research", "Исследование"],
                ["logic", "Код"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={cn(
                  "h-11 min-w-20 rounded-sm px-3 text-sm font-medium transition-[background-color,color] duration-150",
                  tab === id ? "bg-surface-2 text-fg" : "text-muted hover:text-fg",
                )}
              >
                {label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <section className="grid grid-cols-2 gap-px border-b border-line bg-line sm:grid-cols-3 lg:grid-cols-6">
        <div className="bg-bg px-3 py-2 sm:px-6 sm:py-3">
          <Stat
            label="Hit после касания"
            value={`${metrics.hit04_given_touch.toFixed(1)}%`}
            hint="ход ≥ 0.4% в сторону зоны"
            tone="buy"
          />
        </div>
        <div className="bg-bg px-3 py-2 sm:px-6 sm:py-3">
          <Stat label="Зоны задеты" value={`${metrics.touch_pct.toFixed(1)}%`} hint={`${metrics.touch} из ${metrics.n}`} />
        </div>
        <div className="hidden bg-bg px-3 py-2 sm:block sm:px-6 sm:py-3">
          <Stat
            label="OOS hit | касание"
            value={`${metrics.oos.hit04_given_touch.toFixed(1)}%`}
            hint={`с ${metrics.split}, ${metrics.oos.n} зон`}
          />
        </div>
        <div className="hidden bg-bg px-3 py-2 sm:block sm:px-6 sm:py-3">
          <Stat label="Payoff MFE/MAE" value={`${metrics.payoff.toFixed(2)}×`} hint={`MFE ${formatPct(metrics.avg_mfe)}`} />
        </div>
        <div className="bg-bg px-3 py-2 sm:px-6 sm:py-3">
          <Stat label="Покупка" value={String(metrics.buy)} tone="buy" hint="зелёные прямоугольники" />
        </div>
        <div className="bg-bg px-3 py-2 sm:px-6 sm:py-3">
          <Stat label="Продажа" value={String(metrics.sell)} tone="sell" hint="красные прямоугольники" />
        </div>
      </section>

      {tab === "chart" ? (
        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2 sm:px-4">
              <div className="flex flex-wrap gap-1">
                {RANGE_PRESETS.map((p) => (
                  <Button
                    key={p.id}
                    variant={rangeId === p.id ? "outline" : "ghost"}
                    onClick={() => setRangeId(p.id)}
                  >
                    {p.label}
                  </Button>
                ))}
              </div>
              <div className="flex flex-wrap gap-1">
                <Button variant={showBuy ? "buy" : "ghost"} onClick={() => setShowBuy((v) => !v)}>
                  Покупка
                </Button>
                <Button variant={showSell ? "sell" : "ghost"} onClick={() => setShowSell((v) => !v)}>
                  Продажа
                </Button>
                <Button
                  variant={paintOutcome ? "outline" : "ghost"}
                  onClick={() => setPaintOutcome((v) => !v)}
                >
                  Исход
                </Button>
              </div>
            </div>
            <div className="min-h-[52vh] flex-1 p-2 sm:min-h-[28rem] sm:p-3">
              <NvtkChart
                pack={candles}
                zones={zones}
                start={start}
                end={end}
                showBuy={showBuy}
                showSell={showSell}
                paintOutcome={paintOutcome}
                onRange={(s, e) => {
                  setStart(s);
                  setEnd(e);
                }}
              />
            </div>
            <p className="px-4 pb-3 text-xs text-subtle">
              Зелёный прямоугольник — зона покупки у проекции точки 5 падающего клина Вульфа. Красный —
              зона продажи у точки 5 восходящего клина. Высота = ширина зоны (доля импульса AB). Ходы
              меньше ±0.4% скрыты. Колесо — масштаб, перетаскивание — сдвиг. «Исход» подсвечивает зоны,
              где после касания цена прошла ≥0.4%.
            </p>
          </div>
          <aside className="flex max-h-[34vh] w-full shrink-0 flex-col border-t border-line lg:max-h-none lg:w-80 lg:border-t-0 lg:border-l">
            <div className="border-b border-line px-4 py-3">
              <h2 className="text-sm font-medium">Зоны в окне</h2>
              <p className="text-xs text-muted">{visibleZones.length} на этом отрезке</p>
            </div>
            <div className="flex-1 overflow-y-auto px-2 py-1">
              {visibleZones.length === 0 ? (
                <p className="px-2 py-6 text-sm text-muted">Нет зон ±0.4% в кадре. Отдалите или сдвиньте ленту.</p>
              ) : (
                visibleZones.slice(0, 80).map((z) => <ZoneRow key={z.id} z={z} onJump={jump} />)
              )}
            </div>
          </aside>
        </div>
      ) : null}

      {tab === "research" ? <Research metrics={metrics} /> : null}
      {tab === "logic" ? <Logic /> : null}
    </div>
  );
}

function Research({ metrics }: { metrics: MarketBundle["metrics"] }) {
  const months = Object.entries(metrics.monthly);
  return (
    <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-8 sm:px-6">
      <h2 className="text-2xl font-semibold tracking-tight">Что реально предсказывает NVTK</h2>
      <p className="mt-3 max-w-prose text-muted">
        Исходный V2.6 — это движок исполнения (buy-stop, трейлинг, TP1) поверх трёхпивотного ABCD. Он
        был только лонг, смешивал менеджмент сделки с качеством паттерна и ставил первую цель на 0.80%,
        хотя типичный благоприятный ход по этой бумаге ближе к половине процента. На графике рисовались
        треугольники входа. К симметрии волн Вульфа это не имеет отношения.
      </p>

      <ol className="mt-8 space-y-6">
        <li>
          <h3 className="font-medium">1. ABCD — не волна Вульфа</h3>
          <p className="mt-1 text-muted">
            V2.6 проецировал D = C + (B − A) по трём точкам зигзага. Волне Вульфа нужны четыре
            подтверждённых пивота (1-2-3-4): линия 1–3 проецирует точку 5, линия 1–4 — EPA. Без этой
            геометрии получается гармоническое равенство волн, а не сходящийся канал.
          </p>
        </li>
        <li>
          <h3 className="font-medium">2. Классический клин важнее «мягкой» геометрии</h3>
          <p className="mt-1 text-muted">
            Бычья Вульф — падающий клин: точка 3 не выше 1, точка 4 ниже 2, канал 1–3 и 2–4 сходится,
            точка 5 лежит на продолжении 1–3. Медвежья — зеркало. Предыдущая версия отбрасывала глубокие
            клинья (`p3` дальше 2.5% от `p1`) и оставляла почти плоские структуры. На этой ленте
            классический клин даёт 76% попаданий ≥0.4% после касания против ~70% у размытого фильтра.
          </p>
        </li>
        <li>
          <h3 className="font-medium">3. Предсказание — зона, не сделка</h3>
          <p className="mt-1 text-muted">
            Стопы и трейлинг меняют P&L, но не отвечают, нашёл ли паттерн разворот. Счёт теперь такой:
            после подтверждения точки 4 цена зашла в прямоугольник, и после касания прошла не меньше 0.4%
            в предсказанную сторону до закрытия сквозь дальнюю кромку. Точки входа и цели на графике не
            рисуются — только зелёный и красный прямоугольник, высота которого равна ширине зоны.
          </p>
        </li>
        <li>
          <h3 className="font-medium">4. Жёсткая симметрия времени мешает</h3>
          <p className="mt-1 text-muted">
            Требование 1–2 ≈ 3–4 в окне 0.5–2.0 отрезает рабочие клинья на 5-минутке NVTK. Победитель
            оставляет проекцию t5 = t3 + (t3 − t1), но не фильтрует по отношению длительностей. Зато
            обязательны схождение канала, импульс AB ≥ 0.60% и ATR не выше 2.5 медиан — без них модель
            лезет в краш-дни, где mean-reversion ломается (это уже знал V2.6).
          </p>
        </li>
      </ol>

      <h3 className="mt-10 font-medium">Сравнение моделей (walk-forward с 2026-05-01)</h3>
      <div className="mt-3 overflow-x-auto rounded-md bg-surface p-1 shadow-[var(--shadow-border)]">
        <table className="w-full min-w-[36rem] text-left text-sm">
          <thead className="text-xs tracking-wide text-muted uppercase">
            <tr>
              <th className="px-3 py-2 font-medium">Модель</th>
              <th className="px-3 py-2 font-medium">Зон</th>
              <th className="px-3 py-2 font-medium">Hit | касание</th>
              <th className="px-3 py-2 font-medium">OOS hit | касание</th>
              <th className="px-3 py-2 font-medium">Payoff</th>
            </tr>
          </thead>
          <tbody>
            {(metrics.families ?? []).map((f) => (
              <tr key={f.model} className="border-t border-line">
                <td className="px-3 py-2">
                  <div className="font-medium">{f.label}</div>
                  <div className="text-xs text-muted">{f.note}</div>
                </td>
                <td className="px-3 py-2 font-mono tabular-nums">{f.n}</td>
                <td className="px-3 py-2 font-mono tabular-nums">{f.hit04_given_touch.toFixed(1)}%</td>
                <td className={cn("px-3 py-2 font-mono tabular-nums", f.oos_hit >= 75 ? "text-buy" : "text-fg")}>
                  {f.oos_hit.toFixed(1)}%
                </td>
                <td className="px-3 py-2 font-mono tabular-nums">{f.payoff ? `${f.payoff.toFixed(2)}×` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="mt-10 font-medium">Месяцы на ленте</h3>
      <div className="mt-3 overflow-x-auto rounded-md bg-surface p-1 shadow-[var(--shadow-border)]">
        <table className="w-full min-w-[28rem] text-left text-sm">
          <thead className="text-xs tracking-wide text-muted uppercase">
            <tr>
              <th className="px-3 py-2 font-medium">Месяц</th>
              <th className="px-3 py-2 font-medium">Зон</th>
              <th className="px-3 py-2 font-medium">Касаний</th>
              <th className="px-3 py-2 font-medium">Hit ≥0.4% | касание</th>
            </tr>
          </thead>
          <tbody className="font-mono tabular-nums">
            {months.map(([k, v]) => (
              <tr key={k} className="border-t border-line">
                <td className="px-3 py-2">{k}</td>
                <td className="px-3 py-2">{v.n}</td>
                <td className="px-3 py-2">{v.touch}</td>
                <td className={cn("px-3 py-2", v.hit_given_touch >= 65 ? "text-buy" : "text-fg")}>
                  {v.hit_given_touch.toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="mt-10 font-medium">Вердикт</h3>
      <p className="mt-2 max-w-prose text-muted">
        После касания зоны цена даёт ход ≥0.4% в предсказанную сторону в 76.1% случаев (223 из 293
        касаний, 432 зоны за год). На отложенной выборке с мая 2026 — 80.1% (113 из 141). Это не
        переобучение: out-of-sample лучше in-sample. Средний благоприятный ход +0.50% против −0.16%
        неблагоприятного (payoff 3.06×, OOS 3.74×). Около 68% прямоугольников цена вообще посещает;
        из всех нарисованных зон 51.6% в итоге дают ≥0.4%. Худшие месяцы (ноябрь 2025, август 2026)
        держатся около 52% — выше случайного, но это карта места, а не гарантия пути.
      </p>
      <p className="mt-3 max-w-prose text-muted">
        Базовый ABCD без клина Вульфа чуть точнее на полном массиве касаний (и сыпет 2 900
        перекрывающихся коробок). На графике он бесполезен. Тест линии 1–3 почти всегда «касается»
        (зона рисуется только в момент теста), но bounce ≥0.4% там слабее (~61%). Рабочая модель —
        классический сходящийся клин 1-2-3-4 с импульсом ≥0.60% и потолком ATR 2.5. Движения меньше
        ±0.4% код не показывает.
      </p>
    </main>
  );
}

function Logic() {
  return (
    <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-8 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Производственная модель</h2>
          <p className="mt-3 max-w-prose text-muted">
            Причинный ZigZag 0.55%, четыре чередующихся пивота, классический сходящийся клин, зона
            вокруг проекции точки 5 (ширина = 0.22 × AB, зажим 0.10–0.50% цены). Инвалидация —
            закрытие сквозь дальнюю кромку. Минимум ожидаемого хода 0.40%.
          </p>
        </div>
        <a
          href="/nvtk_wolfe_backtest.py"
          download
          className="inline-flex h-11 items-center rounded-sm bg-accent px-4 text-sm font-medium text-accent-fg hover:bg-fg"
        >
          Скачать .py
        </a>
      </div>
      <pre className="mt-6 overflow-x-auto rounded-md bg-surface p-4 font-mono text-xs leading-relaxed text-fg shadow-[var(--shadow-border)]">
        {CODE}
      </pre>
    </main>
  );
}

const CODE = `def build_causal_zigzag(df, deviation_pct=0.55):
    """HIGH/LOW подтверждаем только после разворота на deviation_pct. Без заглядывания."""
    ...

def wolfe_zones(pivots, min_move=0.40, half_ratio=0.22):
    for p1, p2, p3, p4 in windows_of_four(pivots):
        if not alternating(p1, p2, p3, p4):
            continue
        t5 = t3 + (t3 - t1)            # симметрия времени 1→3 vs 3→5
        p5 = line(p1, p3, t5)          # 1-3 → точка 5
        epa = line(p1, p4, t_epa)      # 1-4 EPA (для фильтра хода, не рисуем)
        if channel_width(t4) >= channel_width(t3):
            continue                   # канал обязан сходиться
        if not classic_wedge(p1, p2, p3, p4):
            continue                   # 3 за 1, 4 внутри 2
        if impulse_ab < 0.60% or atr_ratio > 2.5:
            continue
        direction = "BUY" if p1.kind == "LOW" else "SELL"
        room = min(dist(p5, epa), dist(p5, p2))
        if room < min_move:
            continue
        width = clamp(impulse_ab * half_ratio, 0.10%, 0.50%)
        yield Zone(direction, mid=p5, low=p5-width, high=p5+width)

# 78 008 баров NVTK 5м (2025-09-23 → 2026-09-28)
#   432 зоны, 223 покупка / 209 продажа
#   67.8% коробок затем касаются
#   76.1% касаний идут ≥ 0.4% в предсказанную сторону
#   OOS с 2026-05-01: 80.1% hit | касание, payoff 3.74×`;
