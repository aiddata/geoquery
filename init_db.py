
import click
import psycopg
from psycopg.errors import DuplicateTable

from conn import get_conn


def create_table_features(cur):
    # create features table
    cur.execute(
        """
        CREATE TABLE features (
            id              SERIAL PRIMARY KEY,
            shape           geometry NOT NULL
            );
        """
    )

def create_index_features(cur):
    # create spatial index on features table
    cur.execute(
        """
        CREATE INDEX features_geom_idx ON features
        USING GIST (shape);
        """
    )

def create_table_feature_collections(cur):
    cur.execute(
        """
        CREATE TABLE feature_collections (
            id                      SERIAL PRIMARY KEY,
            active                  boolean DEFAULT FALSE,
            public                  boolean DEFAULT FALSE,
            name                    varchar(200) UNIQUE NOT NULL,
            path                    varchar(200) UNIQUE NOT NULL,
            file_extension          varchar(10),
            file_mask               varchar(100),
            title                   varchar(200),
            description             varchar(500),
            details                 varchar(500),
            tags                    varchar(100)[],
            citation                varchar(500),
            source_name             varchar(100),
            source_url              varchar(200),
            other                   jsonb,
            is_global               boolean DEFAULT FALSE,
            group_name              varchar(100),
            group_title             varchar(100),
            group_class             varchar(100),
            group_level             integer
            spatial_extent          geometry,
            date_added              timestamp DEFAULT CURRENT_TIMESTAMP,
            date_updated            timestamp DEFAULT CURRENT_TIMESTAMP,
            ingest_src              varchar(200),

        );
        """
    )

def create_table_feat_map(cur):
    # create feat_map table
    cur.execute(
        """
        CREATE TABLE feat_map (
            id              SERIAL PRIMARY KEY,
            fc_id           int NOT NULL REFERENCES feature_collections(id),
            geom_id         int NOT NULL REFERENCES features(id),
            name            varchar(200),
            attr            jsonb,
            parent          int REFERENCES feat_map(id)
        );
        """
    )

def create_table_datasets(cur):
    # create datasets table
    cur.execute(
        """
        CREATE TABLE datasets (
            id                      SERIAL PRIMARY KEY,
            active                  boolean DEFAULT FALSE,
            public                  boolean DEFAULT FALSE,
            mapped                  boolean DEFAULT FALSE,
            name                    varchar(200) UNIQUE NOT NULL,
            type                    varchar(100) NOT NULL,
            path                    varchar(200) UNIQUE NOT NULL,
            file_extension          varchar(10),
            file_mask               varchar(100),
            title                   varchar(200),
            description             varchar(500),
            details                 varchar(500),
            version                 varchar(100),
            tags                    varchar(100)[],
            citation                varchar(500),
            source_name             varchar(100),
            source_url              varchar(200),
            variable_description    varchar(500),
            variable_factor         float,
            other                   jsonb,
            temporal_start          timestamp,
            temporal_end            timestamp,
            temporal_step           interval,
            spatial_extent          geometry,
            date_added              timestamp DEFAULT CURRENT_TIMESTAMP,
            date_updated            timestamp DEFAULT CURRENT_TIMESTAMP,
            global                  boolean DEFAULT FALSE,
            coverage_dependency     varchar(100) REFERENCES datasets(name),
            ingest_src              varchar(200)
        );
        """
    )

def create_table_dataset_resources(cur):
    # create datasets table
    cur.execute(
        """
        CREATE TABLE dataset_resources (
            id              SERIAL PRIMARY KEY,
            dataset_id      int REFERENCES datasets(id),
            name            varchar(200) UNIQUE NOT NULL,
            path            varchar(200) UNIQUE NOT NULL,
            temporal_start  timestamp,
            temporal_end    timestamp,
            spatial_extent  geometry
            );
        """
    )


def create_table_mappings(cur):
    cur.execute(
        """
        CREATE TABLE mappings (
            dataset_id      int REFERENCES datasets(id),
            map_name        varchar(100),
            map_val         int
        );
        """
    )

