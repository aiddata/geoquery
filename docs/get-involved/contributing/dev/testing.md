---
description: "Running GeoQuery's backend and frontend tests, the type check, testing against a throwaway database, and conventions for writing tests."
---

# Testing

There is no test workflow in CI: the GitHub workflows build images, deploy and publish the docs. Run the relevant tests yourself before merging.

## Backend

Django's test runner, inside the `backend` container (the database publishes no port to the host):

```bash
docker compose exec backend uv run python manage.py test                 # everything
docker compose exec backend uv run python manage.py test public_api stats  # some apps
docker compose exec backend uv run python manage.py test analytics.tests.test_sync
```

The full suite is about 1,400 tests and takes a couple of minutes. Tests that publish Celery messages need RabbitMQ: with the `rabbitmq` service down they fail with connection errors (about 65 of them), which says nothing about your change.

### A throwaway database

To test a branch without touching your development database, start a separate Compose project with only the database, run the tests against it, and remove it:

```bash
docker compose -p scratch up -d db
docker compose -p scratch run --rm --no-deps backend uv run python manage.py test
docker compose -p scratch down -v
```

In a git worktree, pass the main checkout's `.env` with `--env-file`, and create empty `data/` and `requests/` directories first, since Compose mounts them.

### Writing backend tests

- **Reads from the standby.** Code that reads with `.using("replica")` won't see rows a `TestCase` created, because the alias opens its own connection outside the test's transaction. Mix in `geoquery.testing.ReplicaReadsTestMixin` ahead of `TestCase`.
- **Partitioned tables.** Each dataset's own `extract_tasks` and `extract_data` partitions are created by a Celery task queued on commit, which never runs inside a `TestCase`. That's fine: rows for a dataset without its own partition go to the DEFAULT partitions. Test partition creation itself through `datasets.partitions`.
- **Throttles.** DRF caches throttle rates on the class. Patch `THROTTLE_RATES` on the throttle class (`mock.patch.object`) rather than overriding settings, or the rate leaks between tests.
- **Query behaviour.** Some tests read the planner's own answer (`analytics/tests/test_extract_plans.py`) to pin partition pruning. Add one when you write a query against a partitioned table ([Database §1](database.md#1-partitioned-tables-every-query-must-name-dataset_id)).

## Frontend

```bash
docker compose exec frontend bun test        # unit tests (*.test.ts)
docker compose exec frontend bun run check   # svelte-check: types and Svelte diagnostics
```

`bun test` runs every `*.test.ts` under `frontend/`, including the MCP map app's (`mcp-map/map.test.ts`). It doesn't resolve the `#lib/…` import alias, so a module you want to unit-test must import its own dependencies by relative path. Tests of modules that use `#lib` fail to load under `bun test` for that reason, not because of your change.

Keep logic you want to test in plain `.ts` modules (stores, `recipe.ts`, `loadRecipe.ts`, `utils/`), and keep components thin.

### Checking pages in a browser

For changes to what a page shows, run the dev server and look. To check against real data without a local database, a headless browser script can serve the local frontend and forward its `GET /api/…` calls to production, stubbing any write (such as creating a share link) so nothing is written there.

## The docs

```bash
uv run --only-group docs zensical build --clean
```

The build lists links to pages that don't exist. Links into `data_documentation/datasets/` and `boundaries/` are expected locally, since those pages are generated; anything else is a real broken link.
