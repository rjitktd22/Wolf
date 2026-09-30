import { useEffect, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { Desk } from "@/components/desk/desk";
import { loadMarket, type MarketBundle } from "@/lib/market";

export const Route = createFileRoute("/")({ component: Home });

function Home() {
  const [data, setData] = useState<MarketBundle | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    loadMarket()
      .then((bundle) => {
        if (live) setData(bundle);
      })
      .catch((err: unknown) => {
        if (live) setError(err instanceof Error ? err.message : "Ошибка загрузки");
      });
    return () => {
      live = false;
    };
  }, []);

  if (error) {
    return (
      <main className="flex min-h-dvh flex-col items-center justify-center gap-2 bg-bg px-6 text-center text-fg">
        <h1 className="text-lg font-semibold">Ленту не удалось открыть</h1>
        <p className="max-w-md text-sm text-muted">{error}</p>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="flex min-h-dvh flex-col justify-end bg-bg px-6 pb-16 text-fg">
        <p className="text-xs font-medium tracking-[0.18em] text-muted uppercase">Wolfe Desk</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">Читаю NVTK…</h1>
        <p className="mt-2 max-w-md text-muted">78 тысяч 5-минутных баров и зоны Вульфа.</p>
      </main>
    );
  }

  return <Desk data={data} />;
}
