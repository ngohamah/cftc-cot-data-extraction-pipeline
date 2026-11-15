-- Nightly schedule for the price ingest.
-- pg_cron can only run SQL, so it uses pg_net to POST to the ingest-price-bars Edge
-- Function, which does the HTTP work against Yahoo and the upserts. The function URL and
-- the shared secret are read from Supabase Vault at run time - they are configuration,
-- not code, so they are NOT in this migration. Create them once in the SQL editor:
--   select vault.create_secret('https://<ref>.supabase.co/functions/v1/ingest-price-bars', 'ingest_price_bars_url');
--   select vault.create_secret('<INGEST_PRICE_BARS_SECRET>', 'ingest_price_bars_secret');

-- Or enable both from Dashboard -> Database -> Extensions.
create extension if not exists pg_cron with schema pg_catalog;
grant usage on schema cron to postgres;
grant all privileges on all tables in schema cron to postgres;

create extension if not exists pg_net with schema extensions;

-- Re-runnable: drop any previous schedule with the same name first.
select cron.unschedule(jobid) from cron.job where jobname = 'ingest-price-bars-daily';

-- 01:15 UTC every day.
--   US futures/indices settle ~21:00 UTC and forex rolls at 22:00 UTC (5pm ET), so by
--   01:15 the previous day's bar is final. BTC-USD trades 7 days a week and its UTC day
--   has just closed. Runs on weekends are cheap no-ops for everything else (idempotent).
-- range=1mo re-fetches ~22 bars per asset each night: it heals any missed run and
-- re-writes the still-forming latest bar with its final values once the session closed.
select cron.schedule(
  'ingest-price-bars-daily',
  '15 1 * * *',
  $$
  select net.http_post(
    url     := (select decrypted_secret from vault.decrypted_secrets
                where name = 'ingest_price_bars_url'),
    headers := jsonb_build_object(
                 'Content-Type',  'application/json',
                 'x-cron-secret', (select decrypted_secret from vault.decrypted_secrets
                                   where name = 'ingest_price_bars_secret')
               ),
    body    := jsonb_build_object('range', '1mo'),
    timeout_milliseconds := 60000       -- pg_net's default is 5s; 16 assets need more
  );
  $$
);
