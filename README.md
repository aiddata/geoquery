# geoquery-update

Development of an updated version of [GeoQuery](https://geoquery.org), built using Django and Svelte.

## Development

```
docker compose down && docker compose up
cd backend
uv run manage.py migrate
cd ../frontend
bun install
```

Site will be viewable at http://localhost:5173/

Import some boundaries:

```
uv run manage.py ingest_geoboundaries --active --public --iso3 AFG GHA --output-path ./boundary_data
```

Import some datasets:

- Copy some input dataset data to `/backend/dev_data` (.gitignored), e.g. `/backend/dev_data/rasters/esa_landcover/`
- Put the JSON for that dataset somewhere in `/backend`
- Run `docker compose exec backend uv run manage.py ingest_dataset <JSON PATH>`
- The dataset will ingest and you will be able to see it at localhost:8000/admin

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
