"""Stop resetting existing tasks when a published input is edited in place.

Migration 0031's capture triggers treated an edit to a dataset path, resource
path, processing option definition, category map or geometry as invalidating
every result computed from it. Tasks a completed request links were recomputed
in place under the same id, so a request's values could change with no record.

An input whose results should change is now published as a new dataset,
resource, processing option or collection. An in-place edit is one that leaves
results the same -- files moved to a new directory, a kwarg that only affects
how a computation runs -- so it has nothing to invalidate, reset or recompute.

Deletions, additions, eligibility changes and invalidate_extract_inputs are
unchanged. Replaces only trigger functions, so it takes no table locks and has
no data to migrate; the reverse restores the 0031 behaviour.
"""

import importlib

from django.db import migrations

_FUNCTIONS = """
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
        -- A moved feature fences both owners' work, and its new collection
        -- rewinds to rescan it.
        PERFORM extract_input_mark('collection', array_agg(fc), array_agg(lo),
                                   false, false, false, true)
        FROM (
            SELECT fc, min(lo) AS lo FROM (
                SELECT n.fc_id AS fc, n.id - 1 AS lo
                FROM new_rows n JOIN old_rows o ON o.id = n.id
                WHERE n.fc_id IS DISTINCT FROM o.fc_id
                UNION ALL
                SELECT o.fc_id, NULL::integer
                FROM new_rows n JOIN old_rows o ON o.id = n.id
                WHERE n.fc_id IS DISTINCT FROM o.fc_id
            ) AS owners GROUP BY fc
        ) AS moved;
        -- A feature pointed at another geometry keeps its tasks and results;
        -- the rewind brings the coverage scan back to it.
        PERFORM extract_input_mark('collection', array_agg(fc), array_agg(lo),
                                   false, false, false)
        FROM (
            SELECT n.fc_id AS fc, min(n.id) - 1 AS lo
            FROM new_rows n JOIN old_rows o ON o.id = n.id
            WHERE n.geom_id IS DISTINCT FROM o.geom_id AND n.fc_id = o.fc_id
            GROUP BY n.fc_id
        ) AS repointed;
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
    -- Tasks and results stay. Coverage decides eligibility from the shape, so
    -- rewind each referencing collection to rescan the features using it.
    PERFORM extract_input_mark('collection', array_agg(fc_id), array_agg(lo),
                               false, false, false)
    FROM (
        SELECT fm.fc_id, min(fm.id) - 1 AS lo
        FROM feat_map fm WHERE fm.geom_id = ANY(changed)
        GROUP BY fm.fc_id
    ) AS referencing;
    -- Exactly these geometries' coverage is now wrong, so delete it in the
    -- same transaction; the rewinds above bring the coverage scan back to
    -- every feature using them. After the marks, which wait for any coverage
    -- chunk holding those collections, so this statement's snapshot sees
    -- the rows such a chunk inserted from the old shape.
    DELETE FROM coverage WHERE geom_id = ANY(changed);
    RETURN NULL;
END $$;

-- Category maps only ever fed reset decisions.
DROP TRIGGER IF EXISTS extract_capture_mappings_insert ON mappings;
DROP TRIGGER IF EXISTS extract_capture_mappings_update ON mappings;
DROP TRIGGER IF EXISTS extract_capture_mappings_delete ON mappings;
DROP FUNCTION IF EXISTS extract_capture_mappings();
"""


def _restore_0031():
    original = importlib.import_module("analytics.migrations.0031_pair_cursor_leases")
    mapping_triggers = "\n".join(
        f"CREATE TRIGGER extract_capture_mappings_{op} AFTER {op.upper()} ON mappings "
        f"REFERENCING {transitions} "
        "FOR EACH STATEMENT EXECUTE FUNCTION extract_capture_mappings();"
        for op, transitions in (
            ("insert", "NEW TABLE AS new_rows"),
            ("update", "OLD TABLE AS old_rows NEW TABLE AS new_rows"),
            ("delete", "OLD TABLE AS old_rows"),
        )
    )
    return original._CAPTURE_FUNCTIONS + mapping_triggers


def restore_0031(apps, schema_editor):
    schema_editor.execute(_restore_0031())


class Migration(migrations.Migration):
    dependencies = [("analytics", "0033_contact_upper_indexes")]

    operations = [
        migrations.RunSQL(_FUNCTIONS, reverse_sql=migrations.RunSQL.noop),
        migrations.RunPython(migrations.RunPython.noop, restore_0031),
    ]