def create_table_processing_options(cur):
    cur.execute(
        """
        CREATE TABLE processing_options (
            id              SERIAL PRIMARY KEY,
            dataset_id      int REFERENCES datasets(id),
            short_name      varchar(100),
            function        varchar(100),
            kwargs          jsonb
        );
        """
    )



def create_table_coverage(cur):
    cur.execute(
        """
        CREATE TABLE coverage (
            geom_id         SERIAL PRIMARY KEY,
            dataset_id      int REFERENCES datasets(id),
            status          int
        );
        """
    )


def create_table_extract_tasks(cur):
    cur.execute(
        """
        CREATE TABLE extract_tasks (
            id              SERIAL PRIMARY KEY,
            resource_id     int REFERENCES dataset_resources(id),
            fm_id           int REFERENCES feat_map(id),
            op              int REFERENCES processing_options(id),
            status          integer DEFAULT 0,
            priority        integer DEFAULT 0,
            submit_time     timestamp DEFAULT CURRENT_TIMESTAMP,
            start_time      timestamp DEFAULT NULL,
            update_time     timestamp DEFAULT NULL,
            complete_time   timestamp DEFAULT NULL,
            attempts        integer DEFAULT 0,
            error           varchar(100) DEFAULT NULL,
            kwargs          jsonb DEFAULT NULL
        );
        """
    )


def create_table_extract_data(cur):
    cur.execute(
        """
        CREATE TABLE extract_data (
            id              int REFERENCES extract_tasks(id),
            name            varchar(100),
            data_column     varchar(100),
            float_value     float,
            int_value       int,
            str_value       varchar(100)
        );
        """
    )


def create_table_requests(cur):
    cur.execute(
        """
        CREATE TABLE requests (
            id              SERIAL PRIMARY KEY,
            date            timestamp,
            source          varchar(100),
            contact         varchar(100),
            custom_name     varchar(100),
            info            varchar(500),
            status          int,
            priority        int,
            submit_time     timestamp DEFAULT CURRENT_TIMESTAMP,
            prepare_time    timestamp DEFAULT NULL,
            process_time    timestamp DEFAULT NULL,
            complete_time   timestamp DEFAULT NULL
        );
        """
    )

def create_table_request_map(cur):
    cur.execute(
        """
        CREATE TABLE request_map (
            req_id      int REFERENCES requests(id),
            task_id     int REFERENCES extract_tasks(id)
        );
        """
    )


def init_db(overwrite: bool) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            if overwrite:
                cur.execute("DROP TABLE IF EXISTS coverage;")
                cur.execute("DROP TABLE IF EXISTS request_map;")
                cur.execute("DROP TABLE IF EXISTS requests;")
                cur.execute("DROP TABLE IF EXISTS extract_data;")
                cur.execute("DROP TABLE IF EXISTS extract_tasks;")
                cur.execute("DROP TABLE IF EXISTS feat_map;")
                cur.execute("DROP TABLE IF EXISTS features;")
                cur.execute("DROP TABLE IF EXISTS feature_collections;")
                cur.execute("DROP TABLE IF EXISTS dataset_resources;")
                cur.execute("DROP TABLE IF EXISTS mappings;")
                cur.execute("DROP TABLE IF EXISTS processing_options;")
                cur.execute("DROP TABLE IF EXISTS datasets;")


            create_table_feature_collection(cur)
            create_table_features(cur)
            create_index_features(cur)
            create_table_feat_map(cur)

            create_table_datasets(cur)
            create_table_dataset_resources(cur)
            create_table_mappings(cur)
            create_table_processing_options(cur)

            create_table_coverage(cur)
            create_table_extract_tasks(cur)
            create_table_extract_data(cur)

            create_table_requests(cur)
            create_table_request_map(cur)


@click.command()
@click.option("--overwrite/--no-overwrite", default=False)
def main(overwrite: bool) -> None:
    try:
        init_db(overwrite)
    except DuplicateTable:
        raise DuplicateTable(
            "Table(s) already exist, did you mean to use the --overwrite option?"
        )


if __name__ == "__main__":
    main()
