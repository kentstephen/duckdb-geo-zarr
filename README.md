# duckdb-geo-zarr

Testing the [xqlsystems duckdb-zarr](https://github.com/xqlsystems/duckdb-zarr) community
extension for geo imagery, then using the `h3` community extension to polyfill Zarr pixels
into H3 cells for SQL analytics.

## Setup

```sh
uv sync
git clone --depth 1 https://github.com/xqlsystems/duckdb-zarr vendor/duckdb-zarr
(cd vendor/duckdb-zarr && uv run scripts/generate_fixtures.py)   # local test fixtures
```

## Run the documented examples

```sh
uv run scripts_run_sql.py sql/00_repo_examples.sql        # OK/FAIL per statement
duckdb -init sql/init.sql < sql/00_repo_examples.sql       # plain CLI
```

Status 2026-08-15: zarr v0.1.3, h3 v1.5.5, DuckDB 1.5.5 on osx_arm64: all 12 examples pass.

## Browser (duckdb-wasm)

The community build of `zarr` excludes all wasm platforms, but the extension compiles
for `wasm32-unknown-emscripten` with a handful of small changes (branch `wasm-attempt`
in `vendor/duckdb-zarr`: gate `zarrs_http` off wasm, route all stores through
`DuckDbStore`, single-thread rayon pool at init, `-fPIC` for C deps, loop on short reads
in `DuckDbStore`). Blosc compiles and works on wasm without changes.

Status 2026-08-29: `zarr.duckdb_extension.wasm` loads into duckdb-wasm 1.33.1-dev57
(DuckDB v1.5.4) in Chromium and queries ARCO ERA5 (1 degree hourly, blosc/lz4) live from
GCS through a CORS proxy: metadata in 0.6s, one-timestep global aggregate in 0.4s. Results
match native.

Chunk pruning: the branch adds `ranges=['dim:lo:hi', ...]` to `read_zarr` (inclusive, either
bound may be empty; bounds are raw coordinate values, or ISO dates such as
`time:2020-07-01:2020-07-01T23` on a dimension with CF `units` like `hours since 1959-01-01`). Chunks whose coordinate min/max miss the
range are never read, and rows outside the range inside kept chunks are clipped, so the
bounds are written once. One July 2020 day over a Western Europe box reads 3 of 69,033
chunks: 1.6s in the browser, 2.6s native. The pruning passes the boundary cases listed in
upstream `docs/design.md` (decreasing coords, non-uniform spacing, chunk-seam point
predicate, empty result, inclusive bounds). Planner-driven pushdown (bounds inferred from
`WHERE`) remains blocked on the DuckDB C API, see `notes/predicate-pushdown-options.md`.

Map: `wasm/www/map.html` draws one day of the store as a deck.gl raster (one `ranges=`
query into a local table, 24 hourly frames, click or Shift+drag selection back to SQL rows
and the equivalent `read_zarr` query). Details in [`wasm/README.md`](wasm/README.md).

Status and next steps: `notes/status.md`. Map plan: `notes/plan-sql-to-map.md`.

Hosting: Source Cooperative (`data.source.coop`) serves with `Access-Control-Allow-Origin: *`
and Range support, so a Zarr there is queryable from the browser with no proxy. GCS
public buckets are not (hence `wasm/serve.py`'s `/arco/` proxy). Icechunk is out for the
wasm build: the Rust crate drags tokio, reqwest, object_store and opentelemetry, and there
is no JS reader either.

Build and run instructions, test pages, and headless runner are in [`wasm/`](wasm/README.md).
