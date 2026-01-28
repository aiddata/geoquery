# geoquery-update

Development of an updated version of [GeoQuery](https://geoquery.org), built using Django and Svelte.

## Development

### Backend

Run the development database:

```
```

Run any migrations:

```
uv run manage.py migrate
```

Run the server:

```
uv run manage.py runserver
```

### Frontend

`cd frontend`

...

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
