"""
Code to process new and complete requests

Currently placeholder to process dummy requests for step by step
for testing rather than calling the full functions directly.
"""
from pathlib import Path

from gqcore import get_config
from gqcore.utils.db.request_processing import get_next_completed_request, update_request_time, build_output_df, build_request_documentation, process_new_requests, process_completed_requests


# process_new_requests()

# process_completed_requests()


if __name__ == "__main__":

    config = get_config()
    data_root = Path(config["main"]["data_root"])

    request_id, request_contact, request_df = get_next_completed_request()

    update_request_time(request_id, "process_time")

    output_df = build_output_df(request_df)

    output_dir = data_root / "data" / "outputs" / str(request_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "data.csv"
    output_df.to_csv(output_path, index=False)

    doc_output =  output_dir / "documentation.pdf"
    build_request_documentation(request_id, request_df, doc_output)
