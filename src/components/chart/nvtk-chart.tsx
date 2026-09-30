import { useCallback, useEffect, useRef } from "react";
import {
  candleTime,
  formatPct,
  formatPx,
  formatWhen,
  type CandlePack,
  type Zone,
} from "@/lib/market";

type Props = {
  pack: CandlePack;
  zones: Zone[];
  start: number;
  end: number;
  showBuy: boolean;
  showSell: boolean;
  paintOutcome: boolean;
  onRange: (start: number, end: number) => void;
};

type Palette = {
  bg: string;
  fg: string;
  muted: string;
  line: string;
  buy: string;
  sell: string;
  accent: string;
};

const PAD = { l: 8, r: 64, t: 12, b: 44, vol: 52 };

function readPalette(el: HTMLElement): Palette {
  const s = getComputedStyle(el);
  const v = (name: string, fb: string) => s.getPropertyValue(name).trim() || fb;
  return {
    bg: v("--color-bg", "#0b0c0e"),
    fg: v("--color-fg", "#e6e4dc"),
    muted: v("--color-muted", "#8b8e96"),
    line: v("--color-line", "rgba(230,228,220,0.1)"),
    buy: v("--color-buy", "#2e9a68"),
    sell: v("--color-sell", "#c75b4a"),
    accent: v("--color-accent", "#c4c7ce"),
  };
}

