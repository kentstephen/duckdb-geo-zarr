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
