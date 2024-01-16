from init_pg_tables import init_db
from init_pg_views import init_views

if __name__ == "__main__":
    init_db(False)
    init_view()
