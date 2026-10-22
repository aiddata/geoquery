"""Pair cursor leases: schema, change capture and the demand function.

What this migration does, in order:

1. Task ids become bigint (adapted from PR #54). Above IN_PLACE_LIMIT_BYTES it
   refuses rather than rewriting a large table inside a deploy.
2. The NULL-kwargs unique index is reordered to (dataset_id, po_id,
   resource_ids_hash, fm_id), the order lease completions insert in, and the
   po_id index and foreign key go.
3. extract_task_build_progress becomes the pair table: dataset_id, bucket,
   current, priority, a non-null cursor and error/backoff columns. Every
   existing pair is retired with its cursor at 0; sync derives the current
   sets again.
4. extract_tasks.pair_id (provenance, no index, no FK).
5. extract_task_build_run is dropped with the builder.
6. New tables: extract_task_leases, extract_coverage_progress,
   extract_input_state.
7. Change capture: triggers on every input table record changes in
   extract_input_state in the same transaction as the change.
8. The extract_valid_tasks and extract_runnable_tasks views,
   extract_eligible_max_fm_id(), and extract_work_demand(), the
   autoscaler's query, built on them.
9. Seeds an input state for every existing dataset and collection, dirty.
   Dataset states start bootstrap_pending; initialize_extract_work clears
   them one dataset at a time. Long data backfills belong to that command, not
   to this DDL transaction.

See docs/get-involved/contributing/dev/database.md for the contracts.
"""

import django.contrib.postgres.fields
import django.db.models.deletion
from django.db import migrations, models
import django.db.models.functions.datetime
from django.db.models import JSONField, Value


# Above this, rewriting extract_tasks/extract_data is a maintenance-window
# operation, not something a deploy should start on its own: an in-place
# ALTER rewrites every partition in one transaction under ACCESS EXCLUSIVE.
# Size, not reltuples, because reltuples is -1 on never-analyzed partitions.
IN_PLACE_LIMIT_BYTES = 1 * 2**30

# Waiting indefinitely behind a long read would queue every claim and result
# write behind the migration. Failing the deploy is safe: the transaction
# rolls back and a redeploy retries.
LOCK_TIMEOUT = "30s"

TASK_ID_COLUMNS = (
    ("extract_tasks", "id"),
    ("extract_data", "extract_task_id"),
    ("request_map", "task_id"),
)


def _coltype(cursor, table, column):
    cursor.execute(
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
        "WHERE attrelid = %s::regclass AND attname = %s",
        [table, column],
    )
    return cursor.fetchone()[0]


def _task_tables_bytes(cursor):
    cursor.execute(
        "SELECT coalesce(sum(pg_total_relation_size(inhrelid)), 0) FROM pg_inherits "
        "WHERE inhparent IN ('extract_tasks'::regclass, 'extract_data'::regclass)"
    )
    return cursor.fetchone()[0]


def widen_task_ids(apps, schema_editor):
    """Make the three task-id columns bigint, or refuse if that needs a window.

    Already-bigint columns are left alone, so a re-run is a no-op. The
    identity's MAXVALUE is raised either way: widening a column does not
    raise its sequence, and a column converted by hand in a maintenance
    window may still carry int4's limit.
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
        pending = [(t, c) for t, c in TASK_ID_COLUMNS if _coltype(cursor, t, c) != "bigint"]
        if pending:
            size = _task_tables_bytes(cursor)
            if size > IN_PLACE_LIMIT_BYTES:
                raise RuntimeError(
                    f"Task-id columns still integer: {', '.join(f'{t}.{c}' for t, c in pending)}. "
                    f"extract_tasks + extract_data are {size / 2**30:,.0f} GB, too large to convert "
                    "inside a migration. Convert them in a maintenance window first "
                    "(database.md section 11), then deploy again."
                )
            for table, column in pending:
                cursor.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE bigint')
        cursor.execute(
            "ALTER TABLE extract_tasks ALTER COLUMN id SET MAXVALUE 9223372036854775807"
        )


def reorder_unique_index(apps, schema_editor):
    """Rebuild the NULL-kwargs unique index with fm_id last.

    Lease completion inserts one pair's features at a time, so leading with
    (dataset_id, po_id, resource_ids_hash) keeps a page's index insertions on
    neighbouring leaf pages instead of one per feature across the whole index.
    The anti-join probes still supply every column. A plain build on the
    partitioned parent locks the table, so it refuses on a large one; build
    it per partition CONCURRENTLY in a window first, then deploy. Either way
    the old index and the po_id index are dropped here.

    The po_id foreign key goes too. Without the index, its check on every
    processing option delete would scan every partition; deleting an option
    deletes its tasks partition by partition instead
    (analytics.models.delete_option_tasks).
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
        cursor.execute(
            "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname = 'extract_tasks_pair_null_kwargs_idx'"
        )
        row = cursor.fetchone()
        if row is None:
            size = _task_tables_bytes(cursor)
            if size > IN_PLACE_LIMIT_BYTES:
                raise RuntimeError(
                    f"extract_tasks + extract_data are {size / 2**30:,.0f} GB; build "
                    "extract_tasks_pair_null_kwargs_idx per partition CONCURRENTLY in a "
                    "maintenance window first (see migration 0029 for the pattern)."
                )
            cursor.execute(
                """
                CREATE UNIQUE INDEX extract_tasks_pair_null_kwargs_idx
                    ON extract_tasks (dataset_id, po_id, resource_ids_hash, fm_id)
                    WHERE kwargs IS NULL
                """
            )
        elif not row[0]:
            # A partitioned index is invalid until every partition's index is
            # attached; dropping the old one now would leave no uniqueness.
            raise RuntimeError(
                "extract_tasks_pair_null_kwargs_idx exists but is invalid: attach "
                "every partition's index (or drop it and rebuild) before migrating."
            )
        cursor.execute(
            """
            DROP INDEX IF EXISTS extract_tasks_fm_po_resources_null_kwargs_idx;
            DROP INDEX IF EXISTS extract_tasks_po_id_idx;
            """
        )
        cursor.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'extract_tasks'::regclass "
            "AND contype = 'f' AND confrelid = 'processing_options'::regclass"
        )
        for (name,) in cursor.fetchall():
            cursor.execute(f"ALTER TABLE extract_tasks DROP CONSTRAINT {schema_editor.quote_name(name)}")