function hexAlpha(hex: string, a: number) {
  const h = hex.trim();
  if (h.startsWith("rgb")) {
    return h.replace("rgb(", "rgba(").replace(")", `, ${a})`);
  }
  const m = /^#?([0-9a-f]{6})$/i.exec(h);
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

export function NvtkChart({
  pack,
  zones,
  start,
  end,
  showBuy,
  showSell,
  paintOutcome,
  onRange,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hoverRef = useRef<HTMLDivElement>(null);
  const state = useRef({
    start,
    end,
    hover: -1,
    drag: false,
    lastX: 0,
    pal: null as Palette | null,
  });
  const onRangeRef = useRef(onRange);
  onRangeRef.current = onRange;
  state.current.start = start;
  state.current.end = end;

  const n = pack.c.length;

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const pal = state.current.pal ?? (state.current.pal = readPalette(wrap));
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = wrap.clientWidth;
    const h = wrap.clientHeight;
    if (w < 40 || h < 40) return;
    if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = pal.bg;
    ctx.fillRect(0, 0, w, h);

    const i0 = Math.max(0, Math.min(state.current.start, n - 2));
    const i1 = Math.max(i0 + 2, Math.min(n, state.current.end));
    const vis = i1 - i0;
    const plotW = w - PAD.l - PAD.r;
    const plotH = h - PAD.t - PAD.b - PAD.vol;
    const volTop = PAD.t + plotH + 8;
    const volH = PAD.vol - 16;
    if (plotW < 20 || plotH < 20) return;

    const bucket = Math.max(1, Math.ceil(vis / 1600));

    let minP = Infinity;
    let maxP = -Infinity;
    let maxV = 1;
    for (let i = i0; i < i1; i += bucket) {
      let hh = pack.h[i]! / 10;
      let ll = pack.l[i]! / 10;
      let vv = pack.v[i]!;
      for (let k = i + 1; k < i + bucket && k < i1; k++) {
        hh = Math.max(hh, pack.h[k]! / 10);
        ll = Math.min(ll, pack.l[k]! / 10);
        vv += pack.v[k]!;
      }
      if (hh > maxP) maxP = hh;
      if (ll < minP) minP = ll;
      if (vv > maxV) maxV = vv;
    }

    const cSpan = Math.max(maxP - minP, maxP * 0.004);
    const loBound = minP - cSpan * 0.8;
    const hiBound = maxP + cSpan * 0.8;

    for (const z of zones) {
      if (z.i1 < i0 || z.i0 > i1) continue;
      if (z.dir === "BUY" && !showBuy) continue;
      if (z.dir === "SELL" && !showSell) continue;
      if (z.lo >= loBound && z.lo <= hiBound && z.lo < minP) minP = z.lo;
      if (z.hi >= loBound && z.hi <= hiBound && z.hi > maxP) maxP = z.hi;
    }

    const padP = (maxP - minP) * 0.08 || 1;
    minP -= padP;
    maxP += padP;
    const span = maxP - minP || 1;

    const xAt = (idx: number) => PAD.l + ((idx - i0) / vis) * plotW;
    const yAt = (p: number) => PAD.t + ((maxP - p) / span) * plotH;

    ctx.strokeStyle = pal.line;
    ctx.lineWidth = 1;
    const ticks = 6;
    ctx.font = "11px IBM Plex Mono, ui-monospace, monospace";
    ctx.fillStyle = pal.muted;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    for (let t = 0; t <= ticks; t++) {
      const p = maxP - (span * t) / ticks;
      const y = yAt(p);
      ctx.beginPath();
      ctx.moveTo(PAD.l, y);
      ctx.lineTo(w - PAD.r, y);
      ctx.stroke();
      ctx.fillText(formatPx(p), w - PAD.r + 8, y);
    }

    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const labelEvery = Math.max(1, Math.round(vis / 6));
    let lastDay = "";
    for (let i = i0; i < i1; i += labelEvery) {
      const d = candleTime(pack, i);
      const day = `${d.getDate()}.${String(d.getMonth() + 1).padStart(2, "0")}`;
      const label =
        day !== lastDay
          ? `${day} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
          : `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
      lastDay = day;
      ctx.fillText(label, xAt(i), h - PAD.b + 10);
    }

    for (const z of zones) {
      if (z.i1 < i0 || z.i0 > i1) continue;
      if (z.dir === "BUY" && !showBuy) continue;
      if (z.dir === "SELL" && !showSell) continue;
      const color = z.dir === "BUY" ? pal.buy : pal.sell;
      const strong = paintOutcome ? Boolean(z.hit04) : true;
      const x = xAt(Math.max(z.i0, i0));
      const x2 = xAt(Math.min(z.i1, i1));
      const y = yAt(z.hi);
      const y2 = yAt(z.lo);
      const rw = Math.max(3, x2 - x);
      const rh = Math.max(3, y2 - y);
      ctx.fillStyle = hexAlpha(color, strong ? 0.28 : 0.1);
      ctx.fillRect(x, y, rw, rh);
      ctx.strokeStyle = hexAlpha(color, strong ? 0.92 : 0.35);
      ctx.lineWidth = strong ? 1.5 : 1;
      ctx.strokeRect(x + 0.5, y + 0.5, rw, rh);
    }

    const cw = Math.max(1.2, (plotW / vis) * bucket * 0.7);
    for (let i = i0; i < i1; i += bucket) {
      let oo = pack.o[i]! / 10;
      let hh = pack.h[i]! / 10;
      let ll = pack.l[i]! / 10;
      let cc = pack.c[Math.min(i1 - 1, i + bucket - 1)]! / 10;
      let vv = pack.v[i]!;
      for (let k = i + 1; k < i + bucket && k < i1; k++) {
        hh = Math.max(hh, pack.h[k]! / 10);
        ll = Math.min(ll, pack.l[k]! / 10);
        vv += pack.v[k]!;
        cc = pack.c[k]! / 10;
      }
      const x = xAt(i + bucket / 2);
      const up = cc >= oo;
      ctx.strokeStyle = up ? pal.buy : pal.sell;
      ctx.fillStyle = up ? pal.buy : pal.sell;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, yAt(hh));
      ctx.lineTo(x, yAt(ll));
      ctx.stroke();
      const yb = yAt(Math.max(oo, cc));
      const body = Math.max(1, Math.abs(yAt(oo) - yAt(cc)));
      ctx.fillRect(x - cw / 2, yb, cw, body);
      const vh = (vv / maxV) * volH;
      ctx.globalAlpha = 0.45;
      ctx.fillRect(x - cw / 2, volTop + volH - vh, cw, vh);
      ctx.globalAlpha = 1;
    }

    const hi = state.current.hover;
    if (hi >= i0 && hi < i1) {
      const x = xAt(hi);
      ctx.strokeStyle = hexAlpha(pal.accent, 0.35);
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(x, PAD.t);
      ctx.lineTo(x, PAD.t + plotH);
      ctx.stroke();
      ctx.setLineDash([]);
      const c = pack.c[hi]! / 10;
      ctx.fillStyle = pal.accent;
      ctx.beginPath();
      ctx.arc(x, yAt(c), 2.4, 0, Math.PI * 2);
      ctx.fill();
    }

    const hoverEl = hoverRef.current;
    if (hoverEl) {
      if (hi >= 0 && hi < n) {
        const d = candleTime(pack, hi);
        const o = pack.o[hi]! / 10;
        const high = pack.h[hi]! / 10;
        const low = pack.l[hi]! / 10;
        const c = pack.c[hi]! / 10;
        const chg = ((c - o) / o) * 100;
        const hitZ = zones.find(
          (z) =>
            z.i0 <= hi &&
            z.i1 >= hi &&
            ((z.dir === "BUY" && showBuy) || (z.dir === "SELL" && showSell)),
        );
        const zoneBit = hitZ
          ? `<span class="${hitZ.dir === "BUY" ? "text-buy" : "text-sell"}">${hitZ.dir === "BUY" ? "покупка" : "продажа"} ${formatPx(hitZ.lo)}–${formatPx(hitZ.hi)}</span>`
          : "";
        hoverEl.hidden = false;
        hoverEl.innerHTML = `<span class="text-muted">${formatWhen(d)}</span>
          <span>O ${formatPx(o)}</span>
          <span>H ${formatPx(high)}</span>
          <span>L ${formatPx(low)}</span>
          <span>C ${formatPx(c)}</span>
          <span class="${chg >= 0 ? "text-buy" : "text-sell"}">${formatPct(chg)}</span>
          ${zoneBit}`;
      } else {
        hoverEl.hidden = true;
      }
    }
  }, [pack, zones, n, showBuy, showSell, paintOutcome]);

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const ro = new ResizeObserver(() => draw());
    ro.observe(wrap);
    draw();
    return () => ro.disconnect();
  }, [draw, start, end]);

  useEffect(() => {
    draw();
  }, [draw, start, end, showBuy, showSell, zones, paintOutcome]);

  const idxFromX = (x: number) => {
    const wrap = wrapRef.current;
    if (!wrap) return 0;
    const plotW = wrap.clientWidth - PAD.l - PAD.r;
    const i0 = state.current.start;
    const vis = Math.max(1, state.current.end - i0);
    const rel = (x - PAD.l) / plotW;
    return Math.max(0, Math.min(n - 1, Math.floor(i0 + rel * vis)));
  };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const vis = state.current.end - state.current.start;
      const rect = canvas.getBoundingClientRect();
      const pivot = idxFromX(e.clientX - rect.left);
      const factor = e.deltaY > 0 ? 1.18 : 0.85;
      let next = Math.round(vis * factor);
      next = Math.max(40, Math.min(n, next));
      const ratio = vis > 0 ? (pivot - state.current.start) / vis : 0.5;
      let ns = Math.round(pivot - next * ratio);
      let ne = ns + next;
      if (ns < 0) {
        ne -= ns;
        ns = 0;
      }
      if (ne > n) {
        ns -= ne - n;
        ne = n;
      }
      onRangeRef.current(Math.max(0, ns), Math.min(n, ne));
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, [n]);

  return (
    <div className="relative h-full min-h-[52vh] w-full overflow-hidden rounded-md bg-bg sm:min-h-72">
      <canvas
        ref={canvasRef}
        className="block h-full w-full touch-none"
        onPointerDown={(e) => {
          (e.target as HTMLCanvasElement).setPointerCapture(e.pointerId);
          state.current.drag = true;
          state.current.lastX = e.nativeEvent.offsetX;
        }}
        onPointerMove={(e) => {
          const x = e.nativeEvent.offsetX;
          state.current.hover = idxFromX(x);
          if (state.current.drag) {
            const wrap = wrapRef.current;
            if (wrap) {
              const plotW = wrap.clientWidth - PAD.l - PAD.r;
              const vis = state.current.end - state.current.start;
              const dx = x - state.current.lastX;
              const db = Math.round((-dx / plotW) * vis);
              if (db !== 0) {
                let ns = state.current.start + db;
                let ne = state.current.end + db;
                if (ns < 0) {
                  ne -= ns;
                  ns = 0;
                }
                if (ne > n) {
                  ns -= ne - n;
                  ne = n;
                }
                ns = Math.max(0, ns);
                onRange(ns, Math.max(ns + 2, ne));
                state.current.lastX = x;
              }
            }
          }
          draw();
        }}
        onPointerUp={() => {
          state.current.drag = false;
        }}
        onPointerLeave={() => {
          state.current.hover = -1;
          state.current.drag = false;
          draw();
        }}
      />
      <div
        ref={hoverRef}
        hidden
        className="pointer-events-none absolute left-3 top-2 flex flex-wrap gap-x-3 gap-y-1 font-mono text-xs tabular-nums text-fg"
      />
    </div>
  );
}
