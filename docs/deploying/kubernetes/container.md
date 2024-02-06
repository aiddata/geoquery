# Building the Backend Container

This is an OCI container designed to run GeoQuery backend jobs.
It comes with the gqcore package preinstalled in `/src`.

## Building
- Since the Makefile loads content into the image from your repository's working directory, **please stash or commit any local changes before building!**
- `cd` to the `/k8s/containers/backend` directory in this repo
- Run `make` to build the container
  - Requires Podman >=4.0
- The container will be tagged as geoquery-backend:XXXXXXX, with the current short commit hash as the tag
 
## Pushing

- login to Docker Hub with `podman login docker.io`
- Push the container to Docker Hub
  ```
  podman push geoquery-backend:XXXXXXX docker.io/jacobwhall/geoquery-backend:XXXXXXX
  ```

## Using

Images are available at [https://hub.docker.com/r/jacobwhall/geoquery-backend](https://hub.docker.com/r/jacobwhall/geoquery-backend)

The image tag used by the helm chart is set using the `default_image` variable in `values.yaml`.
Make sure to update that variable to deploy your most recent image.