# One upsert per affected scope. Called only from the capture triggers below
# and from analytics.changes, never by hand-written SQL elsewhere, so that the
# flag and rewind rules live in one place:
#   - generation increments; dirty means generation <> applied_generation;
#   - epoch increments only for an invalidation (p_invalidate or a reset
#     flag): it is what work fences on, so additive changes never discard
#     finished work;
#   - flags are ORed in and stay set until sync publishes the scope;
#   - rewind_from keeps the minimum boundary ever requested (NULL = none);
#   - the checkpoint is invalidated, so a sync in progress restarts its phases;
#   - error and backoff are cleared, so a repaired input is retried promptly.
# A missing row is created dirty. Rows are upserted in object_id order so two
# statements marking the same scopes take their row locks in the same order.
_MARK_FUNCTION = """
CREATE OR REPLACE FUNCTION extract_input_mark(
    p_kind text, p_ids integer[], p_rewinds integer[],
    p_sync_pairs boolean, p_reset_tasks boolean, p_reset_coverage boolean,
    p_invalidate boolean DEFAULT false
) RETURNS void LANGUAGE sql VOLATILE AS $$
    INSERT INTO extract_input_state AS s
        (kind, object_id, generation, applied_generation, epoch, rewind_from,
         sync_pairs, reset_tasks, reset_coverage, bootstrap_pending,
         checkpoint, updated_at, retry_after, last_error)
    SELECT p_kind, v.id, 1, 0,
           (p_invalidate OR p_reset_tasks OR p_reset_coverage)::int, v.rewind,
           p_sync_pairs, p_reset_tasks, p_reset_coverage, false, '{}'::jsonb,
           clock_timestamp(), now(), NULL
    FROM (
        SELECT u.id, min(u.rewind) AS rewind
        FROM unnest(p_ids, p_rewinds) AS u(id, rewind)
        WHERE u.id IS NOT NULL
        GROUP BY u.id
    ) AS v
    ORDER BY v.id
    ON CONFLICT (kind, object_id) DO UPDATE SET
        generation = s.generation + 1,
        epoch = s.epoch + EXCLUDED.epoch,
        rewind_from = CASE
            WHEN EXCLUDED.rewind_from IS NULL THEN s.rewind_from
            WHEN s.rewind_from IS NULL THEN EXCLUDED.rewind_from
            ELSE LEAST(s.rewind_from, EXCLUDED.rewind_from)
        END,
        sync_pairs = s.sync_pairs OR EXCLUDED.sync_pairs,
        reset_tasks = s.reset_tasks OR EXCLUDED.reset_tasks,
        reset_coverage = s.reset_coverage OR EXCLUDED.reset_coverage,
        checkpoint = '{}'::jsonb,
        updated_at = clock_timestamp(),
        -- now(), not clock_timestamp(): due checks compare against now(), and
        -- the scope must be due to any later transaction (and to the rest of
        -- this one).
        retry_after = now(),
        last_error = NULL
$$;

-- The inputs a targeted reset covers (extract_invalid_items). Called after
-- the scope's mark, so it waits behind a publish holding that state, and the
-- items commit with the mark.
CREATE OR REPLACE FUNCTION extract_input_items(
    p_scope_kind text, p_scopes integer[], p_item_kind text, p_items integer[]
) RETURNS void LANGUAGE sql VOLATILE AS $$
    INSERT INTO extract_invalid_items (scope_kind, scope_id, item_kind, item_id)
    SELECT DISTINCT p_scope_kind, u.scope, p_item_kind, u.item
    FROM unnest(p_scopes, p_items) AS u(scope, item)
    WHERE u.scope IS NOT NULL
    ORDER BY 2, 4
    ON CONFLICT DO NOTHING
$$;
"""

