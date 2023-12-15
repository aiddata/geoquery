REPO_ROOT = $(shell git rev-parse --show-toplevel)
SHORT_COMMIT_HASH = $(shell git rev-parse --short HEAD)
container:
	podman build --build-context "REPO_ROOT=$(REPO_ROOT)" --tag geoquery-backend:$(SHORT_COMMIT_HASH) .

