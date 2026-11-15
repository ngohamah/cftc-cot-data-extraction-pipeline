# Database migrations: how and why

A plain-language guide to how this project changes its Supabase database, and why it works this way.

A 33-second animated version is at <https://claude.ai/artifact/Dj4DsKJ3jA3kWtAHijCdS6>. The link is private
to its owner unless it is shared from the page's Share menu.

## What a migration is

Think of the database as a building, and a migration as one page of written instructions for changing it:
"add a room called `price_bars`", "install a timer that runs every night". Every page has a number, and the
pages are always carried out in number order.

This project's pages live in [`supabase/migrations/`](../supabase/migrations/):

| File | What it does |
|---|---|
| `20261115000000_price_pipeline_schema.sql` | Creates the price tables, fills in the 16 assets, adds the read function |
| `20261115000001_price_pipeline_cron.sql` | Turns on the scheduler and books the nightly 01:15 UTC ingest job |

The long number at the start of each name is a timestamp: year, month, day, hour, minute, second. Sorting by
it keeps the files in the order they were written.

The database keeps its own list of every migration it has already carried out, in the table
`supabase_migrations.schema_migrations`. It works like the stamp in a passport: when a migration runs, its
number is recorded, and it is never run again.

## How a change reaches the database

1. **Write a new file** in `supabase/migrations/` and open a pull request, like any other code change.
2. **Merge to `master`.** That starts the GitHub Action
   [`supabase-deploy.yml`](../.github/workflows/supabase-deploy.yml) ("Deploy Supabase (price pipeline)").
3. **The Action connects to the project** with `supabase link`.
4. **The Action pushes the migrations** with `supabase db push --remote --yes`. It compares the folder with
   the database's list and runs only the numbers that are missing, oldest first.
5. **The database records each one.** Run the deploy again and every number is already on the list, so
   nothing runs twice.

The same workflow then deploys the `ingest-price-bars` Edge Function and sets its secret.

### What each flag is for

The first deploys failed three times, and each failure was a safety check doing its job:

| Error | Cause | Fix |
|---|---|---|
| `connect ECONNREFUSED 127.0.0.1:54322` | Without `--remote`, the CLI looks for a local test database on the GitHub runner | `--remote` targets the linked project |
| `password authentication failed` | The CLI reached the real project, but the `SUPABASE_DB_PASSWORD` secret was wrong | Store the plain database password in the GitHub secret |
| `Confirmation required ... Re-run with --yes` | The CLI asks before changing production, and a CI run cannot answer | `--yes` confirms in automated runs |

## Why it works this way

- **Every change is written down.** Git shows exactly what changed, when and why, long after it happened.
- **Changes are reviewed first.** A pull request lets someone catch a mistake before it reaches the live database.
- **Every database ends up the same.** A test database and production get the same files in the same order.
- **Re-running is safe.** The list of applied migrations means a repeated deploy changes nothing.
- **Nobody clicks in the dashboard.** A change made by hand in the Supabase dashboard has no record and is easy
  to lose or forget.

## The rule: never edit a migration that already ran

The database will not run a file again once its number is on the list, so an edit would never take effect, and
the file would no longer describe what is really in the database. Add a new file instead. This creates one with
the right timestamp:

```sh
supabase migration new describe_your_change
```

Then write the SQL in the new file, open a pull request and merge it. The deploy applies it.

## Useful checks

Which migrations the live database has applied (Supabase SQL editor):

```sql
select version, name from supabase_migrations.schema_migrations order by version;
```

Compare your local folder with the live database (needs the Supabase CLI and a linked project; recent CLI
versions target a local database unless told `--remote`):

```sh
supabase migration list --remote
```

## Further learning

Videos (found by search, not reviewed):

- [Database Migrations Explained](https://www.youtube.com/watch?v=mMsZPZKNc4g): a general introduction.
- [Database Migrations for Beginners](https://www.youtube.com/watch?v=dJDBP7pPA-o): a beginner walkthrough using
  Flyway; the idea is the same as here.
- [Supabase local development video](https://www.youtube.com/watch?v=Kx5nHBmIxyQ): the video embedded in
  Supabase's migrations guide.
- [Perform Database Migration Using GitHub Actions and Supabase CLI](https://classcentral.com/course/youtube-perform-database-migration-using-github-actions-supabase-cli-217330):
  a listing for a video by Kunal Kushwaha that matches this setup closely.

Reading:

- [Supabase: database migrations](https://supabase.com/docs/guides/cli/migrations)
- [Supabase: local development overview](https://supabase.com/docs/guides/local-development/overview.md)
