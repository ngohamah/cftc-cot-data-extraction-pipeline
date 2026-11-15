-- Price bars for the COT assets, ingested daily from Yahoo Finance.
-- Raw Yahoo values; inversion / forex close-repair happen in the API read path.

create table if not exists public.price_assets (
  asset         text primary key,             -- frontend asset name, e.g. 'GOLD', 'EURUSD'
  signal_file   text not null,                -- cot_analysis signal/<signal_file>.csv
  yahoo_symbol  text not null,
  invert        boolean not null default false, -- Yahoo quotes USD per currency; flip on read
  is_forex      boolean not null default false,
  enabled       boolean not null default true,
  last_price    double precision,             -- Yahoo regularMarketPrice at last ingest
  last_price_at timestamptz
);

create table if not exists public.price_bars (
  asset      text not null references public.price_assets (asset) on delete cascade,
  bar_date   date not null,                   -- trading day in the exchange's timezone
  open       double precision not null,
  high       double precision not null,
  low        double precision not null,
  close      double precision not null,
  volume     bigint not null default 0,
  source     text not null default 'yahoo',
  fetched_at timestamptz not null default now(),
  primary key (asset, bar_date)
);

create table if not exists public.price_ingest_runs (
  id            bigint generated always as identity primary key,
  asset         text not null,
  range         text not null,
  started_at    timestamptz not null,
  finished_at   timestamptz not null default now(),
  bars_upserted integer not null default 0,
  ok            boolean not null,
  error         text
);

-- Keep the log small: only the last 60 days matter for monitoring.
create index if not exists price_ingest_runs_started_at_idx
  on public.price_ingest_runs (started_at desc);

-- Only the service role (Edge Function) and the postgres role (API server over
-- DATABASE_URL) can touch these. RLS on + no policies = nothing via anon/authenticated.
alter table public.price_assets      enable row level security;
alter table public.price_bars        enable row level security;
alter table public.price_ingest_runs enable row level security;

-- Seed the registry. Must stay in sync with src/lib/assets.ts in the frontend repo and
-- with PRICE_ASSETS in config.py (tests/test_backfill_price_bars.py checks the latter).
insert into public.price_assets (asset, signal_file, yahoo_symbol, invert, is_forex) values
  ('AUDUSD',    'AUSTRALIAN',        'AUDUSD=X', false, true),
  ('CADUSD',    'CANADIAN DOLLAR',   'CADUSD=X', false, true),
  ('CHFUSD',    'SWISS FRANC',       'USDCHF=X', true,  true),
  ('EURUSD',    'EURO FX',           'EURUSD=X', false, true),
  ('GBPUSD',    'POUND',             'GBPUSD=X', false, true),
  ('JPYUSD',    'JAPANESE YEN',      'USDJPY=X', true,  true),
  ('NZDUSD',    'NEW ZEALAND',       'NZDUSD=X', false, true),
  ('CRUDE OIL', 'CRUDE OIL',         'CL=F',     false, false),
  ('COPPER',    'COPPER',            'HG=F',     false, false),
  ('GOLD',      'GOLD',              'GC=F',     false, false),
  ('PLATINUM',  'PLATINUM',          'PL=F',     false, false),
  ('SILVER',    'SILVER',            'SI=F',     false, false),
  ('DOW',       'DJIA Consolidated', '^DJI',     false, false),
  ('NASDAQ',    'NASDAQ-100',        '^NDX',     false, false),
  ('BITCOIN',   'BITCOIN',           'BTC-USD',  false, false),
  ('USD INDEX', 'U.S. DOLLAR INDEX', 'DX-Y.NYB', false, false)
on conflict (asset) do nothing;

-- Read function used by the API server. Returns daily bars, or weekly bars aggregated
-- from the daily ones (Monday-stamped, like Yahoo's own weekly bars).
-- bar_date is returned as text (YYYY-MM-DD) on purpose: node-postgres parses a `date`
-- column into a JS Date at *local* midnight, which shifts the day on non-UTC hosts.
create or replace function public.price_bars_range(
  p_asset    text,
  p_from     date,
  p_interval text default '1d'           -- '1d' | '1wk'
)
returns table (
  bar_date text,
  open     double precision,
  high     double precision,
  low      double precision,
  close    double precision,
  volume   bigint
)
language sql
stable
as $$
  select
    to_char(bar_date, 'YYYY-MM-DD'),
    open, high, low, close, volume
  from public.price_bars
  where p_interval = '1d' and asset = p_asset and bar_date >= p_from
  union all
  select
    to_char(week_start, 'YYYY-MM-DD'),
    open, high, low, close, volume
  from (
    select
      date_trunc('week', bar_date)::date                      as week_start,
      (array_agg(open  order by bar_date asc))[1]              as open,
      max(high)                                                as high,
      min(low)                                                 as low,
      (array_agg(close order by bar_date desc))[1]             as close,
      sum(volume)                                              as volume
    from public.price_bars
    where p_interval = '1wk' and asset = p_asset and bar_date >= p_from
    group by 1
  ) w
  order by 1;
$$;
