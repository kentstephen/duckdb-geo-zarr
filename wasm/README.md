# duckdb-zarr in the browser (duckdb-wasm)

Proof that the `zarr` extension, built for `wasm32-unknown-emscripten` from the
`wasm-attempt` branch in `vendor/duckdb-zarr`, loads into duckdb-wasm and reads
Zarr v2/v3 stores over HTTP in headless Chromium, including ARCO ERA5 from GCS.

## Build the extension

```sh
export PATH="/opt/homebrew/opt/rustup/bin:$HOME/.cargo/bin:$PATH"   # brew install rustup emscripten
cd vendor/duckdb-zarr && make wasm_mvp
# output: build/wasm_mvp/release/zarr.duckdb_extension.wasm
# afterwards, for native builds again: rm configure/platform.txt && make configure
```

## Run the browser test

```sh
cd wasm
npm i && npx playwright install chromium
cp ../vendor/duckdb-zarr/build/wasm_mvp/release/zarr.duckdb_extension.wasm www/
cp -r ../vendor/duckdb-zarr/test/fixtures/xarray_tutorial/consolidated_v{2,3}_http.zarr www/
python3 serve.py www 8765 &      # CORS + Range static server, plus /arco/ proxy to GCS
node run.mjs                     # headless Chromium, prints the era5.html output
```

Pages (open in a normal browser at http://127.0.0.1:8765/...):

- `index.html`: local fixtures (v2 gzip, v3 zstd), smoke test
- `era5.html`: ARCO ERA5 `1959-2022-1h-360x181_equiangular_with_poles_conservative.zarr`
  (blosc/lz4) via the `/arco/` proxy, with a SQL box for ad hoc queries against the
  `era5_t2m` view

The proxy exists because `storage.googleapis.com` sends no CORS headers for the
public ARCO bucket; the browser cannot fetch it directly. The proxy forwards Range
and passes 404s through (the store probes `zarr.json` before `.zmetadata`).

## What the page does

- boots `@duckdb/duckdb-wasm` from jsDelivr with `allowUnsignedExtensions`
- `LOAD 'http://127.0.0.1:8765/zarr.duckdb_extension.wasm'`
- `read_zarr_metadata`, `read_zarr`, an aggregate, and the `.zarr` replacement scan
  against both consolidated fixtures over HTTP

## Known limits of the wasm build

- no planner-driven predicate pushdown in the extension (native either; the DuckDB C API
  has no filter hook). Use the branch's `ranges=['time:539088:539111','latitude:40:50']`
  named parameter on `read_zarr` (inclusive; raw coordinate values, or ISO dates on a
  dimension with CF `units`: `time:2020-07-01:2020-07-01T23` on ERA5, whose `time` is hours
  since 1959-01-01). Chunks outside the range are never fetched and rows outside it are
  clipped, so no `WHERE` repeat is needed. Without `ranges=`, `WHERE time = x` scans all
  552k timesteps; LIMIT-bounded scans are still cheap because the scan streams
- remote stores need consolidated metadata (same as native remote stores)
- blosc works (c-blosc with nthreads=1 never spawns); rayon runs on a single-thread
  pool built at extension init
- `wasm_eh` and `wasm_threads` not yet tried (`make wasm_eh`, `make wasm_threads`)

## Timings seen (ERA5 1 degree, Chromium, proxy on localhost)

| query | time |
| --- | --- |
| `read_zarr_metadata` (35 arrays) | 0.6s |
| `read_zarr_groups` | 0.2s |
| first 3 rows | 1.3s (one 8-timestep chunk, ~4 MB compressed) |
| global mean/min/max over first timestep | 0.4s |
| `ranges=` one day x lat 40..50 x lon -10..5 (3 chunks) | 1.6s |
| `ranges=` 4 hours, global hourly means (1 chunk) | 0.25s |
