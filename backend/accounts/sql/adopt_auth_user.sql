-- Adopt the legacy django.contrib.auth user table as accounts.User.
--
-- Context
-- -------
-- Databases created before the accounts app existed were migrated under the
-- default AUTH_USER_MODEL ("auth.User"). admin.0001_initial declares a
-- *swappable* dependency, so once AUTH_USER_MODEL becomes "accounts.User" that
-- long-applied migration retroactively claims a dependency on
-- accounts.0001_initial and `migrate` aborts before doing any work:
--
--   InconsistentMigrationHistory: Migration admin.0001_initial is applied
--   before its dependency accounts.0001_initial
--
-- The check runs in MigrationLoader.check_consistent_history(), ahead of every
-- migration, so this cannot be repaired by a migration. It has to be done out
-- of band -- which is what this script is for.
--
-- It renames auth_user and its two m2m tables to the names
-- accounts.0001_initial would have created, widens the integer primary key to
-- bigint to match BigAutoField, adds the unique email constraint that
-- accounts.User declares, repoints the auth|user content type at the accounts
-- app so existing permissions and admin-log rows keep resolving, and records
-- accounts.0001_initial as applied.
--
-- Rows are preserved throughout: user ids, password hashes, group memberships,
-- per-user permissions and admin history all survive, so existing logins and
-- any FK pointing at a user id remain valid.
--
-- Usage
-- -----
-- Normally you do not run this by hand: `manage.py adopt_auth_user` executes it
-- (and `manage.py migrate` calls that first -- see accounts/management/commands/).
-- The command decides *whether* it needs to run; the preconditions below are an
-- independent safety net that refuses if it were ever invoked wrongly.
--
-- To run it directly instead:
--
--   psql "$DSN" -v ON_ERROR_STOP=1 --single-transaction -f adopt_auth_user.sql
--
-- --single-transaction matters: any failed precondition must roll the whole
-- thing back rather than leave the tables half-renamed. This file deliberately
-- contains no BEGIN/COMMIT and no psql meta-commands, so that the identical
-- text can be executed through a Django cursor inside transaction.atomic().
--
-- Afterwards `manage.py migrate` runs the real migrations, and
-- `manage.py adopt_legacy_users` gives the adopted accounts their allauth
-- EmailAddress rows -- without which they cannot log in at all.

-- ---------------------------------------------------------------------------
-- Preconditions. Each one aborts the transaction rather than half-converting.
-- These run before the table lock so that an already-converted database gets
-- the explanation below rather than a bare "relation auth_user does not exist".
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF to_regclass('public.accounts_user') IS NOT NULL THEN
        RAISE EXCEPTION 'accounts_user already exists -- this database has already been converted (or was created with the accounts app present); nothing to do.';
    END IF;

    IF EXISTS (SELECT 1 FROM django_migrations WHERE app = 'accounts' AND name = '0001_initial') THEN
        RAISE EXCEPTION 'accounts.0001_initial is already recorded as applied; nothing to do.';
    END IF;

    IF to_regclass('public.auth_user') IS NULL THEN
        RAISE EXCEPTION 'No auth_user table to adopt. This database was not created under the default AUTH_USER_MODEL, so there is nothing for this script to convert.';
    END IF;

    -- accounts.0001_initial depends on auth.0012. Recording the former as
    -- applied while the latter is not would swap this script's error for an
    -- identical InconsistentMigrationHistory one migration further along.
    IF NOT EXISTS (
        SELECT 1 FROM django_migrations
        WHERE app = 'auth' AND name = '0012_alter_user_first_name_max_length'
    ) THEN
        RAISE EXCEPTION 'auth.0012_alter_user_first_name_max_length is not applied. Bring the database up to date on the pre-accounts code first (manage.py migrate auth), then re-run.';
    END IF;

    IF EXISTS (SELECT 1 FROM django_content_type WHERE app_label = 'accounts' AND model = 'user') THEN
        RAISE EXCEPTION 'A django_content_type row for accounts|user already exists, so the auth|user row cannot be repointed onto it. Inspect both rows and merge them by hand.';
    END IF;
END $$;

-- Hold the table for the rest of the transaction so no user row is written
-- between the duplicate check below and the rename.
LOCK TABLE auth_user IN ACCESS EXCLUSIVE MODE;

