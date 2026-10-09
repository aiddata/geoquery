"""Widen extract task ids from integer to bigint, one partition at a time.

extract_tasks_id_seq ran out at 2,147,483,647 with ~483M tasks still to build,
so extract_tasks.id -- and the two columns that reference it,
extract_data.extract_task_id and request_map.task_id -- must become bigint.

Why not a single ALTER TABLE ... TYPE bigint on each parent: on a partitioned
table that rewrites every partition inside one transaction, and the old files
are only released at commit. Production would need roughly a second copy of
~1 TB on a volume that does not have it, plus WAL for all of it in one go.

What this does instead, per parent table:

  1. Build an empty bigint twin, <table>__i8, cloned from the live parent
     (columns, defaults, identity, NOT NULLs, the generated resource_ids_hash
     column) plus the parent's primary key and indexes under __i8 names.
  2. Move each partition across in its own transaction: DETACH from the old
     parent, widen the column and add a CHECK matching the partition bound in
     the SAME ALTER -- one rewrite, which also validates the CHECK -- then
     ATTACH to the twin. The CHECK lets ATTACH skip its validation scan, and
     the rewritten indexes match the twin's definitions, so they are adopted
     rather than rebuilt. Peak extra space is one partition, released at that
     partition's commit.
  3. When the old parent is empty, drop it and give the twin the original
     table, index, constraint and sequence names.

Each step is a single transaction, so an interruption always leaves every
partition attached to exactly one of the two parents; re-running resumes from
whatever the catalog shows.

Two constraints shape the window (both verified on PostgreSQL 17):

  * DETACH is refused while extract_data and request_map hold foreign keys
    into extract_tasks, so both are dropped first and re-added at the end.
  * PostgreSQL 17 cannot add a NOT VALID foreign key to a partitioned table,
    so re-adding extract_data's means a full validation scan, holding locks
    that block writes to both tables. That is its own phase (--phase fks) so
    it can be scheduled, or skipped.

Between partitions the command waits for every physical replication slot to
catch up, because a slot that falls further behind than
max_slot_wal_keep_size is invalidated and that standby has to be rebuilt.
Within a partition it cannot wait -- one ALTER is one statement -- so the
largest partitions need that limit raised for the window. See database.md
section 11.
"""

import re
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

SUFFIX = "__i8"
BIGINT_MAX = 9223372036854775807

# (parent, column, column is the identity column)
TABLES = (
    ("extract_tasks", "id", True),
    ("extract_data", "extract_task_id", False),
)

# Re-added in --phase fks with exactly these definitions. Checked against the
# live catalog before anything is dropped, so a drifted definition aborts the
# run instead of being silently replaced.
FOREIGN_KEYS = (
    ("extract_data", "extract_data_extract_task_fk",
     "FOREIGN KEY (dataset_id, extract_task_id) REFERENCES extract_tasks(dataset_id, id) "
     "DEFERRABLE INITIALLY DEFERRED"),
    ("request_map", "request_map_extract_task_fk",
     "FOREIGN KEY (dataset_id, task_id) REFERENCES extract_tasks(dataset_id, id) "
     "DEFERRABLE INITIALLY DEFERRED"),
)

PHASES = ("prepare", "extract_tasks", "extract_data", "request_map", "fks")


def _q(cursor, sql, params=None):
    cursor.execute(sql, params or [])
    return cursor.fetchall()


def _exists(cursor, relname):
    return bool(_q(cursor, "SELECT 1 FROM pg_class WHERE relname = %s", [relname]))


def _coltype(cursor, relname, column):
    rows = _q(cursor, """
        SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        WHERE c.relname = %s AND a.attname = %s AND NOT a.attisdropped
    """, [relname, column])
    return rows[0][0] if rows else None


def _partitions(cursor, parent):
    """[(name, bound, total_bytes)] for parent's partitions, DEFAULT last, then smallest first."""
    if not _exists(cursor, parent):
        return []
    return [tuple(r) for r in _q(cursor, """
        SELECT c.relname, pg_get_expr(c.relpartbound, c.oid), pg_total_relation_size(c.oid)
        FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
        WHERE i.inhparent = %s::regclass
        ORDER BY pg_get_expr(c.relpartbound, c.oid) = 'DEFAULT', pg_total_relation_size(c.oid)
    """, [parent])]


def _bound_check(bound):
    """CHECK body implied by a LIST bound, or None for DEFAULT."""
    if bound == "DEFAULT":
        return None
    m = re.fullmatch(r"FOR VALUES IN \((.+)\)", bound)
    if not m:
        raise CommandError(f"unexpected partition bound: {bound!r}")
    return f"dataset_id IS NOT NULL AND dataset_id IN ({m.group(1)})"


