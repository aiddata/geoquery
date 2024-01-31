# Building the backend container

This is an OCI container designed to run GeoQuery backend jobs.
It comes with the package in `/src` preinstalled.

## Building
- run `make` to build the container
  - requires Podman >=4.0
- the container will be tagged as geoquery-backend:XXXXXXX, with the current short commit hash as the tag
  - please stash or commit any local changes before building!
 
## Pushing

- login to Docker Hub with `podman login docker.io`
- `podman push geoquery-backend:XXXXXXX docker.io/jacobwhall/geoquery-backend:XXXXXXX`

## Using

images are available at https://hub.docker.com/r/jacobwhall/geoquery-backend
