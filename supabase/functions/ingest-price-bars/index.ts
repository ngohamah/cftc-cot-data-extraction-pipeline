// Ingests daily OHLC bars from Yahoo Finance into public.price_bars.
//
//   POST { range?: "1mo" | "1y" | "max" | ..., assets?: string[] }   -> ingest
//   GET                                                               -> list enabled assets
//
// Both require the x-cron-secret header (CRON_SECRET). SUPABASE_URL and
// SUPABASE_SERVICE_ROLE_KEY are injected by the platform.
//
// Design: store raw Yahoo bars, daily interval only, every
// run idempotent (upsert on asset + bar_date), one asset failing never aborts the others,
// and every attempt - success or failure - leaves a row in price_ingest_runs.
import { createClient } from "jsr:@supabase/supabase-js@2";

const YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart";
const UPSERT_CHUNK = 500;
const DEFAULT_RANGE = "1mo";

type AssetRow = { asset: string; yahoo_symbol: string };

type Bar = {
  asset: string;
  bar_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  source: "yahoo";
};

type YahooQuote = {
  open?: Array<number | null>;
  high?: Array<number | null>;
  low?: Array<number | null>;
  close?: Array<number | null>;
  volume?: Array<number | null>;
};

type YahooResult = {
  meta?: { exchangeTimezoneName?: string; regularMarketPrice?: number };
  timestamp?: number[];
  indicators?: { quote?: YahooQuote[] };
};

type AssetSummary = { asset: string; bars?: number; error?: string };

// Yahoo stamps a daily bar with the session start in the *exchange's* timezone
// (midnight New York for GC=F, etc.). Converting that instant to a calendar date in the
// same timezone is what gives a stable, correct trading day. 'en-CA' formats YYYY-MM-DD.
export function barDate(unixSeconds: number, timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(unixSeconds * 1000));
}

async function fetchYahoo(symbol: string, range: string): Promise<YahooResult> {
  const url = `${YAHOO_CHART}/${encodeURIComponent(symbol)}?range=${encodeURIComponent(range)}&interval=1d`;
  const res = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0" } });
  if (!res.ok) throw new Error(`Yahoo responded ${res.status} for ${symbol}`);
  const json = await res.json();
  const result: YahooResult | undefined = json?.chart?.result?.[0];
  if (!result) {
    throw new Error(`No chart result for ${symbol}: ${JSON.stringify(json?.chart?.error ?? null)}`);
  }
  return result;
}

export function parseBars(asset: string, result: YahooResult): Bar[] {
  const tz = result.meta?.exchangeTimezoneName ?? "UTC";
  const quote = result.indicators?.quote?.[0] ?? {};
  const timestamps = result.timestamp ?? [];

  // Keyed by date: Yahoo occasionally repeats a timestamp - last one wins, and the
  // (asset, bar_date) upsert below can never see a duplicate key in one batch.
  const byDate = new Map<string, Bar>();
  for (let i = 0; i < timestamps.length; i++) {
    const o = quote.open?.[i];
    const h = quote.high?.[i];
    const l = quote.low?.[i];
    const c = quote.close?.[i];
    if (o == null || h == null || l == null || c == null) continue;
    const date = barDate(timestamps[i], tz);
    byDate.set(date, {
      asset,
      bar_date: date,
      open: o,
      high: h,
      low: l,
      close: c,
      volume: quote.volume?.[i] ?? 0,
      source: "yahoo",
    });
  }
  return [...byDate.values()];
}

Deno.serve(async (req) => {
  if (req.headers.get("x-cron-secret") !== Deno.env.get("CRON_SECRET")) {
    return new Response("unauthorized", { status: 401 });
  }

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );

  const body = req.method === "POST" ? await req.json().catch(() => ({})) : {};
  const range: string = typeof body.range === "string" && body.range ? body.range : DEFAULT_RANGE;
  const only: string[] | undefined = Array.isArray(body.assets) ? body.assets : undefined;

  let query = supabase.from("price_assets").select("asset,yahoo_symbol").eq("enabled", true);
  if (only?.length) query = query.in("asset", only);
  const { data: assets, error } = await query;
  if (error) return Response.json({ error: error.message }, { status: 500 });

  if (req.method === "GET") {
    return Response.json({ assets: (assets as AssetRow[]).map((a) => a.asset) });
  }

  const summary: AssetSummary[] = [];

  for (const a of assets as AssetRow[]) {
    const started_at = new Date().toISOString();
    try {
      const result = await fetchYahoo(a.yahoo_symbol, range);
      const rows = parseBars(a.asset, result);

      for (let i = 0; i < rows.length; i += UPSERT_CHUNK) {
        const { error: upsertError } = await supabase
          .from("price_bars")
          .upsert(rows.slice(i, i + UPSERT_CHUNK), { onConflict: "asset,bar_date" });
        if (upsertError) throw new Error(upsertError.message);
      }

      // The API's forex close-repair needs a live price for the latest bar; this is
      // the closest thing to one we get without a live feed.
      await supabase
        .from("price_assets")
        .update({
          last_price: result.meta?.regularMarketPrice ?? null,
          last_price_at: new Date().toISOString(),
        })
        .eq("asset", a.asset);

      await supabase.from("price_ingest_runs").insert({
        asset: a.asset, range, started_at, bars_upserted: rows.length, ok: true,
      });
      summary.push({ asset: a.asset, bars: rows.length });
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      console.error(`ingest failed for ${a.asset} (${a.yahoo_symbol}, range=${range}): ${message}`);
      await supabase.from("price_ingest_runs").insert({
        asset: a.asset, range, started_at, bars_upserted: 0, ok: false, error: message,
      });
      summary.push({ asset: a.asset, error: message });
    }
  }

  const failed = summary.filter((s) => s.error).length;
  return Response.json(
    { range, assets: summary.length, failed, summary },
    { status: failed ? 207 : 200 },
  );
});