def _gb(n):
    n = n or 0
    return f"{n / 2**30:,.1f} GB" if n >= 2**30 else f"{n / 2**20:,.0f} MB"


class Command(BaseCommand):
    help = "Widen extract task ids to bigint one partition at a time (dry run unless --execute)."

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true",
                            help="Make changes. Without it, print the plan and current state only.")
        parser.add_argument("--phase", choices=PHASES + ("all",), default="all",
                            help="Run one phase only. 'all' runs everything except fks.")
        parser.add_argument("--max-partitions", type=int, default=0,
                            help="Stop after converting this many partitions (0 = no limit).")
        parser.add_argument("--max-slot-lag-gb", type=float, default=8.0,
                            help="Before each partition, wait until every replication slot is this close.")
        parser.add_argument("--lag-timeout-minutes", type=int, default=240)
        parser.add_argument("--lock-timeout", default="30s",
                            help="Give up on a partition rather than queue behind live traffic for longer.")
        parser.add_argument("--maintenance-work-mem", default="2GB",
                            help="For the index rebuilds inside each ALTER.")

    # ---- entry ---------------------------------------------------------------

    def handle(self, *args, **opts):
        self.opts = opts
        with connection.cursor() as cursor:
            self._report(cursor)
            if not opts["execute"]:
                self.stdout.write("\nDry run. Re-run with --execute to apply.")
                return
            phase = opts["phase"]
            if phase in ("all", "prepare"):
                self._prepare(cursor)
            self.converted = 0
            for parent, column, identity in TABLES:
                if phase in ("all", parent):
                    if not self._convert_table(cursor, parent, column, identity):
                        return
            if phase in ("all", "request_map"):
                self._request_map(cursor)
            if phase == "fks":
                self._foreign_keys(cursor)
            elif phase == "all":
                self.stdout.write(self.style.WARNING(
                    "\nForeign keys are still dropped. Re-add them with --phase fks "
                    "(full validation scan; blocks writes to extract_tasks and extract_data)."))

    # ---- reporting -----------------------------------------------------------

    def _report(self, cursor):
        self.stdout.write("Column types:")
        for table, column in (("extract_tasks", "id"), ("extract_data", "extract_task_id"),
                              ("request_map", "task_id")):
            twin = table + SUFFIX
            twin_note = f"   twin {twin}: {_coltype(cursor, twin, column)}" if _exists(cursor, twin) else ""
            self.stdout.write(f"  {table}.{column}: {_coltype(cursor, table, column)}{twin_note}")

        self.stdout.write("Foreign keys into extract_tasks:")
        for table, name, _ in FOREIGN_KEYS:
            live = _q(cursor, "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s", [name])
            self.stdout.write(f"  {name}: {'present' if live else 'DROPPED'}")

        for parent, column, _ in TABLES:
            parts = _partitions(cursor, parent)
            done = _partitions(cursor, parent + SUFFIX)
            if not parts and not done:
                continue
            self.stdout.write(
                f"{parent}: {len(parts)} partition(s) still int4 ({_gb(sum(p[2] for p in parts))}), "
                f"{len(done)} moved to {parent}{SUFFIX}")
            if parts:
                biggest = max(parts, key=lambda p: p[2])
                self.stdout.write(f"  largest remaining: {biggest[0]} {_gb(biggest[2])}  "
                                  "<- peak extra space, and roughly the WAL one ALTER emits")

        rows = _q(cursor, "SELECT current_setting('max_slot_wal_keep_size')")
        self.stdout.write(f"max_slot_wal_keep_size: {rows[0][0]}")
        for slot, active, status, behind in self._slots(cursor):
            self.stdout.write(f"  slot {slot}: active={active} wal_status={status} behind={_gb(behind or 0)}")

    def _slots(self, cursor):
        return _q(cursor, """
            SELECT slot_name, active, wal_status, pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)
            FROM pg_replication_slots WHERE slot_type = 'physical' ORDER BY slot_name
        """)

    # ---- phases --------------------------------------------------------------

    def _prepare(self, cursor):
        """Check FK definitions, drop them, and build the bigint twins."""
        for table, name, expected in FOREIGN_KEYS:
            live = _q(cursor, "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s", [name])
            if live and live[0][0] != expected:
                raise CommandError(
                    f"{name} no longer matches the definition this command would restore:\n"
                    f"  live:     {live[0][0]}\n  expected: {expected}\n"
                    "Update FOREIGN_KEYS before running.")
        with transaction.atomic():
            for table, name, _ in FOREIGN_KEYS:
                cursor.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{name}"')
            for parent, column, identity in TABLES:
                self._build_twin(cursor, parent, column, identity)
        self.stdout.write(self.style.SUCCESS("prepare: foreign keys dropped, twins in place"))

    def _build_twin(self, cursor, parent, column, identity):
        twin = parent + SUFFIX
        if _exists(cursor, twin) or _coltype(cursor, parent, column) == "bigint":
            return
        cursor.execute(
            f'CREATE TABLE "{twin}" (LIKE "{parent}" INCLUDING DEFAULTS INCLUDING IDENTITY '
            f'INCLUDING CONSTRAINTS INCLUDING GENERATED) PARTITION BY LIST (dataset_id)')
        cursor.execute(f'ALTER TABLE "{twin}" ALTER COLUMN "{column}" TYPE bigint')
        if identity:
            # LIKE copies the identity sequence's MAXVALUE, and widening the
            # column does not raise it: without this the twin would stop at
            # exactly the same 2,147,483,647.
            last = _q(cursor, "SELECT last_value FROM pg_sequences WHERE sequencename = %s",
                      [f"{parent}_{column}_seq"])
            restart = (last[0][0] if last and last[0][0] else 0) + 1
            cursor.execute(f'ALTER TABLE "{twin}" ALTER COLUMN "{column}" SET MAXVALUE {BIGINT_MAX}')
            cursor.execute(f'ALTER TABLE "{twin}" ALTER COLUMN "{column}" RESTART WITH {restart}')
        for name, definition in _q(cursor, """
            SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
            WHERE conrelid = %s::regclass AND contype IN ('p', 'u')
        """, [parent]):
            cursor.execute(f'ALTER TABLE "{twin}" ADD CONSTRAINT "{name}{SUFFIX}" {definition}')
        for name, definition in _q(cursor, """
            SELECT ic.relname, pg_get_indexdef(x.indexrelid)
            FROM pg_index x JOIN pg_class ic ON ic.oid = x.indexrelid
            WHERE x.indrelid = %s::regclass
              AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = x.indexrelid)
        """, [parent]):
            new = definition.replace(f"INDEX {name} ON ONLY public.{parent} ",
                                     f"INDEX {name}{SUFFIX} ON public.{twin} ", 1)
            if new == definition:
                raise CommandError(f"could not retarget index definition: {definition}")
            cursor.execute(new)

    def _convert_table(self, cursor, parent, column, identity):
        twin = parent + SUFFIX
        if _coltype(cursor, parent, column) == "bigint" and not _exists(cursor, twin):
            self.stdout.write(f"{parent}: already bigint")
            return True
        if not _exists(cursor, twin):
            raise CommandError(f"{twin} is missing; run --phase prepare first")
        for name, bound, size in _partitions(cursor, parent):
            limit = self.opts["max_partitions"]
            if limit and self.converted >= limit:
                self.stdout.write(f"stopping after {limit} partition(s) (--max-partitions)")
                return False
            self._wait_for_replicas(cursor)
            started = time.monotonic()
            self._move_partition(cursor, parent, twin, column, name, bound)
            cursor.execute(f'ANALYZE "{name}" ("{column}")')
            self.converted += 1
            secs = time.monotonic() - started
            self.stdout.write(f"  {name}: {_gb(size)} in {secs:,.0f}s ({size / 2**20 / max(secs, 1):,.0f} MB/s)")
        self._swap(cursor, parent, twin, column, identity)
        return True

    def _move_partition(self, cursor, parent, twin, column, name, bound):
        check = _bound_check(bound)
        with transaction.atomic():
            cursor.execute("SET LOCAL statement_timeout = 0")
            cursor.execute("SET LOCAL lock_timeout = %s", [self.opts["lock_timeout"]])
            cursor.execute("SET LOCAL maintenance_work_mem = %s", [self.opts["maintenance_work_mem"]])
            cursor.execute(f'ALTER TABLE "{parent}" DETACH PARTITION "{name}"')
            # One ALTER, one rewrite: the CHECK is validated while the table is
            # rewritten, and is what lets ATTACH skip its own scan.
            alter = f'ALTER TABLE "{name}" ALTER COLUMN "{column}" TYPE bigint'
            if check:
                alter += f', ADD CONSTRAINT "{name}{SUFFIX}_bound" CHECK ({check})'
            cursor.execute(alter)
            cursor.execute(f'ALTER TABLE "{twin}" ATTACH PARTITION "{name}" {bound}')
            if check:
                cursor.execute(f'ALTER TABLE "{name}" DROP CONSTRAINT "{name}{SUFFIX}_bound"')

    def _swap(self, cursor, parent, twin, column, identity):
        if _partitions(cursor, parent):
            raise CommandError(f"{parent} still has partitions; not swapping")
        with transaction.atomic():
            cursor.execute(f'DROP TABLE "{parent}"')
            cursor.execute(f'ALTER TABLE "{twin}" RENAME TO "{parent}"')
            for (name,) in _q(cursor, """
                SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass AND conname LIKE %s
            """, [parent, f"%{SUFFIX}"]):
                cursor.execute(f'ALTER TABLE "{parent}" RENAME CONSTRAINT "{name}" TO "{name[:-len(SUFFIX)]}"')
            for (name,) in _q(cursor, """
                SELECT ic.relname FROM pg_index x JOIN pg_class ic ON ic.oid = x.indexrelid
                WHERE x.indrelid = %s::regclass AND ic.relname LIKE %s
            """, [parent, f"%{SUFFIX}"]):
                cursor.execute(f'ALTER INDEX "{name}" RENAME TO "{name[:-len(SUFFIX)]}"')
            if identity:
                seq = _q(cursor, "SELECT pg_get_serial_sequence(%s, %s)", [parent, column])[0][0]
                cursor.execute(f'ALTER SEQUENCE {seq} RENAME TO "{parent}_{column}_seq"')
        self.stdout.write(self.style.SUCCESS(f"{parent}: swapped; {column} is bigint"))

    def _request_map(self, cursor):
        if _coltype(cursor, "request_map", "task_id") == "bigint":
            self.stdout.write("request_map: already bigint")
            return
        with transaction.atomic():
            cursor.execute("SET LOCAL statement_timeout = 0")
            cursor.execute('ALTER TABLE "request_map" ALTER COLUMN "task_id" TYPE bigint')
        self.stdout.write(self.style.SUCCESS("request_map: task_id is bigint"))

    def _foreign_keys(self, cursor):
        if _exists(cursor, "extract_tasks" + SUFFIX) or _exists(cursor, "extract_data" + SUFFIX):
            raise CommandError("conversion is not finished; re-add foreign keys afterwards")
        for table, name, definition in FOREIGN_KEYS:
            if _q(cursor, "SELECT 1 FROM pg_constraint WHERE conname = %s", [name]):
                continue
            started = time.monotonic()
            with transaction.atomic():
                cursor.execute("SET LOCAL statement_timeout = 0")
                cursor.execute(f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" {definition}')
            self.stdout.write(f"  {name}: validated in {time.monotonic() - started:,.0f}s")
        self.stdout.write(self.style.SUCCESS("foreign keys restored"))

    # ---- replication ---------------------------------------------------------

    def _wait_for_replicas(self, cursor):
        """Block until every recoverable physical slot is within --max-slot-lag-gb.

        Reads pg_replication_slots rather than pg_stat_replication: the app
        role can see a slot's restart_lsn and wal_status, but not a
        walsender's replay_lsn.

        A 'lost' slot is past saving -- its standby needs rebuilding whatever
        happens next -- so it is reported and then left out, and the wait
        keeps protecting the standbys that are still recoverable rather than
        refusing to finish. An 'unreserved' slot is still recoverable: nothing
        is written between partitions, so its standby can catch up, and that is
        exactly what waiting is for. Inactive slots count too -- a standby that
        is restarting still needs the WAL it has not replayed.
        """
        limit = self.opts["max_slot_lag_gb"] * 2**30
        deadline = time.monotonic() + self.opts["lag_timeout_minutes"] * 60
        while True:
            slots = self._slots(cursor)
            lost = sorted(s[0] for s in slots if s[2] == "lost")
            if lost and lost != getattr(self, "_reported_lost", None):
                self._reported_lost = lost
                self.stdout.write(self.style.ERROR(
                    f"  replication slot(s) lost: {lost}. Those standbys must be rebuilt once the "
                    "conversion finishes; continuing to protect the rest."))
            behind = max((s[3] or 0 for s in slots if s[2] != "lost"), default=0)
            if behind <= limit:
                return
            if time.monotonic() > deadline:
                raise CommandError(f"replicas still {_gb(behind)} behind after the lag timeout")
            self.stdout.write(f"  waiting for replicas: {_gb(behind)} behind")
            time.sleep(30)