-- accounts.User declares email as unique. Duplicates (most often several
-- legacy rows sharing the empty string) would fail the ADD CONSTRAINT below
-- with a bare Postgres error, so surface them up front with enough detail to
-- act on.
DO $$
DECLARE
    dupes text;
    blanks bigint;
    ci_dupes text;
BEGIN
    SELECT string_agg(format('%L (%s rows: %s)', email, n, ids), '; ' ORDER BY email)
      INTO dupes
      FROM (
        SELECT email, count(*) AS n, string_agg(id::text, ',' ORDER BY id) AS ids
          FROM auth_user GROUP BY email HAVING count(*) > 1
      ) d;
    IF dupes IS NOT NULL THEN
        RAISE EXCEPTION E'auth_user has duplicate email addresses, which accounts.User forbids:\n  %', dupes
            USING HINT = 'Give each row a distinct address (or delete the dead ones), then re-run. Blank emails are the usual cause.';
    END IF;

    SELECT count(*) INTO blanks FROM auth_user WHERE email = '';
    IF blanks > 0 THEN
        RAISE WARNING 'One user has a blank email. ACCOUNT_LOGIN_METHODS is {"email"}, so that account cannot log in until an address is set (the Django admin can still be reached by any account that has one).';
    END IF;

    -- Addresses differing only by case pass the unique index, which is
    -- case-sensitive -- but allauth.account.0006_emailaddress_lower lowercases
    -- every User.email row, at which point they collide and `migrate` dies
    -- part-applied. Refuse here, while refusing is still free.
    SELECT string_agg(format('%L (rows: %s)', email, ids), '; ' ORDER BY email)
      INTO ci_dupes
      FROM (
        SELECT lower(email) AS email, string_agg(id::text, ',' ORDER BY id) AS ids
          FROM auth_user WHERE email <> ''
        GROUP BY lower(email) HAVING count(*) > 1
      ) c;
    IF ci_dupes IS NOT NULL THEN
        RAISE EXCEPTION E'auth_user has email addresses that differ only by case:\n  %', ci_dupes
            USING HINT = 'allauth.account.0006_emailaddress_lower lowercases every user email during migrate, which would make these duplicates and abort the run half-applied. Make them distinct (or delete the dead rows) before converting.';
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 1. Rename the tables to what accounts.0001_initial would have created.
--    Postgres repoints existing foreign keys automatically, so django_admin_log
--    and the m2m tables keep referencing the same rows throughout.
-- ---------------------------------------------------------------------------

ALTER TABLE auth_user                  RENAME TO accounts_user;
ALTER TABLE auth_user_groups           RENAME TO accounts_user_groups;
ALTER TABLE auth_user_user_permissions RENAME TO accounts_user_user_permissions;

-- ---------------------------------------------------------------------------
-- 2. Widen the primary key and every column referencing it. django.contrib.auth
--    pins its own models to AutoField (integer); accounts.User inherits the
--    project DEFAULT_AUTO_FIELD of BigAutoField. The identity sequence and the
--    values in it are preserved by the type change.
-- ---------------------------------------------------------------------------

ALTER TABLE accounts_user                  ALTER COLUMN id      TYPE bigint;
ALTER TABLE accounts_user_groups           ALTER COLUMN user_id TYPE bigint;
ALTER TABLE accounts_user_user_permissions ALTER COLUMN user_id TYPE bigint;
ALTER TABLE django_admin_log               ALTER COLUMN user_id TYPE bigint;

-- ---------------------------------------------------------------------------
-- 3. Add the unique email constraint accounts.User declares, plus the
--    varchar_pattern_ops index Django pairs with every unique CharField on
--    Postgres so __startswith/__endswith lookups stay index-backed.
-- ---------------------------------------------------------------------------

ALTER TABLE accounts_user ADD CONSTRAINT accounts_user_email_key UNIQUE (email);
CREATE INDEX accounts_user_email_b2644a56_like
    ON accounts_user (email varchar_pattern_ops);

-- ---------------------------------------------------------------------------
-- 4. Rename indexes and foreign keys to the names a fresh migrate produces.
--    Purely cosmetic -- Django's schema editor resolves constraints by column,
--    not by name -- but it keeps this database diff-identical to a pristine one,
--    so future schema changes cannot behave differently here. IF EXISTS
--    throughout, because a database of a different vintage may have arrived at
--    these tables by another route and carry different names.
-- ---------------------------------------------------------------------------

