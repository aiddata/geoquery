"""Generate the data documentation pages (datasets and boundaries) for the docs site.

build.build_bundle runs nightly in the cluster (datasets.tasks.build_data_docs_task)
and writes a tarball into the requests share. The docs workflow downloads it from
<app_url>/requests/docs/data-docs.tar.gz (.github/scripts/fetch_data_docs.py).
"""
