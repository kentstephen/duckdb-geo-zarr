-- Documented examples from xqlsystems/duckdb-zarr README and docs/README.md
-- Run from repo root:  duckdb -init sql/init.sql < sql/00_repo_examples.sql
-- Local fixtures come from `uv run scripts/generate_fixtures.py` inside vendor/duckdb-zarr

-- 1. Query a public Zarr store straight from its URL
SELECT time, latitude, longitude, precip
FROM read_zarr(
  'https://ncsa.osn.xsede.org/Pangeo/pangeo-forge/gpcp-feedstock/gpcp.zarr',
  dims=['time','latitude','longitude']
)
LIMIT 10;

-- 2. Inspect a store's arrays
SELECT name, role, dtype, shape
FROM read_zarr_metadata('https://ncsa.osn.xsede.org/Pangeo/pangeo-forge/gpcp-feedstock/gpcp.zarr');

-- 3. Single-group stores need no dims= (replacement scan on .zarr path)
SELECT lat, lon, AVG(temperature)
FROM 'vendor/duckdb-zarr/test/fixtures/xarray_tutorial/float_baseline.zarr'
GROUP BY lat, lon
LIMIT 5;

-- 4. Select one array by its store-relative path
SELECT * FROM read_zarr('vendor/duckdb-zarr/test/fixtures/bioimage/ome_zarr/synthetic_multichannel.ome.zarr', array_path='0') LIMIT 5;

-- 5. List a store's dimension groups
SELECT dims, shape, data_vars FROM read_zarr_groups('vendor/duckdb-zarr/test/fixtures/xarray_tutorial/multi_dim_group.zarr');

-- 6. docs: metadata of local fixture
SELECT * FROM read_zarr_metadata('vendor/duckdb-zarr/test/fixtures/xarray_tutorial/float_baseline.zarr');

-- 7. docs: read a store as a table
SELECT * FROM read_zarr('vendor/duckdb-zarr/test/fixtures/xarray_tutorial/float_baseline.zarr') LIMIT 5;

-- 8. docs: filter on coordinate columns
SELECT time, lat, lon, temperature
FROM read_zarr('vendor/duckdb-zarr/test/fixtures/xarray_tutorial/float_baseline.zarr')
WHERE lat > 0 AND lon < 180
LIMIT 5;

-- 9. docs: OME-Zarr metadata discovery
SELECT name, dims, shape, dtype
FROM read_zarr_metadata('vendor/duckdb-zarr/test/fixtures/bioimage/ome_zarr/synthetic_multichannel.ome.zarr');

-- 10. docs: image array aggregation
SELECT c, AVG(value) AS mean_intensity
FROM read_zarr('vendor/duckdb-zarr/test/fixtures/bioimage/ome_zarr/synthetic_multichannel.ome.zarr', array_path='0')
GROUP BY c;

-- 11. docs: label array with filtering
SELECT value AS label, COUNT(*) AS pixels
FROM read_zarr('vendor/duckdb-zarr/test/fixtures/bioimage/ome_zarr/synthetic_multichannel.ome.zarr', array_path='labels/nuclei/0')
WHERE value > 0
GROUP BY label
ORDER BY label;

-- 12. examples/demo.zarr
SELECT * FROM 'vendor/duckdb-zarr/examples/demo.zarr' LIMIT 5;
