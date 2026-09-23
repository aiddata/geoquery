# Request Lifecycle

A `Request` is one user's extraction job. Its `status` drives the whole
pipeline — which background job looks at it, whether it is visible to the sweep,
and whether anything will ever pick it up again. Most operational questions
reduce to "what status is it in, and what moves it out".

## Statuses

| Status | Meaning | What moves it on |
|---|---|---|
| `4` | Submitted, awaiting materialization | `materialize_request_tasks` → `-1` |
| `3` | Awaiting custom boundary ingestion | `ingest_custom_boundary_task` |
| `-1` | Queued, never yet swept | the sweep claims it → `2` |
| `0` | Queued, previously swept and not ready | the sweep claims it → `2` |
| `2` | A sweep is working on it | that sweep → `1`, or back to `0` |
| `1` | Complete, output downloadable | terminal |
| `-2` | Error | terminal (see [Recovery](#recovery)) |

Two of these are easy to misread:

- **`0` and `-1` are both "queued".** The sweep selects exactly these two. The
  difference is only whether the "request received" email has been sent — which
  is tracked by `prepare_time` being set, not by the status.
- **`2` is a claim, and it is committed.** It is written in its own short
  transaction so other sweeps can *see* it and skip the request. Before that it
  was written inside the long work transaction and was invisible for exactly as
  long as it mattered. See [Database §4](database.md).

## The path through

```
submit  ──► 4 ──► -1 ──► 2 ──► 1
             │      ▲      │
             │      └──────┘   not ready: back to 0, retried next sweep
             └──► -2          nothing resolvable
```

1. **Submit.** `create_request` writes the row at `status=4` and returns
   immediately. Task creation is deferred so the HTTP request does not block.
2. **Materialize.** A `post_save` signal dispatches `materialize_request_tasks`,
   which resolves the plan, creates `ExtractTask` and `RequestMap` rows, and
   moves the request to `-1`. It is **idempotent** — it deletes existing
   `RequestMap` rows before recreating them, so re-triggering a stuck request is
   safe.
3. **Extract tasks run.** A request's tasks are priority-bumped so they are
   claimed ahead of the general backlog. Tasks already computed for a previous
   request are reused rather than recomputed.
4. **Sweep.** `process_user_requests` claims the request (`2`), checks whether
   every task is done, and either builds the output or returns it to `0`.
5. **Build and notify.** Output is written to a temp directory and renamed into
   place, the status goes to `1`, and the completion email is sent.

The sweep runs on a 5-minute beat and is also triggered by a signal when
materialization finishes, so a request does not usually wait a full interval.

## Timings to expect

From a real 2,890-task request, with the fleet processing ~43k tasks/min:

| Stage | Duration |
|---|---|
| Submit → materialized | ~5 s |
| Materialized → first sweep claim | ~45 s |
| Extract tasks (2,890, priority-bumped) | ~3 min |
| Output build | **~2 s** |
| **Total** | **~4 min** |

Build time is dominated by task count only through the merge, which is batched —
a 1,040-task build that once took 3 h 38 m now takes seconds. If a build is
taking minutes, something is wrong; see [Database §7](database.md).

## Recovery

Every state that means "something is working on this" strands the request if the
worker dies, so each has a reaper. All three run hourly inside
`reset_stale_requests`:

| Stuck at | Recovered by | Returns to |
|---|---|---|
| `4` (materialization never ran) | `_redispatch_unmaterialized_requests` | re-dispatches, stays `4` until it works |
| `2` (sweep died mid-build) | `_reset_stale_requests` | `0` — not `-1`, which would re-send the received email |
| `-2` (errored) | `reset_errored_requests`, manually | `0` |

A long-running build is **not** stranded: the sweep heartbeats its claim, so
`process_time` stays fresh and the reaper leaves it alone.

## Checking on a request

```sql
SELECT left(id::text,8) AS id, status,
       submit_time, prepare_time, process_time, complete_time,
       (SELECT count(*) FROM request_map rm WHERE rm.req_id = r.id) AS tasks
FROM requests r ORDER BY submit_time DESC LIMIT 5;
```

Read it as:

- `prepare_time` set → it has been claimed at least once (and the received email
  has gone out)
- `process_time` advancing while `status=2` → a build is running and
  heartbeating, not stuck
- `status=2` with a `process_time` older than `STALE_TASK_MINUTES` → the sweep
  died; the reaper will return it to `0`
- `status=4` with tasks already mapped → materialization ran but the status was
  moved back by hand; nudge it to `-1`

Task progress for one request:

```sql
SELECT et.status, count(*)
FROM request_map rm
JOIN extract_tasks et ON et.dataset_id = rm.dataset_id AND et.id = rm.task_id
WHERE rm.req_id = '<uuid>'
GROUP BY 1 ORDER BY 1;
```

Note the join carries `dataset_id` — without it this scans every partition. That
rule applies everywhere; see [Database §1](database.md).

## Things worth knowing

- **A bulk `UPDATE` does not fire `post_save`.** Setting a status with
  `Request.objects.filter(...).update(status=4)` skips the signal, so nothing
  dispatches materialization. This is how one request sat at `4` for four days.
  Use `.save()` if you want the signal, or re-dispatch the task explicitly.
- **`status=4` looks healthy.** It is a normal transient state, and `-2` is the
  only status monitoring reads as an error, so a stranded request is invisible.
  The fingerprint worth alerting on is *requests at `4` older than an hour*.
- **Output directories starting with `.` are transient.**
  `.{id}.building.{hex}` is an in-progress build (disposable);
  `.{id}.replaced.{hex}` is displaced output and may be the **only** copy of a
  completed request's results — never delete it blindly.
