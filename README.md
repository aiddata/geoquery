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
