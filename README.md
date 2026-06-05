# geoquery-update

Development of an updated version of [GeoQuery](https://geoquery.org), built using Django and Svelte.

## Development

```
docker compose down && docker compose up
cd backend
```

Migrate the database and create a superuser:

```
uv run manage.py migrate
uv run manage.py createsuperuser
```

Get the frontend going:

```
cd ../frontend
bun install
```

Site will be viewable at http://localhost:5173/


Import some boundaries:

```
uv run manage.py ingest_geoboundaries --active --public --iso3 AFG GHA
```

Import some datasets:

The `./data` directory (.gitignored) is mounted into the containers at `/data`, so reference dataset paths absolutely as `/data/...`.

- Copy some input dataset data to `./data`, e.g. `./data/rasters/esa_landcover/`
- Put a dataset JSON into `./data`, e.g. [`esa_landcover.json`](https://raw.githubusercontent.com/cmhwang/geo-datasets/7d5148dafe47a3c9532aa718313ae7c7e3fd5d6d/datasets/esa_landcover/raster_ingest.json)
- Edit the path at the top of the JSON file to e.g. `"/data/rasters/esa_landcover"`
- `uv run manage.py ingest_dataset /data/esa_landcover.json`

### Documentation

All documentation can be found in `/docs`.

To view the documentation in your web browser, follow the following steps:

- Install gqcore, this repository's Python package:
  ```sh
  # cd to the root of this repository
  pip install -e .
  ```
- Run `mkdocs serve` from the root of this repository
- Visit http://localhost:8000 in your browser
- Changes to files in `/docs` will render live in your browser!
