"""Point clusters for the boundary map, where a selection is too dense to draw
as polygons.

They are built in two stages:

1. Here, once per collection, as part of its refresh (features.matviews): a
   supercluster-style hierarchy. At CLUSTER_MAX_ZOOM the collection's points
   are grouped greedily: the point in the densest spot that has not yet been
   claimed takes every unclaimed point within CLUSTER_RADIUS_PX of it, and
   becomes a cluster at their weighted mean. Each zoom below clusters the
   level above it the same way, so clusters sit wherever the features are and
   split apart as the map zooms in. There is no grid, and no tiles, so no
   seams. Stored as one row per cluster per zoom in features_cluster_points.
2. In each vector tile (features.views), the selected collections' clusters
   are merged across collections, never within one. The rule only looks a few
   radii away, so every tile computes exactly the merge the whole selection
   would; see _CLUSTER_TILE_SQL there.

Changing CLUSTER_MAX_ZOOM, CLUSTER_RADIUS_PX or the algorithm invalidates every
stored row: ship a migration that runs rebuild_cluster_points (all of
production takes seconds).
"""

import numpy as np

# Tiles up to this zoom are clusters for a dense selection; above it, polygons.
CLUSTER_MAX_ZOOM = 8

# Two clusters at one zoom are about this far apart, in CSS pixels, so they
# rarely overlap. The largest disc is 64 px across (CLUSTER_MAX_RADIUS in
# frontend/src/lib/components/map/MapFrame.svelte).
CLUSTER_RADIUS_PX = 64

# MapLibre's tile size in CSS pixels: a map at zoom z is TILE_PX * 2**z wide.
TILE_PX = 512

# Before clustering at CLUSTER_MAX_ZOOM, points are summed on a grid this many
# times finer than the radius. India ADM5's 650k points become far fewer
# weighted points, and a cluster moves by under half a cell, a few pixels at
# most, when every point in a cell is taken to sit at the cell's mean.
_PREBIN = 8

_KEY_OFFSET = 2**28

# Half the width of the EPSG:3857 world, which spans [-HALF, HALF] on both axes.
WEB_MERCATOR_HALF_WIDTH = 20037508.342789244


def radius(z):
    """CLUSTER_RADIUS_PX at zoom z, in EPSG:3857 metres."""
    return CLUSTER_RADIUS_PX * 2 * WEB_MERCATOR_HALF_WIDTH / (TILE_PX * 2**z)


def build_hierarchy(x, y, max_zoom=CLUSTER_MAX_ZOOM):
    """The clusters at every zoom 0..max_zoom, for points at x, y in EPSG:3857.

    Returns a list indexed by zoom of (x, y, n) arrays: each cluster's position
    and how many points it holds. Every level's n sums to len(x).
    """
    # Clamped to the world: Web Mercator stops at about 85 degrees, and the
    # centroid of a polar feature (Antarctica's is 43,000 km south of the
    # edge) would otherwise fall in no tile. Here it is counted at the edge.
    w = WEB_MERCATOR_HALF_WIDTH
    x = np.clip(np.asarray(x, dtype=float), -w, w)
    y = np.clip(np.asarray(y, dtype=float), -w, w)
    n = np.ones(len(x), dtype=np.int64)
    if len(x):
        x, y, n = _bin(x, y, n, radius(max_zoom) / _PREBIN)

    levels = [None] * (max_zoom + 1)
    for z in range(max_zoom, -1, -1):
        x, y, n = _greedy(x, y, n, radius(z))
        levels[z] = (x, y, n)
    return levels


def _cells(x, y, size):
    """Each point's cell on a grid of the given size, as one int64 key."""
    cx = np.floor(x / size).astype(np.int64)
    cy = np.floor(y / size).astype(np.int64)
    # Offset so both halves are non-negative and the key fits in 63 bits. At
    # the finest grid, the prebin at CLUSTER_MAX_ZOOM, the world is about 2**14
    # cells across, far inside the 2**28 either side of 0 this allows.
    return cx, cy, ((cx + _KEY_OFFSET) << 32) + (cy + _KEY_OFFSET)


def _bin(x, y, n, size):
    """Points summed per grid cell, each at the weighted mean of its points."""
    _, _, key = _cells(x, y, size)
    _, inverse = np.unique(key, return_inverse=True)
    w = np.bincount(inverse, weights=n)
    bx = np.bincount(inverse, weights=x * n) / w
    by = np.bincount(inverse, weights=y * n) / w
    return bx, by, w.astype(np.int64)


def _greedy(x, y, n, r):
    """One level of clustering with radius r.

    Seeds are taken densest first: by the weight in the seed's r-sized grid
    cell, then by the seed's own weight, then by position so the result does
    not depend on input order. A seed claims every unclaimed point within r,
    itself included, and becomes a cluster at their weighted mean.
    """
    count = len(x)
    if count == 0:
        return x, y, n

    cx, cy, key = _cells(x, y, r)
    # Points grouped by cell: members of a cell are by_cell[start:end].
    by_cell = np.argsort(key, kind="stable")
    unique_keys, start, cell_sizes = np.unique(
        key[by_cell], return_index=True, return_counts=True
    )
    span_of = {
        ((k >> 32) - _KEY_OFFSET, (k & 0xFFFFFFFF) - _KEY_OFFSET): (s, s + c)
        for k, s, c in zip(unique_keys.tolist(), start.tolist(), cell_sizes.tolist())
    }

    inverse = np.searchsorted(unique_keys, key)
    density = np.bincount(inverse, weights=n)[inverse]
    order = np.lexsort((y, x, -n, -density))

    claimed = np.zeros(count, dtype=bool)
    r2 = r * r
    out_x, out_y, out_n = [], [], []
    cxs, cys = cx.tolist(), cy.tolist()
    for i in order.tolist():
        if claimed[i]:
            continue
        ci, cj = cxs[i], cys[i]
        spans = [
            span_of[cell]
            for cell in ((ci + dx, cj + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
            if cell in span_of
        ]
        candidates = np.concatenate([by_cell[s:e] for s, e in spans])
        candidates = candidates[~claimed[candidates]]
        d2 = (x[candidates] - x[i]) ** 2 + (y[candidates] - y[i]) ** 2
        members = candidates[d2 <= r2]
        claimed[members] = True
        w = n[members]
        total = w.sum()
        out_x.append(float((x[members] * w).sum() / total))
        out_y.append(float((y[members] * w).sum() / total))
        out_n.append(int(total))

    return np.array(out_x), np.array(out_y), np.array(out_n, dtype=np.int64)
