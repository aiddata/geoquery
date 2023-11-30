


from gqcore.utils.db.conn import get_conn
with get_conn() as conn:
    with conn.cursor() as cur:
        query = """
        UPDATE extract_tasks
        SET    status = 0
        WHERE   status = 2 OR status = 1;
        """
        cur.execute(query)


from gqcore.utils.db.conn import get_conn
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE extract_data;")


from gqcore.tasks.process_extract_tasks import run_extract
run_extract()


from gqcore.utils.db.conn import get_conn
with get_conn() as conn:
    with conn.cursor() as cur:
        a = cur.execute("""SELECT * FROM extract_tasks""").fetchall()
        b = cur.execute("""SELECT * FROM extract_data""").fetchall()
        print('tasks', len(a), a)
        print('---')
        print('data', len(b), b)
        c = cur.execute("""SELECT * FROM extract_tasks WHERE status != 1""").fetchall()


# from gqcore.utils.db.conn import get_conn
# with get_conn() as conn:
#     with conn.cursor() as cur:
#         cur.execute("""
#         UPDATE extract_tasks
#         SET status = 0
#         WHERE id IN (SELECT id FROM extract_tasks WHERE status = 1 LIMIT 3)
#         """)


from gqcore.utils.db.conn import get_conn
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE coverage;")


from gqcore.utils.db.conn import get_conn
with get_conn() as conn:
    with conn.cursor() as cur:
        z = cur.execute("""SELECT * FROM coverage""").fetchall()
        print('coverage', len(z), z)


from gqcore.utils.db.conn import get_conn
with get_conn() as conn:
    with conn.cursor() as cur:
        x = cur.execute("""SELECT * FROM feature_collections""").fetchall()
        y = cur.execute("""SELECT * FROM features""").fetchall()
        z = cur.execute("""SELECT * FROM feat_map""").fetchall()
        print('feature_collections', len(x), x)
        print('features', len(y), y)
        print('feat_map', len(z), z)


from gqcore.utils.db.conn import get_conn
with get_conn() as conn:
    with conn.cursor() as cur:
        x = cur.execute("""SELECT * FROM datasets""").fetchall()
        y = cur.execute("""SELECT * FROM mappings""").fetchall()
        z = cur.execute("""SELECT * FROM processing_options""").fetchall()
        print('datasets', len(x), x)
        print('mappings', len(y), y)
        print('processing_options', len(z), z)
        w = cur.execute("""SELECT * FROM dataset_resources""").fetchall()
        print('dataset_resources', len(w), w)




from gqcore.utils.db.conn import get_conn
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE requests CASCADE;")
        cur.execute("TRUNCATE TABLE request_map CASCADE;")



from gqcore.utils.db.conn import get_conn
with get_conn() as conn:
    with conn.cursor() as cur:
        za = cur.execute("""SELECT * FROM requests""").fetchall()
        zb = cur.execute("""SELECT * FROM request_map""").fetchall()
        print('requests', len(za), za)
        print('request_map', len(zb), zb)
