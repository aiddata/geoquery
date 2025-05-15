REPO_ROOT = $(shell git rev-parse --show-toplevel)
SHORT_COMMIT_HASH = $(shell git rev-parse --short HEAD)
container:
	podman build --file Containerfile --tag geoquery-backend:$(SHORT_COMMIT_HASH) $(REPO_ROOT)