ALTER INDEX IF EXISTS auth_user_pkey                        RENAME TO accounts_user_pkey;
ALTER INDEX IF EXISTS auth_user_username_key                RENAME TO accounts_user_username_key;
ALTER INDEX IF EXISTS auth_user_username_6821ab7c_like      RENAME TO accounts_user_username_6088629e_like;

ALTER INDEX IF EXISTS auth_user_groups_pkey                             RENAME TO accounts_user_groups_pkey;
ALTER INDEX IF EXISTS auth_user_groups_user_id_6a12ed8b                 RENAME TO accounts_user_groups_user_id_52b62117;
ALTER INDEX IF EXISTS auth_user_groups_group_id_97559544                RENAME TO accounts_user_groups_group_id_bd11a704;
ALTER INDEX IF EXISTS auth_user_groups_user_id_group_id_94350c0c_uniq   RENAME TO accounts_user_groups_user_id_group_id_59c0b32f_uniq;

ALTER INDEX IF EXISTS auth_user_user_permissions_pkey                              RENAME TO accounts_user_user_permissions_pkey;
ALTER INDEX IF EXISTS auth_user_user_permissions_user_id_a95ead1b                  RENAME TO accounts_user_user_permissions_user_id_e4f0a161;
ALTER INDEX IF EXISTS auth_user_user_permissions_permission_id_1fbb5f2c            RENAME TO accounts_user_user_permissions_permission_id_113bb443;
ALTER INDEX IF EXISTS auth_user_user_permissions_user_id_permission_id_14a6b632_uniq RENAME TO accounts_user_user_permi_user_id_permission_id_2ab516c2_uniq;

-- ALTER TABLE ... RENAME TO leaves the identity sequences under their old
-- names. Their type did widen to bigint along with the column, so this is
-- cosmetic -- but an "auth_user_id_seq" backing accounts_user is a trap for
-- whoever reads this schema next.
ALTER SEQUENCE IF EXISTS auth_user_id_seq                  RENAME TO accounts_user_id_seq;
ALTER SEQUENCE IF EXISTS auth_user_groups_id_seq           RENAME TO accounts_user_groups_id_seq;
ALTER SEQUENCE IF EXISTS auth_user_user_permissions_id_seq RENAME TO accounts_user_user_permissions_id_seq;

-- ALTER TABLE ... RENAME CONSTRAINT has no IF EXISTS, so guard each one.
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT * FROM (VALUES
            ('accounts_user_groups',           'auth_user_groups_user_id_6a12ed8b_fk_auth_user_id',        'accounts_user_groups_user_id_52b62117_fk_accounts_user_id'),
            ('accounts_user_groups',           'auth_user_groups_group_id_97559544_fk_auth_group_id',      'accounts_user_groups_group_id_bd11a704_fk_auth_group_id'),
            ('accounts_user_user_permissions', 'auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id', 'accounts_user_user_p_user_id_e4f0a161_fk_accounts_'),
            ('accounts_user_user_permissions', 'auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm', 'accounts_user_user_p_permission_id_113bb443_fk_auth_perm'),
            ('django_admin_log',               'django_admin_log_user_id_c564eba6_fk_auth_user_id',        'django_admin_log_user_id_c564eba6_fk_accounts_user_id')
        ) AS t(tbl, old_name, new_name)
    LOOP
        IF EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = r.old_name AND conrelid = r.tbl::regclass
        ) THEN
            EXECUTE format('ALTER TABLE %I RENAME CONSTRAINT %I TO %I', r.tbl, r.old_name, r.new_name);
        END IF;
    END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- 5. Repoint the content type. Renaming in place (rather than deleting and
--    letting post_migrate create a fresh row) is what keeps the four
--    add/change/delete/view_user permission rows attached to their existing
--    ids -- so group grants, per-user grants and django_admin_log entries all
--    survive. This mirrors contenttypes' own RenameContentType operation.
-- ---------------------------------------------------------------------------

UPDATE django_content_type
   SET app_label = 'accounts'
 WHERE app_label = 'auth' AND model = 'user';

-- ---------------------------------------------------------------------------
-- 6. Record accounts.0001_initial. The table it creates now exists, so marking
--    it applied is truthful, and it is what satisfies the swappable dependency
--    that admin.0001_initial resolves to.
-- ---------------------------------------------------------------------------

INSERT INTO django_migrations (app, name, applied)
VALUES ('accounts', '0001_initial', now());

