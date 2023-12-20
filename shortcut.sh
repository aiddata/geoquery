python src/gqcore/tasks/init_pg_tables.py --overwrite
python ingest/features/prepare_gB.py
python ingest/datasets/esa_lc.py
python ingest/datasets/ltdr_ndvi.py
python src/gqcore/tasks/build_coverage_records.py
python src/gqcore/tasks/build_extract_tasks.py

python src/gqcore/tasks/create_request.py

python src/gqcore/tasks/process_requests.py
python src/gqcore/tasks/process_extract_tasks.py
python src/gqcore/tasks/clear_dangling_tasks.py
python src/gqcore/tasks/process_requests.py