# Statement-level triggers with transition tables, so a bulk write marks each
# affected scope once rather than once per row. Writes that change nothing an
# extraction reads (titles, citations, names, attributes) mark nothing.
_CAPTURE_FUNCTIONS = """
CREATE OR REPLACE FUNCTION extract_capture_datasets() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM extract_input_mark('dataset', array_agg(id), array_agg(0),
                                   true, false, false)
        FROM new_rows;
    ELSIF TG_OP = 'DELETE' THEN
        -- A tombstone: the state outlives the row until sync has retired the
        -- dataset's pairs and coverage progress.
        PERFORM extract_input_mark('dataset', array_agg(id), array_agg(0),
                                   true, true, true)
        FROM old_rows;
    ELSE
        -- Inputs every stored result was computed from.
        PERFORM extract_input_mark('dataset', array_agg(n.id), array_agg(0),
                                   true, true, false)
        FROM new_rows n JOIN old_rows o ON o.id = n.id
        WHERE (n.path, n.type, n.mapped) IS DISTINCT FROM (o.path, o.type, o.mapped);
        -- Inputs coverage was computed from. Results stay valid: coverage
        -- decides eligibility, not values.
        PERFORM extract_input_mark('dataset', array_agg(n.id), array_agg(0),
                                   true, false, true)
        FROM new_rows n JOIN old_rows o ON o.id = n.id
        WHERE n.is_global IS DISTINCT FROM o.is_global
           OR n.spatial_extent IS DISTINCT FROM o.spatial_extent;
        -- Pair membership and parking. Inactivity parks pairs and leases;
        -- completions check activity themselves, so nothing is invalidated.
        PERFORM extract_input_mark('dataset', array_agg(n.id),
                                   array_agg(NULL::integer), true, false, false)
        FROM new_rows n JOIN old_rows o ON o.id = n.id
        WHERE n.active IS DISTINCT FROM o.active
           OR n.task_group_period IS DISTINCT FROM o.task_group_period;
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION extract_capture_dataset_resources() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- New resources select new pairs; nothing existing is invalidated.
        PERFORM extract_input_mark('dataset', array_agg(dataset_id),
                                   array_agg(NULL::integer), true, false, false)
        FROM new_rows;
    ELSIF TG_OP = 'DELETE' THEN
        -- A targeted reset of the resource's tasks: request tasks naming it
        -- become terminal errors, background ones go with their pairs.
        PERFORM extract_input_mark('dataset', array_agg(dataset_id),
                                   array_agg(NULL::integer), true, false, false, true)
        FROM old_rows;
        PERFORM extract_input_items('dataset', array_agg(dataset_id), 'resource', array_agg(id))
        FROM old_rows;
    ELSE
        -- A new path invalidates only the tasks that read this resource.
        PERFORM extract_input_mark('dataset', array_agg(n.dataset_id),
                                   array_agg(NULL::integer), false, false, false, true)
        FROM new_rows n JOIN old_rows o ON o.id = n.id
        WHERE n.path IS DISTINCT FROM o.path AND n.dataset_id = o.dataset_id;
        PERFORM extract_input_items('dataset', array_agg(n.dataset_id), 'resource', array_agg(n.id))
        FROM new_rows n JOIN old_rows o ON o.id = n.id
        WHERE n.path IS DISTINCT FROM o.path AND n.dataset_id = o.dataset_id;
        -- A moved resource resets both owners entirely; prefer a new one.
        PERFORM extract_input_mark('dataset', array_agg(ds), array_agg(0),
                                   true, true, false)
        FROM (
            SELECT n.dataset_id AS ds FROM new_rows n JOIN old_rows o ON o.id = n.id
            WHERE n.dataset_id IS DISTINCT FROM o.dataset_id
            UNION
            SELECT o.dataset_id FROM new_rows n JOIN old_rows o ON o.id = n.id
            WHERE n.dataset_id IS DISTINCT FROM o.dataset_id
        ) AS moved;
        -- Temporal values decide grouped bucket membership.
        PERFORM extract_input_mark('dataset', array_agg(n.dataset_id),
                                   array_agg(NULL::integer), true, false, false)
        FROM new_rows n JOIN old_rows o ON o.id = n.id
        WHERE n.temporal IS DISTINCT FROM o.temporal;
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION extract_capture_processing_options() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM extract_input_mark('dataset', array_agg(dataset_id),
                                   array_agg(NULL::integer), true, false, false)
        FROM new_rows;
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM extract_input_mark('dataset', array_agg(dataset_id),
                                   array_agg(NULL::integer), true, false, false)
        FROM old_rows;
    ELSE
        -- A changed definition invalidates only this option's tasks.
        PERFORM extract_input_mark('dataset', array_agg(n.dataset_id),
                                   array_agg(NULL::integer), false, false, false, true)
        FROM new_rows n JOIN old_rows o ON o.id = n.id
        WHERE (n.function, n.kwargs, n.short_name) IS DISTINCT FROM (o.function, o.kwargs, o.short_name)
          AND n.dataset_id = o.dataset_id;
        PERFORM extract_input_items('dataset', array_agg(n.dataset_id), 'option', array_agg(n.id))
        FROM new_rows n JOIN old_rows o ON o.id = n.id
        WHERE (n.function, n.kwargs, n.short_name) IS DISTINCT FROM (o.function, o.kwargs, o.short_name)
          AND n.dataset_id = o.dataset_id;
        -- A moved option resets both owners entirely; prefer a new one.
        PERFORM extract_input_mark('dataset', array_agg(ds), array_agg(0),
                                   true, true, false)
        FROM (
            SELECT n.dataset_id AS ds FROM new_rows n JOIN old_rows o ON o.id = n.id
            WHERE n.dataset_id IS DISTINCT FROM o.dataset_id
            UNION
            SELECT o.dataset_id FROM new_rows n JOIN old_rows o ON o.id = n.id
            WHERE n.dataset_id IS DISTINCT FROM o.dataset_id
        ) AS changed;
        PERFORM extract_input_mark('dataset', array_agg(n.dataset_id),
                                   array_agg(NULL::integer), true, false, false)
        FROM new_rows n JOIN old_rows o ON o.id = n.id
        WHERE n.active IS DISTINCT FROM o.active;
    END IF;
    RETURN NULL;
END $$;

-- Category maps only feed mapped datasets' results. A mapped flag flip is
-- captured on datasets itself.
CREATE OR REPLACE FUNCTION extract_capture_mappings() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM extract_input_mark('dataset', array_agg(m.dataset_id), array_agg(0),
                                   true, true, false)
        FROM new_rows m JOIN datasets d ON d.id = m.dataset_id AND d.mapped;
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM extract_input_mark('dataset', array_agg(m.dataset_id), array_agg(0),
                                   true, true, false)
        FROM old_rows m JOIN datasets d ON d.id = m.dataset_id AND d.mapped;
    ELSE
        PERFORM extract_input_mark('dataset', array_agg(ds), array_agg(0),
                                   true, true, false)
        FROM (
            SELECT n.dataset_id AS ds FROM new_rows n JOIN old_rows o ON o.id = n.id
            WHERE (n.map_val, n.map_name, n.dataset_id)
                  IS DISTINCT FROM (o.map_val, o.map_name, o.dataset_id)
            UNION
            SELECT o.dataset_id FROM new_rows n JOIN old_rows o ON o.id = n.id
            WHERE n.dataset_id IS DISTINCT FROM o.dataset_id
        ) AS changed
        JOIN datasets d ON d.id = changed.ds AND d.mapped;
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION extract_capture_feature_collections() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- Every collection gets a permanent state, clean: it has no features
        -- yet, and each feat_map insert marks its own rewind.
        INSERT INTO extract_input_state (kind, object_id)
        SELECT 'collection', id FROM new_rows ORDER BY id
        ON CONFLICT (kind, object_id) DO NOTHING;
    ELSIF TG_OP = 'DELETE' THEN
        -- feat_map rows are deleted first (each marks its own rewind); this
        -- leaves a tombstone for sync to retire.
        PERFORM extract_input_mark('collection', array_agg(id),
                                   array_agg(NULL::integer), false, false, false)
        FROM old_rows;
    ELSE
        -- Eligibility for leases and coverage. Rewinding from the
        -- collection's lowest feature covers transitions that are reversed
        -- again before sync runs.
        PERFORM extract_input_mark('collection', array_agg(changed.id),
                                   array_agg(changed.lo), false, false, false)
        FROM (
            SELECT n.id, (SELECT min(fm.id) - 1 FROM feat_map fm WHERE fm.fc_id = n.id) AS lo
            FROM new_rows n JOIN old_rows o ON o.id = n.id
            WHERE (n.active, n.is_user_upload) IS DISTINCT FROM (o.active, o.is_user_upload)
        ) AS changed;
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION extract_capture_feat_map() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- Attaching a geometry takes FOR SHARE on it, which conflicts with the
        -- exclusive lock a shape edit holds while it discovers referencing
        -- collections. The FK's own KEY SHARE is not enough: it does not
        -- conflict with a non-key UPDATE, and it is deferred to commit.
        PERFORM 1 FROM features f
        WHERE f.id IN (SELECT geom_id FROM new_rows)
        ORDER BY f.id FOR SHARE;
        -- Uploads are never leased or covered (and flipping the flag rewinds
        -- the collection), so their features need no rewind and their
        -- request tasks never wait for a publish.
        PERFORM extract_input_mark('collection', array_agg(fc_id), array_agg(lo),
                                   false, false, false)
        FROM (
            SELECT n.fc_id, min(n.id) - 1 AS lo
            FROM new_rows n JOIN feature_collections fc ON fc.id = n.fc_id AND NOT fc.is_user_upload
            GROUP BY n.fc_id
        ) AS added;
    ELSIF TG_OP = 'DELETE' THEN
        -- Leases may still name these features: the epoch fences their
        -- completion, and sync drops missing members when it publishes.
        PERFORM extract_input_mark('collection', array_agg(fc_id), array_agg(lo),
                                   false, false, false, true)
        FROM (
            SELECT o.fc_id, min(o.id) - 1 AS lo
            FROM old_rows o JOIN feature_collections fc ON fc.id = o.fc_id AND NOT fc.is_user_upload
            GROUP BY o.fc_id
        ) AS removed;
    ELSE
        PERFORM 1 FROM features f
        WHERE f.id IN (
            SELECT n.geom_id FROM new_rows n JOIN old_rows o ON o.id = n.id
            WHERE (n.geom_id, n.fc_id) IS DISTINCT FROM (o.geom_id, o.fc_id)
        )
        ORDER BY f.id FOR SHARE;
        -- A moved or repointed feature fences both owners' work, and its
        -- (new) collection rewinds to rescan it. Only a new geometry
        -- invalidates its results, so only that logs the feature for a
        -- targeted reset. Coverage belongs to the geometry, not the feature,
        -- so it stays valid.
        PERFORM extract_input_mark('collection', array_agg(fc), array_agg(lo),
                                   false, false, false, true)
        FROM (
            SELECT fc, min(lo) AS lo FROM (
                SELECT n.fc_id AS fc, n.id - 1 AS lo
                FROM new_rows n JOIN old_rows o ON o.id = n.id
                WHERE (n.geom_id, n.fc_id) IS DISTINCT FROM (o.geom_id, o.fc_id)
                UNION ALL
                SELECT o.fc_id, NULL::integer
                FROM new_rows n JOIN old_rows o ON o.id = n.id
                WHERE n.fc_id IS DISTINCT FROM o.fc_id
            ) AS owners GROUP BY fc
        ) AS moved;
        PERFORM extract_input_items('collection', array_agg(n.fc_id), 'feature', array_agg(n.id))
        FROM new_rows n JOIN old_rows o ON o.id = n.id
        WHERE n.geom_id IS DISTINCT FROM o.geom_id;
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION extract_capture_features() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    changed integer[];
BEGIN
    SELECT array_agg(n.id ORDER BY n.id) INTO changed
    FROM new_rows n JOIN old_rows o ON o.id = n.id
    WHERE n.shape IS DISTINCT FROM o.shape;
    IF changed IS NULL THEN
        RETURN NULL;
    END IF;
    -- Lock the reshaped features exclusively before discovering which
    -- collections reference them, so a concurrent attachment either commits
    -- first (and is found here, by this statement's fresh snapshot) or waits
    -- for this transaction and then sees the new shape.
    PERFORM 1 FROM features f WHERE f.id = ANY(changed) ORDER BY f.id FOR UPDATE;
    -- Shared geometries mark each referencing collection once, and log
    -- every feature using them for a targeted reset.
    PERFORM extract_input_mark('collection', array_agg(fc_id), array_agg(lo),
                               false, false, false, true)
    FROM (
        SELECT fm.fc_id, min(fm.id) - 1 AS lo
        FROM feat_map fm WHERE fm.geom_id = ANY(changed)
        GROUP BY fm.fc_id
    ) AS referencing;
    PERFORM extract_input_items('collection', array_agg(fm.fc_id), 'feature', array_agg(fm.id))
    FROM feat_map fm WHERE fm.geom_id = ANY(changed);
    -- Exactly these geometries' coverage is now wrong, so delete it in the
    -- same transaction; the rewinds above bring the coverage scan back to
    -- every feature using them. After the marks, which wait for any coverage
    -- chunk holding those collections, so this statement's snapshot sees
    -- the rows such a chunk inserted from the old shape.
    DELETE FROM coverage WHERE geom_id = ANY(changed);
    RETURN NULL;
END $$;
"""

