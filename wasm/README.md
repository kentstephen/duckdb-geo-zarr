# duckdb-zarr in the browser (duckdb-wasm)

The `zarr` extension, built for `wasm32-unknown-emscripten` from the patches in
`../patches/duckdb-zarr/` (branch `wasm-attempt` of a local clone in `vendor/duckdb-zarr`),
loads into duckdb-wasm and reads Zarr v2/v3 stores over HTTP in Chromium. The pages in
`www/` are deployed to Netlify (https://duckdb-geo-zarr.netlify.app, `netlify.toml` at
the repo root, publish dir `wasm/www`) and to GitHub Pages from `main` by
`.github/workflows/pages.yml`; everything in `www/` is static (the 3.6 MB extension binary and two small fixture stores
are committed so the site is self-contained).

## Pages

- `/` serves `map.html` (a rewrite in `netlify.toml`); there is no landing page.
- `map.html`: ARCO ERA5 2 m temperature (1°, hourly, 1959-2022, on GCS) as a deck.gl
  raster over MapLibre. Pick a date window and a frame mode (hourly, daily mean, monthly
  mean); each frame is one `read_zarr(..., ranges=[time, ...])` query fetched when shown,
  with playback and a scrubber. Click a cell or Shift+drag a box: its per-frame
  mean/min/max curve is one query, drawn on the scrubber, and the cells at the current
  frame are listed. "Pin window" reads the window into a table so frames and selections
  become local queries. Colormaps: a blue-to-orange diverging ramp (default) plus the 107
  maps of the Source Cooperative zarr-viewer (`colormaps.png`, deck.gl-raster's sprite,
  MIT). `#selftest` / `#selftest-daily` log a box for `run.mjs`. Reads GCS through the
  same-origin `/arco/` proxy (below).
