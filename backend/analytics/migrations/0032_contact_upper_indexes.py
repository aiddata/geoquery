"""Replace the LOWER(contact) indexes with UPPER(contact) ones.

Django renders ``__iexact`` as ``UPPER(x) = UPPER(y)`` on PostgreSQL -- it is
hardcoded in the backend's ``lookup_cast``, with no setting to change it. An
expression index is only eligible when its expression matches the predicate's
exactly, so ``btree(lower(contact))`` could never serve a single
``contact__iexact`` lookup. Confirmed by EXPLAIN with ``enable_seqscan=off``:
the UPPER predicate plans a Seq Scan against the lower() index, and an Index
Scan once the index expression matches.

Every ownership read was therefore sequentially scanning: ``requests_for_user``,
``legacy_requests_for_user``, both filters in ``claim_requests_for_email``, the
``backfill_request_claims`` dry-run count, and ``RequestHistoryView``.

This changes no stored data and nothing the API returns. An expression index
keeps ``upper(contact)`` only inside its own B-tree keys; the column is never
rewritten and ``SELECT contact`` still returns the address exactly as the
submitter typed it.

Runs CONCURRENTLY because ``requests`` is populated in production and a plain
CREATE INDEX holds ACCESS EXCLUSIVE for the whole build, blocking reads and
writes. That requires ``atomic = False``, so a failure part-way leaves the
completed operations applied. Re-running is safe, but if it does fail, check
``\\d requests`` and drop any INVALID index CONCURRENTLY before retrying.

The new indexes are added before the old ones are dropped. Neither can serve
the queries while both exist, so the order costs nothing and avoids a window
with no contact index at all.
"""

import django.db.models.functions.text
from django.contrib.postgres.operations import (
    AddIndexConcurrently,
    RemoveIndexConcurrently,
)
from django.db import migrations, models


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
    atomic = False

    dependencies = [
        ("analytics", "0031_legacyrequest"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="request",
            index=models.Index(
                django.db.models.functions.text.Upper("contact"),
                name="requests_contact_upper_idx",
            ),
        ),
        AddIndexConcurrently(
            model_name="legacyrequest",
            index=models.Index(
                django.db.models.functions.text.Upper("contact"),
                name="legacy_contact_upper_idx",
            ),
        ),
        RemoveIndexConcurrently(
            model_name="request",
            name="requests_contact_lower_idx",
        ),
        RemoveIndexConcurrently(
            model_name="legacyrequest",
            name="legacy_contact_lower_idx",
        ),
    ]
