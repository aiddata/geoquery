from .init_pg_functions import init_functions
from .init_pg_tables import main as init_tables
from .init_pg_views import init_views


def main():
    init_tables()
    init_views()
    init_functions()


if __name__ == "__main__":
    main()
