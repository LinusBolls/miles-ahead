"""Memory compaction for the service (called by preprocess.py; also runnable standalone on an existing geo/berlin_geo.pkl.gz).
- legal parking polygons are unioned per 400 m tile: distance to the union == distance to the nearest polygon, but far
  fewer GEOS objects (255k -> a few thousand).
- street names come from a numpy centroid grid instead of per-polygon lookups."""
import gzip, pickle, sys, time
import numpy as np, shapely

TILE = 400.0


def compact_legal(data):
    t = time.time()
    L = shapely.from_wkb(data["legal_wkb"])
    c = shapely.centroid(L)
    cx, cy = shapely.get_x(c), shapely.get_y(c)
    tx, ty = np.floor(cx / TILE).astype(np.int64), np.floor(cy / TILE).astype(np.int64)
    key = tx * 100000 + ty
    order = np.argsort(key, kind="stable")
    ks = key[order]
    bounds = np.flatnonzero(np.diff(ks)) + 1
    groups = np.split(order, bounds)
    tiles = []
    for g in groups:
        u = shapely.union_all(L[g], grid_size=0.1)
        u = shapely.simplify(u, 0.3, preserve_topology=True)
        tiles.append(u)
    data["legal_tiles_wkb"] = shapely.to_wkb(np.array(tiles, dtype=object))
    data["legal_cx"] = cx.astype(np.float32)
    data["legal_cy"] = cy.astype(np.float32)
    del data["legal_wkb"]
    print(f"legal: {len(L)} polygons -> {len(tiles)} tiles, coords {shapely.get_num_coordinates(L).sum()} -> "
          f"{shapely.get_num_coordinates(np.array(tiles, dtype=object)).sum()} ({time.time()-t:.0f}s)")
    return data


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "geo/berlin_geo.pkl.gz"
    d = pickle.load(gzip.open(p))
    if "legal_wkb" in d:
        d = compact_legal(d)
        with gzip.open(p, "wb", compresslevel=6) as f:
            pickle.dump(d, f, protocol=5)
    print("ok", sorted(d))