# (table, function, operations). Every trigger is AFTER ... FOR EACH STATEMENT
# with transition tables; PostgreSQL requires one trigger per operation when
# transition tables are used.
_TRIGGERS = (
    ("datasets", "extract_capture_datasets"),
    ("dataset_resources", "extract_capture_dataset_resources"),
    ("processing_options", "extract_capture_processing_options"),
    ("mappings", "extract_capture_mappings"),
    ("feature_collections", "extract_capture_feature_collections"),
    ("feat_map", "extract_capture_feat_map"),
    ("features", None),
)


def _trigger_sql():
    statements = []
    for table, function in _TRIGGERS:
        if function is None:
            # Features only matter when their shape changes. An inserted
            # feature has no feat_map yet; a deleted one takes its feat_map
            # rows (and their triggers) with it.
            statements.append(
                f"CREATE TRIGGER extract_capture_{table}_update AFTER UPDATE ON {table} "
                "REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows "
                "FOR EACH STATEMENT EXECUTE FUNCTION extract_capture_features();"
            )
            continue
        statements.extend(
            [
                f"CREATE TRIGGER extract_capture_{table}_insert AFTER INSERT ON {table} "
                f"REFERENCING NEW TABLE AS new_rows "
                f"FOR EACH STATEMENT EXECUTE FUNCTION {function}();",
                f"CREATE TRIGGER extract_capture_{table}_update AFTER UPDATE ON {table} "
                f"REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows "
                f"FOR EACH STATEMENT EXECUTE FUNCTION {function}();",
                f"CREATE TRIGGER extract_capture_{table}_delete AFTER DELETE ON {table} "
                f"REFERENCING OLD TABLE AS old_rows "
                f"FOR EACH STATEMENT EXECUTE FUNCTION {function}();",
            ]
        )
    return "\n".join(statements)