- `map-hrrr.html`: NOAA HRRR 48 h forecast (dynamical.org, on Source Cooperative), same
  design. Nothing is read up front. Pick a run (init date + cycle, or
  "Latest") and a variable; the 49 forecast hours are frames, each one a
  `read_zarr(..., ranges=[init, lead])` query fetched when shown, kept for the last 12
  frames, with a 2-frame lookahead for playback. Click a cell or Shift+drag a box: its
  per-hour mean/min/max curve is one query (`runbox`), drawn on the scrubber, and the cells
  at the current hour are listed and outlined. The HRRR grid is Lambert conformal (3 km,
  1799 x 1059); the page projects with the sphere LCC from `spatial_ref` (checked against
  the store's `latitude`/`longitude` arrays to under 1 m) and paints each frame into an
  equirectangular texture through a precomputed pixel-to-cell lookup. Colormaps applied
  with the middle at the frame median and arms to p2/p98.
  `?init=2025-08-01T06&var=composite_reflectivity` preselects a run and variable.
  `#selftest` / `#selftest-var` log a box for `run.mjs`.
- `hrrr.html`: the HRRR store as a SQL console with timings and a query box.
- `fixtures.html`: smoke test against two local fixture stores (v2 gzip, v3 zstd).
- `era5.html`: the ARCO ERA5 store as a SQL console with timings.

The ERA5 pages read `storage.googleapis.com` through a same-origin `/arco/` path: the
public bucket sends no CORS headers. Locally `serve.py` proxies it; on Netlify a `200`
rewrite in `netlify.toml` does (`/arco/*` to the bucket, Range passes through and 206
comes back, checked). On GitHub Pages there is no proxy, so the ERA5 pages do not work
there.

## Build the extension

```sh
export PATH="/opt/homebrew/opt/rustup/bin:$HOME/.cargo/bin:$PATH"   # brew install rustup emscripten
git clone https://github.com/xqlsystems/duckdb-zarr vendor/duckdb-zarr
cd vendor/duckdb-zarr && git am ../../patches/duckdb-zarr/*.patch
make wasm_mvp
# output: build/wasm_mvp/release/zarr.duckdb_extension.wasm
# afterwards, for native builds again: rm configure/platform.txt && make configure
```

## Run locally

```sh
cd wasm
npm i && npx playwright install chromium
cp ../vendor/duckdb-zarr/build/wasm_mvp/release/zarr.duckdb_extension.wasm www/   # if rebuilt
python3 serve.py www 8765 &      # CORS + Range static server, plus /arco/ proxy to GCS
node run.mjs hrrr.html           # headless Chromium, prints the page's log
node run.mjs "map.html#selftest-daily" shot.png   # ERA5 map selftest plus a screenshot
node run.mjs "map-hrrr.html#selftest-var"          # HRRR map selftest
BASE=https://duckdb-geo-zarr.netlify.app/ node run.mjs era5.html   # same against the deployed site

Deploy: `npx netlify-cli deploy --prod --dir wasm/www --no-build` (site `duckdb-geo-zarr`, linked in `.netlify/`).
```

Then open http://127.0.0.1:8765/ in a browser. Any static server works for the HRRR and
fixture pages as long as it answers Range requests; `serve.py` is only required for ERA5 (the `/arco/` proxy).

## What the pages do

- boot `@duckdb/duckdb-wasm` from jsDelivr with `allowUnsignedExtensions`
- `LOAD` the extension from the page's own directory
- `read_zarr_metadata`, `read_zarr_groups`, `read_zarr` with `ranges=`, aggregates, joins
  between arrays of the same store, and the `.zarr` replacement scan (fixtures page)

## The HRRR store

`https://data.source.coop/dynamical/noaa-hrrr-forecast-48-hour/v0.1.0.zarr`, Zarr v3.
Dims `init_time` (runs every 6 h since 2018-07-13, seconds since 1970), `lead_time`
(0..48 h in seconds), `y`, `x` (metres). Data arrays are `sharding_indexed`: one shard per
run (`[1, 49, 1060, 1800]`), inner chunks `[1, 49, 265, 300]` blosc/zstd. An inner chunk
holds every lead for a 265 x 300 cell tile, so a box over a whole run costs one chunk and a
full-CONUS frame costs 24. Source Cooperative sends `Access-Control-Allow-Origin: *` and
supports Range, so the browser reads it directly. The ISO bound on `init_time`
(`init_time:2025-08-01T06:2025-08-01T06`) resolves through the array's CF `units`.

## Timings (Chromium on an M-series Mac, Source Cooperative direct)

| query | time |
| --- | --- |
| `read_zarr_metadata` (36 arrays) | 1.1s |
| first touch of a run: 60 km box, one lead | 4.7s (the run's chunks come down) |
| same box, all 49 leads | 0.7s |
| full CONUS, one lead (1.9M cells, 24 chunks) | 0.85s after first touch |
| full CONUS, all 49 leads, grouped by lead | 13.7s |
| map frame (query + Arrow to Float32 + texture) | 5s first, ~1s after |

ERA5 (1 degree, through the local proxy): metadata 0.6s, one day x 10 x 15 degree box 1.6s,
4 hours of global means 0.25s.

## Known limits of the wasm build

- No planner-driven predicate pushdown (native either; the DuckDB C API has no filter hook).
  `ranges=['dim:lo:hi', ...]` on `read_zarr` is the substitute: inclusive, either bound may
  be empty, raw coordinate values or ISO dates on a dimension with CF `units`. Chunks
  outside the range are never fetched and rows outside it are clipped, so no `WHERE`
  repeat is needed. Without `ranges=`, a `WHERE` scans the whole array.
- Reading a 1-D coordinate array by `array_path` (`x`, `init_time`) fails with a duplicate
  column name (the dimension and the value share it); read a 2-D array such as `latitude`
  or a 1-D array with a different name (`ingested_forecast_length`) instead.
- `ingested_forecast_length` / `expected_forecast_length` read back as NULL on wasm
  (float64 with a fill value); untested native.
- Remote stores need consolidated metadata (`zarr.json` with `consolidated_metadata`, or
  `.zmetadata`).
- blosc works (c-blosc with nthreads=1 never spawns); rayon runs on a single-thread pool
  built at extension init.
- `wasm_eh` and `wasm_threads` not yet tried (`make wasm_eh`, `make wasm_threads`).
- Icechunk stores (the dynamical.org `*-analysis` datasets) are out of reach: the Rust
  crate needs tokio/reqwest/object_store, and there is no JS reader.
