---
description: "GeoQuery's public APIs: the Public API for datasets and boundaries, the STAC API for catalog clients, and the stats API for GeoQuery's usage figures. Base URLs, rate limits and examples."
---

# API access

GeoQuery has three read-only APIs, for finding its datasets and boundaries from your own code and for showing its usage figures on your own site. They're free and need no key while they're in beta.

To extract data, use the [GeoQuery application](https://geoquery.aiddata.wm.edu): the APIs describe what's available, but don't submit requests.

| API | Base URL | Reference |
|-----|----------|-----------|
| Public API | `https://geoquery.aiddata.wm.edu/api/public/v1/` | [Interactive docs](https://geoquery.aiddata.wm.edu/api/public/v1/docs/) |
| STAC API | `https://geoquery.aiddata.wm.edu/api/stac/v1/` | [Interactive docs](https://geoquery.aiddata.wm.edu/api/stac/v1/docs/) |

Each API allows 100 requests an hour from one address. If you go over, you'll get a `429` response; wait and try again.

## Public API

Datasets and boundary sets, in the same terms the application uses.

| Endpoint | What it gives |
|----------|---------------|
| `GET datasets/` | Every public dataset: title, description, type, source, license, citation, time span and extent |
| `GET datasets/{name}/` | One dataset |
| `GET datasets/categories/` | The categories datasets are tagged with |
| `POST datasets/coverage/` | The datasets with data for the features you send, as `{"featureIds": [...]}` |
| `GET boundaries/autocomplete/?q=` | Boundary sets matching a search, such as `Ghana ADM2` |
| `GET boundaries/{name}/` | One boundary set, with the IDs of its features |
| `GET boundaries/presets/` | The [boundary presets](../data_documentation/boundary-presets.md), such as "Africa ADM1" |
| `GET stats/`, `stats/timeseries/`, `stats/status/` | GeoQuery's usage figures (see [Stats](#stats)) |

For example, to find Ghana's boundary sets:

```bash
curl "https://geoquery.aiddata.wm.edu/api/public/v1/boundaries/autocomplete/?q=Ghana"
```

Errors come back as `{"error": {"code": 404, "message": "..."}}`.

## STAC API

The same datasets as a [STAC](https://stacspec.org) catalog, for tools that read STAC, such as [pystac-client](https://pystac-client.readthedocs.io) and STAC Browser. Each dataset is a collection, and each of its time periods is an item.

```python
from pystac_client import Client

catalog = Client.open("https://geoquery.aiddata.wm.edu/api/stac/v1/")
for collection in catalog.get_collections():
    print(collection.id, collection.title)
```

## Stats

The figures on the [System Status](system-status.md) page, for showing on your own site. Pages on any website can read them directly from the browser.

| Endpoint | What it gives | Refreshed |
|----------|---------------|-----------|
| `GET stats/` | Requests and results extracted, datasets and boundary sets available, people and organizations served, recent turnaround, and the most requested datasets and boundary sets | Hourly |
| `GET stats/timeseries/?period=month` | Requests and results extracted over time, per `day`, `month` or `year` | Hourly |
| `GET stats/status/` | Whether GeoQuery is `healthy`, `backlogged` or `delayed` right now | Each call |

```js
const res = await fetch("https://geoquery.aiddata.wm.edu/api/public/v1/stats/");
const stats = await res.json();
console.log(`${stats.requests.completed + stats.requests.earlier_versions} requests completed`);
```

The [interactive docs](https://geoquery.aiddata.wm.edu/api/public/v1/docs/) describe every field. These figures are aggregate counts and never identify anyone.

## Examples

The [tutorials](tutorials/index.md) include notebooks that walk through each API with Python.