def _drop_trigger_sql():
    statements = []
    for table, function in _TRIGGERS:
        for op in ("insert", "update", "delete"):
            statements.append(f"DROP TRIGGER IF EXISTS extract_capture_{table}_{op} ON {table};")
    for function in (
        "extract_capture_datasets", "extract_capture_dataset_resources",
        "extract_capture_processing_options", "extract_capture_mappings",
        "extract_capture_feature_collections", "extract_capture_feat_map",
        "extract_capture_features",
    ):
        statements.append(f"DROP FUNCTION IF EXISTS {function}();")
    statements.append(
        "DROP FUNCTION IF EXISTS extract_input_mark(text, integer[], integer[], boolean, boolean, boolean, boolean);"
    )
    statements.append("DROP FUNCTION IF EXISTS extract_input_items(text, integer[], text, integer[]);")
    return "\n".join(statements)


# The definitions every claim, reader and the autoscaler share, so they
# cannot disagree about what is valid or runnable.
#
# extract_valid_tasks: tasks whose stored state may be trusted. Not in a
# dataset being reset as a whole or still bootstrapping, and not named by a
# pending targeted reset (extract_invalid_items). Readers select results from
# it, in the same statement, so a reset that commits mid-response is either
# seen or not, never half. A plain view: the planner inlines it, so the
# caller's dataset_id filter still prunes partitions.
#
# extract_runnable_tasks: valid pending tasks a worker may claim now. Their
# dataset, option and collection are active; neither scope is unavailable
# (reset as a whole, or bootstrapping); and the task is a request's or a
# current pair's. A retired pair's task with no request waits, not counted.
#
# extract_eligible_max_fm_id(): the highest feature a lease or coverage scan
# can ever use. Uploads are never leased or covered, so they move no cap.
_WORK_DEFINITIONS = """
CREATE OR REPLACE VIEW extract_valid_tasks AS
SELECT t.*
FROM extract_tasks t
WHERE NOT EXISTS (
          SELECT 1 FROM extract_input_state s
          WHERE s.kind = 'dataset' AND s.object_id = t.dataset_id
            AND (s.reset_tasks OR s.bootstrap_pending))
  AND NOT EXISTS (
          SELECT 1 FROM extract_invalid_items i
          WHERE i.item_kind = 'feature' AND i.item_id = t.fm_id)
  AND NOT EXISTS (
          SELECT 1 FROM extract_invalid_items i
          WHERE i.scope_kind = 'dataset' AND i.scope_id = t.dataset_id
            AND ((i.item_kind = 'option' AND i.item_id = t.po_id)
                 OR (i.item_kind = 'resource' AND i.item_id = ANY(t.resource_ids))));

CREATE OR REPLACE VIEW extract_runnable_tasks AS
SELECT t.id, t.dataset_id, fm.fc_id, t.priority, t.submit_time
FROM extract_valid_tasks t
JOIN feat_map fm ON fm.id = t.fm_id
JOIN feature_collections fc ON fc.id = fm.fc_id AND fc.active
JOIN datasets d ON d.id = t.dataset_id AND d.active
JOIN processing_options po ON po.id = t.po_id AND po.active
JOIN extract_input_state sd
  ON sd.kind = 'dataset' AND sd.object_id = t.dataset_id
 AND NOT (sd.reset_tasks OR sd.reset_coverage OR sd.bootstrap_pending)
JOIN extract_input_state sc
  ON sc.kind = 'collection' AND sc.object_id = fm.fc_id
 AND NOT (sc.reset_tasks OR sc.reset_coverage OR sc.bootstrap_pending)
WHERE t.status = 0
  AND (t.pair_id IS NULL
       OR EXISTS (SELECT 1 FROM extract_task_build_progress p
                  WHERE p.id = t.pair_id AND p.current)
       OR EXISTS (SELECT 1 FROM request_map rm
                  WHERE rm.dataset_id = t.dataset_id AND rm.task_id = t.id));

-- ORDER BY ... LIMIT 1 rather than max(), so it walks feat_map's primary key
-- backwards and stops at the first non-upload feature.
CREATE OR REPLACE FUNCTION extract_eligible_max_fm_id() RETURNS integer
LANGUAGE sql STABLE AS $$
    SELECT COALESCE((
        SELECT fm.id FROM feat_map fm
        WHERE EXISTS (SELECT 1 FROM feature_collections fc
                      WHERE fc.id = fm.fc_id AND NOT fc.is_user_upload)
        ORDER BY fm.id DESC LIMIT 1), 0)
$$;

-- The autoscaler's demand, in units of feature-pair work items. It
-- overestimates by design: ID ranges include gaps and ineligible features.
-- Pending tasks count exactly what claims would take (extract_runnable_tasks,
-- read through the pending partial index). Leases and unscanned ranges
-- count only for available datasets and current pairs of active options
-- that no pending targeted reset covers. Unavailable scopes recover through
-- beat and the background workers, not the processing fleet.
CREATE OR REPLACE FUNCTION extract_work_demand() RETURNS bigint
LANGUAGE sql STABLE AS $$
    WITH available AS (
        SELECT d.id, d.is_global
        FROM datasets d
        JOIN extract_input_state s ON s.kind = 'dataset' AND s.object_id = d.id
        WHERE d.active AND NOT (s.reset_tasks OR s.reset_coverage OR s.bootstrap_pending)
    ),
    caps AS (
        SELECT a.id AS dataset_id, a.is_global, m.id AS max_fm_id,
               COALESCE(cp.covered_up_to_fm_id, 0) AS covered,
               CASE WHEN a.is_global THEN m.id
                    ELSE LEAST(m.id, COALESCE(cp.covered_up_to_fm_id, 0)) END AS cap
        FROM available a
        CROSS JOIN (SELECT extract_eligible_max_fm_id() AS id) m
        LEFT JOIN extract_coverage_progress cp ON cp.dataset_id = a.id
    ),
    runnable_pairs AS (
        SELECT p.id, p.cursor_fm_id, c.cap
        FROM extract_task_build_progress p
        JOIN caps c ON c.dataset_id = p.dataset_id
        JOIN processing_options po ON po.id = p.po_id AND po.active
        WHERE p.current
          AND NOT EXISTS (
              SELECT 1 FROM extract_invalid_items i
              WHERE i.scope_kind = 'dataset' AND i.scope_id = p.dataset_id
                AND ((i.item_kind = 'option' AND i.item_id = p.po_id)
                     OR (i.item_kind = 'resource' AND i.item_id = ANY(p.resource_ids))))
    )
    SELECT (
        (SELECT count(*) FROM extract_runnable_tasks)
        + (SELECT COALESCE(sum(cardinality(l.fm_ids)), 0)
           FROM extract_task_leases l
           WHERE l.progress_id IN (SELECT id FROM runnable_pairs))
        + (SELECT COALESCE(sum(GREATEST(cap - cursor_fm_id, 0)), 0) FROM runnable_pairs)
        + (SELECT COALESCE(sum(GREATEST(max_fm_id - covered, 0)), 0)
           FROM caps WHERE NOT is_global)
    )::bigint
$$;
"""

_DROP_WORK_DEFINITIONS = """
DROP FUNCTION IF EXISTS extract_work_demand();
DROP FUNCTION IF EXISTS extract_eligible_max_fm_id();
DROP VIEW IF EXISTS extract_runnable_tasks;
DROP VIEW IF EXISTS extract_valid_tasks;
"""


_RETIRE_PAIRS_SQL = """
    UPDATE extract_task_build_progress p
    SET dataset_id = po.dataset_id
    FROM processing_options po
    WHERE po.id = p.po_id;
    UPDATE extract_task_build_progress
    SET cursor_fm_id = 0, current = false;
"""


def seed_input_states(apps, schema_editor):
    """Every existing dataset and collection starts dirty.

    Dataset states are bootstrap_pending: sync may not publish them until
    initialize_extract_work has backfilled that dataset's provenance and
    rebuilt its coverage. Collections rewind from 0, so the first publish
    rewinds nothing that is not already at 0. A fresh database seeds nothing;
    datasets and collections created later get states from the triggers.
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO extract_input_state
                (kind, object_id, generation, applied_generation, rewind_from,
                 sync_pairs, bootstrap_pending)
            SELECT 'dataset', id, 1, 0, 0, true, true FROM datasets ORDER BY id
            ON CONFLICT (kind, object_id) DO NOTHING;
            INSERT INTO extract_input_state
                (kind, object_id, generation, applied_generation, rewind_from)
            SELECT 'collection', id, 1, 0, 0 FROM feature_collections ORDER BY id
            ON CONFLICT (kind, object_id) DO NOTHING;
            """
        )


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0030_extracttaskbuildrun_worker_tracking"),
        ("datasets", "0011_remove_dataset_task_group_period_requires_global"),
        ("features", "0010_feat_map_name_search"),
    ]

    operations = [
        # 1. bigint task ids.
        migrations.SeparateDatabaseAndState(
            database_operations=[
                # Not reversed: a bigint column holds every int4 value, and
                # narrowing it back would fail once any id exceeds int4.
                migrations.RunPython(widen_task_ids, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="extracttask",
                    name="id",
                    field=models.BigAutoField(primary_key=True, serialize=False),
                ),
            ],
        ),
        # 2. Unique index order, and no po_id index or foreign key.
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(reorder_unique_index, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="extracttask",
                    name="po",
                    field=models.ForeignKey(
                        db_column="po_id",
                        db_constraint=False,
                        db_index=False,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to="analytics.processingoption",
                    ),
                ),
            ],
        ),
        # 3. The pair table.
        migrations.AddField(
            model_name="extracttaskbuildprogress",
            name="dataset_id",
            field=models.IntegerField(null=True),
        ),
        migrations.RenameField(
            model_name="extracttaskbuildprogress",
            old_name="completed_up_to_fm_id",
            new_name="cursor_fm_id",
        ),
        migrations.AddField(
            model_name="extracttaskbuildprogress",
            name="bucket",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="extracttaskbuildprogress",
            name="task_group_period",
            field=models.CharField(blank=True, max_length=10, null=True),
        ),
        migrations.AddField(
            model_name="extracttaskbuildprogress",
            name="current",
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.AddField(
            model_name="extracttaskbuildprogress",
            name="priority",
            field=models.IntegerField(db_default=0, default=0),
        ),
        migrations.AddField(
            model_name="extracttaskbuildprogress",
            name="last_error",
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
        migrations.AddField(
            model_name="extracttaskbuildprogress",
            name="retry_after",
            field=models.DateTimeField(db_default=django.db.models.functions.datetime.Now()),
        ),
        migrations.AddField(
            model_name="extracttaskbuildprogress",
            name="seconds_per_feature",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.RemoveField(
            model_name="extracttaskbuildprogress",
            name="claimed_at",
        ),
        migrations.RunSQL(_RETIRE_PAIRS_SQL, migrations.RunSQL.noop),
        migrations.AlterField(
            model_name="extracttaskbuildprogress",
            name="dataset_id",
            field=models.IntegerField(),
        ),
        migrations.AlterField(
            model_name="extracttaskbuildprogress",
            name="cursor_fm_id",
            field=models.IntegerField(db_default=0, default=0),
        ),
        migrations.AddConstraint(
            model_name="extracttaskbuildprogress",
            constraint=models.UniqueConstraint(
                condition=models.Q(("bucket__isnull", False), ("current", True)),
                fields=("dataset_id", "po", "bucket"),
                name="extract_pairs_current_bucket_unique",
            ),
        ),
        # 4. Provenance.
        migrations.AddField(
            model_name="extracttask",
            name="pair_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        # 5. The builder's run guard.
        migrations.DeleteModel(name="ExtractTaskBuildRun"),
        # 6. New tables.
        migrations.CreateModel(
            name="ExtractTaskLease",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("dataset_id", models.IntegerField()),
                (
                    "resource_ids",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.IntegerField(), size=None
                    ),
                ),
                ("po_id", models.IntegerField()),
                ("task_group_period", models.CharField(blank=True, max_length=10, null=True)),
                (
                    "fm_ids",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.IntegerField(), size=None
                    ),
                ),
                (
                    "input_generations",
                    models.JSONField(db_default=Value({}, JSONField()), default=dict),
                ),
                ("token", models.UUIDField()),
                (
                    "leased_at",
                    models.DateTimeField(db_default=django.db.models.functions.datetime.Now()),
                ),
                ("leased_until", models.DateTimeField()),
                (
                    "retry_after",
                    models.DateTimeField(db_default=django.db.models.functions.datetime.Now()),
                ),
                (
                    "created_at",
                    models.DateTimeField(db_default=django.db.models.functions.datetime.Now()),
                ),
                ("attempts", models.IntegerField(db_default=0, default=0)),
                ("last_error", models.CharField(blank=True, max_length=100, null=True)),
                (
                    "progress",
                    models.ForeignKey(
                        db_column="progress_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        to="analytics.extracttaskbuildprogress",
                    ),
                ),
            ],
            options={
                "db_table": "extract_task_leases",
                "indexes": [
                    models.Index(fields=["leased_until"], name="extract_task_leases_due_idx")
                ],
            },
        ),
        migrations.CreateModel(
            name="CoverageProgress",
            fields=[
                (
                    "dataset",
                    models.OneToOneField(
                        db_column="dataset_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        serialize=False,
                        to="datasets.dataset",
                    ),
                ),
                ("covered_up_to_fm_id", models.IntegerField(db_default=0, default=0)),
                ("extent_hash", models.TextField(blank=True, null=True)),
            ],
            options={"db_table": "extract_coverage_progress"},
        ),
        migrations.CreateModel(
            name="ExtractInputState",
            fields=[
                (
                    "pk",
                    models.CompositePrimaryKey(
                        "kind", "object_id", blank=True, editable=False,
                        primary_key=True, serialize=False,
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[("dataset", "Dataset"), ("collection", "Collection")],
                        max_length=10,
                    ),
                ),
                ("object_id", models.IntegerField()),
                ("generation", models.BigIntegerField(db_default=0, default=0)),
                ("applied_generation", models.BigIntegerField(db_default=0, default=0)),
                ("epoch", models.BigIntegerField(db_default=0, default=0)),
                ("rewind_from", models.IntegerField(blank=True, null=True)),
                ("sync_pairs", models.BooleanField(db_default=False, default=False)),
                ("reset_tasks", models.BooleanField(db_default=False, default=False)),
                ("reset_coverage", models.BooleanField(db_default=False, default=False)),
                ("bootstrap_pending", models.BooleanField(db_default=False, default=False)),
                (
                    "checkpoint",
                    models.JSONField(db_default=Value({}, JSONField()), default=dict),
                ),
                (
                    "updated_at",
                    models.DateTimeField(db_default=django.db.models.functions.datetime.Now()),
                ),
                (
                    "retry_after",
                    models.DateTimeField(db_default=django.db.models.functions.datetime.Now()),
                ),
                ("last_error", models.TextField(blank=True, null=True)),
            ],
            options={"db_table": "extract_input_state"},
        ),
        migrations.CreateModel(
            name="ExtractInvalidItem",
            fields=[
                (
                    "pk",
                    models.CompositePrimaryKey(
                        "scope_kind", "scope_id", "item_kind", "item_id", blank=True,
                        editable=False, primary_key=True, serialize=False,
                    ),
                ),
                (
                    "scope_kind",
                    models.CharField(
                        choices=[("dataset", "Dataset"), ("collection", "Collection")],
                        max_length=10,
                    ),
                ),
                ("scope_id", models.IntegerField()),
                ("item_kind", models.CharField(max_length=10)),
                ("item_id", models.IntegerField()),
            ],
            options={
                "db_table": "extract_invalid_items",
                "indexes": [
                    models.Index(fields=["item_kind", "item_id"], name="extract_invalid_items_item_idx")
                ],
            },
        ),
        # 7. Change capture.
        migrations.RunSQL(
            _MARK_FUNCTION + _CAPTURE_FUNCTIONS + _trigger_sql(),
            _drop_trigger_sql(),
        ),
        # 8. Shared definitions of valid and runnable work, and demand.
        migrations.RunSQL(_WORK_DEFINITIONS, _DROP_WORK_DEFINITIONS),
        # 9. Seed.
        migrations.RunPython(seed_input_states, migrations.RunPython.noop),
    ]
