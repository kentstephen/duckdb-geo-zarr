# Virtual Zarr support in duckdb-zarr

A feasibility study for [xqlsystems/duckdb-zarr#45](https://github.com/xqlsystems/duckdb-zarr/issues/45): reading TIFF, HDF5 and NetCDF through VirtualiZarr-style chunk manifests, with no conversion of the underlying data. Written against upstream `main` at `46fd732` (v0.1.3) and zarrs 0.23.10 as pinned in `Cargo.lock`.

## 1. Summary

- The manifest layer is small. A virtual Zarr is ordinary Zarr metadata plus a map from chunk key to (path, offset, length). duckdb-zarr already reads through a custom zarrs store with byte-range support (`DuckDbStore`) and already serves metadata from an in-memory map (`ConsolidatedCacheStore`). A manifest-backed store is the same shape: a few hundred lines in `src/zarr_reader/`, and nothing above the store layer changes.
- The codec layer is where the effort is. Chunks decode with whatever compressor the source file used. HDF5 and NetCDF4 sources (zlib, shuffle, fletcher32) are covered by zarrs behind feature flags that are currently off. TIFF sources need codecs zarrs does not ship (LZW, predictor, JPEG, WebP, LZMA, Lerc), each a separate codec plugin.
- The manifest format decides reach. Kerchunk JSON is a single file and is the easiest target. Kerchunk Parquet is a directory of Parquet tables, which DuckDB reads natively. Icechunk is the only format virtual-tiff writes today and its Rust crate brings tokio, reqwest, object_store and opentelemetry, which is a large dependency step for a loadable extension.
- Rough effort: NetCDF4/HDF5 over kerchunk JSON in days. Deflate TIFF for free once that exists. LZW and predictor a few days each in pure Rust. JPEG, WebP and Lerc weeks each, with build risk on every DuckDB CI target. Icechunk is a separate decision.

## 2. What a virtual Zarr is

VirtualiZarr's in-memory model is a `ChunkManifest`: three arrays (paths, offsets, lengths) indexed by chunk key. A `ManifestArray` pairs one manifest with the usual Zarr array metadata: shape, dtype, chunks, codecs, fill value, attributes. A chunk is virtual (points into an external file), missing (empty path, read as fill value) or inlined (raw bytes carried in the manifest). Nothing in the model is specific to the source format. An HDF5 dataset chunk, a TIFF tile and a NetCDF3 record all become (path, offset, length).

VirtualiZarr persists this three ways:

| Format | Layout | Notes |
|---|---|---|
| Kerchunk JSON | one `.json` file with `version`, `templates`, `gen`, `refs` | Zarr v2 keys (`.zgroup`, `.zarray`, `.zattrs`, `var/0.0.1`). A ref value is an inline string, a `base64:` string, `[url]` for a whole file, or `[url, offset, length]`. |
| Kerchunk Parquet | directory with `.zmetadata` and `var/refs.N.parq` | Columns `path`, `offset`, `size`, `raw`. `record_size` refs per file, default 10,000. `.zmetadata` carries all Zarr metadata. |
| Icechunk | Icechunk repository with virtual chunk refs | Zarr v3 model. Binary manifests, transactional. Needs the `icechunk` crate to read. |

Parsers exist for HDF5/NetCDF4, NetCDF3, FITS, TIFF (virtual-tiff) and existing kerchunk references. virtual-tiff persists only to Icechunk today, so a TIFF manifest reaches a kerchunk target only through a Python round trip (`open_virtual_dataset` then `to_kerchunk`).

An older proposal, zarr-specs issue 287 (February 2024), defines a chunk manifest as a Zarr v3 storage transformer stored beside the array metadata. It did not land in the spec and zarrs does not implement it. It matters here because a manifest-backed store in duckdb-zarr is the natural place to honor it if it ever does.

## 3. How duckdb-zarr reads today

The read path at `46fd732`:

1. `open_store` in `src/zarr_reader/meta.rs` builds a `ZarrStore` (`Arc<dyn ReadableStorageTraits>`). Bare paths use zarrs's `FilesystemStore`, `http(s)://` uses `zarrs_http`, and every other remote scheme uses `DuckDbStore` (`src/zarr_reader/duckdb_store.rs`), which implements `get_partial_many` (byte ranges) and `size_key` over DuckDB's C file API (`duckdb_file_system_open`, seek, read). This is how S3, GCS and Azure arrive with secrets already applied.
2. `ConsolidatedCacheStore` (`src/zarr_reader/consolidated_store.rs`) wraps the store and serves metadata keys (`zarr.json`, `.zarray`, `.zattrs`, `.zgroup`, `.zmetadata`) from a `HashMap<StoreKey, Bytes>` built from consolidated metadata, so `Array::open` costs zero round trips. Non-metadata keys pass through to the inner store.
3. `Array::open` (zarrs) parses metadata, v2 or v3, and `retrieve_chunk` in `src/read_zarr.rs` decodes one chunk through the codec chain. Missing chunks become fill value.
4. Everything above (dimension groups, coordinate loading, the pivot, projection) sees only arrays and chunk indices.

The key observation: layer 2 is already half a manifest store. It maps keys to bytes from a parsed document. A virtual store adds the other half: mapping chunk keys to byte ranges in other files.

## 4. Design: a manifest-backed store

### 4.1 `ManifestStore`

A new `ReadableStorageTraits` implementation beside the existing two:

- Construction: read the manifest document through the DuckDB file API, so the manifest itself may live on S3, then parse it into `metadata: HashMap<StoreKey, Bytes>` and `chunks: HashMap<StoreKey, ChunkRef>`, where `ChunkRef` is `{ path, offset, length: Option<u64> }` or `Inline(Bytes)`.
- `get_partial_many(key, ranges)`: a metadata or inline key returns slices of the cached bytes, with the same range clamping `ConsolidatedCacheStore` already does. A chunk key opens `path`, seeks to `offset + range.start`, reads `range.length`. An unknown key returns `None`, which zarrs turns into fill value.
- `size_key`: `length` for chunk refs, byte length for cached values, a file stat when `length` is absent (whole-file refs).
- Handle cache: one NetCDF file backs thousands of chunks, and a remote open is at least one HEAD. Keep an LRU of open `duckdb_file_handle`s keyed by path. `DuckDbStore` opens and closes per call, which is correct for a real Zarr where each chunk is its own object and wrong here.
- Path resolution: kerchunk paths are absolute URLs or paths as written by the producer. Pass them to DuckDB unchanged so `s3://`, `gs://`, `https://` and local paths all work and the secrets manager applies. An optional `path_rewrite=['from', 'to']` argument covers manifests written against one host and read from another.

`ConsolidatedCacheStore` and `ManifestStore` share the metadata half. Either fold the manifest into the cache store (a `chunks` map that is empty for real Zarr) or lift the cached-metadata behaviour into a helper both use.

### 4.2 Wiring

`read_zarr('refs.json')` can detect a manifest by a `.json` extension or by a `version`/`refs` top-level key after one read. An explicit `format='kerchunk'` argument avoids the probe on remote paths and is the cleaner surface. `read_zarr_metadata` and `read_zarr_groups` work unchanged because array listing already prefers consolidated metadata, and a manifest is consolidated by construction. The replacement scan can match `*.json` only if the user opts in; guessing is worse than an explicit argument.

Zarr v2 chunk keys from kerchunk (`var/0.0.1`) need no translation. zarrs's v2 chunk key encoding produces the same keys the store is asked for, and both `.` and `/` separators are handled by `dimension_separator` in `.zarray`.

### 4.3 Kerchunk JSON details

- `version: 1` `templates` and `gen`: jinja-style `{{name}}` substitution and cartesian key generation. VirtualiZarr does not emit these; kerchunk's own combiners do. Support `refs` first and reject `gen` with a clear error. A minimal template substituter is a later addition if real files need it.
- `base64:` inline chunks: decode at parse time. `base64` is already a dependency.
- Plain-string inline values: metadata, and small coordinate arrays, which is common.
- `[url]` with no offset or length: whole file. `size_key` stats the file.
- Large manifests: one JSON document with millions of chunks is a parse-time and memory cost. That is exactly why kerchunk Parquet exists.

### 4.4 Kerchunk Parquet

Two routes:

- Inside the store: read `.zmetadata` for metadata and, on first touch of an array, read its `refs.N.parq` files. That means a Parquet reader in the extension (the `parquet` crate, which is heavy) or a call back into DuckDB's own reader through `duckdb_query` from the bind callback.
- As a DuckDB table: `read_zarr` takes the manifest as a relation with columns `(key VARCHAR, path VARCHAR, offset BIGINT, size BIGINT, raw BLOB)`. The user builds it with `read_parquet('refs/**/*.parq')` or from any other source. The manifest becomes ordinary SQL data: filterable, joinable, materializable, and a manifest for a set of COGs can be generated in SQL without VirtualiZarr. Table-valued input to a table function is awkward in the C API, so this likely means `CREATE TABLE refs AS ...` followed by `read_zarr(manifest_table='refs')`, with the extension reading the table through `duckdb_query`.

The second route is specific to DuckDB and not available to any other Zarr reader. It is also a design discussion, not just an implementation.

### 4.5 Icechunk

Reading virtual refs from Icechunk requires the `icechunk` crate, which brings tokio, reqwest, object_store and opentelemetry. That roughly doubles the dependency surface of a loadable extension and interacts badly with the existing OpenSSL and mingw constraints in `Cargo.toml`. Two alternatives sit outside the extension: ask producers to `to_kerchunk` alongside `to_icechunk`, or wait for a lightweight Icechunk manifest reader. Not in scope for a first version.

## 5. Codecs

The manifest yields bytes; zarrs must then decode them with the codec chain the producer wrote into `.zarray`. Coverage in zarrs 0.23.10, checked against its `Cargo.toml` features and `src/array/codec/`:

| Codec (v2 numcodecs id) | Typical source | zarrs status | In duckdb-zarr build |
|---|---|---|---|
| `zlib` | HDF5/NetCDF4 deflate, TIFF Deflate | `zlib` feature | off, enable |
| `shuffle` | HDF5 shuffle filter | always on (`bytes_to_bytes/shuffle`) | yes |
| `fletcher32` | HDF5 checksum filter | `fletcher32` feature | off, enable |
| `fixedscaleoffset` | HDF5 scale-offset filter | always on | yes |
| `bz2` | rare HDF5 | `bz2` feature | off, enable |
| `gzip`, `zstd`, `blosc` | native Zarr | on | yes (blosc off on windows mingw) |
| `delta` | some kerchunk outputs | not in zarrs | plugin, small |
| LZW, predictor | GeoTIFF, very common | not in zarrs | plugin, pure Rust, small |
| PackBits | GeoTIFF | zarrs `packbits` is Zarr v3 bit packing, not TIFF PackBits | plugin, small |
| JPEG, JPEGXL, WebP | aerial imagery COGs | not in zarrs | plugin with an external decoder |
| LZMA | GeoTIFF | not in zarrs | plugin (`xz2` or `lzma-rs`) |
| Lerc, PNG | GeoTIFF | not in zarrs | plugin |
| szip | older HDF5 | not in zarrs, licensing | skip |

Consequences:

- NetCDF4/HDF5 as produced by VirtualiZarr's HDFParser is two feature flags away (`zlib`, `fletcher32`) plus the store.
- Deflate GeoTIFFs decode with `zlib` too, provided virtual-tiff writes the codec as numcodecs `zlib` and the predictor is none. With predictor 2 or 3 (horizontal or floating-point differencing) a predictor codec is required. It is a few dozen lines.
- LZW is the common case for legacy COGs and is small to implement (the TIFF variant, MSB-first with early change). Worth doing early.
- The JPEG family and WebP carry the cost and CI risk: a decoder must build on linux, macOS, windows_amd64_mingw and any future wasm target, and mingw already forces `blosc` off. Pure-Rust decoders (`zune-jpeg`, `image-webp`) reduce that risk.
- Codec ids must match. virtual-tiff and VirtualiZarr write numcodecs-style names and configs; zarrs converts v2 `compressor` and `filters` to v3 codec names in `zarrs_metadata_ext`. Anything unrecognized fails at `Array::open`, before any bytes are read, which is at least a clean failure.
- HDF5 carries semantics outside the codec chain: `_FillValue` versus HDF5 fill, `scale_factor` and `add_offset` (already handled by the packed-integer path in `docs/design.md`), and dtypes outside zarrs's "v3-compatible subset of v2". Compound types and enums are out. Variable-length strings (`|O` with a `vlen-utf8` filter) go through zarrs's `vlen_v2`; arbitrary object dtypes do not. `docs/design.md` already lists structured and object dtypes as a bind-time error, so this is consistent.

## 6. What works unchanged

- The pivot, dimension groups, coordinate caching, projection pushdown and NULL masking. None of it touches the store.
- The coordinate-range pruning planned for v0.3 in `docs/design.md`. It operates on coordinate values and chunk indices. It is more valuable for virtual stores than for real Zarr: a pruned chunk means never opening the backing NetCDF or TIFF at all.
- CF attributes. Kerchunk carries `_ARRAY_DIMENSIONS` in `.zattrs`, which the v2 dimension-name path already reads.
- Remote credentials. Referenced files resolve through the same DuckDB file API as the store today.

## 7. Open questions and risks

- zarrs v2 metadata acceptance for HDF5-derived arrays. `<f4` and `|S16` are fine; `|O` and compound are not. Needs a test against a real HDFParser output. A CMIP6 or NOAA NetCDF4 file is the natural fixture.
- DuckDB file handle cost across a scan: how many handles may stay open, and how DuckDB's HTTP filesystem behaves under many range reads on one URL. A per-path LRU with a small cap is the safe default.
- Manifests referencing many files with different credentials. DuckDB secrets are scoped by path prefix, so this should work, but is untested.
- Whole-file refs on remote paths cost a stat per call. Cache the size with the handle.
- `dimension_separator`. VirtualiZarr can write either `.` or `/`. The store must not assume one.
- Version 1 `gen` blocks: reject first, implement if asked.
- Surface: a `format=` argument, extension sniffing, or a separate `read_virtual_zarr` function. Maintainer preference.
- Parallel scan. When per-chunk reads share file handles, the handle cache needs to be `Sync` and either lock per handle or open one handle per thread.

## 8. Effort

| Piece | Scope | Estimate |
|---|---|---|
| `ManifestStore` for kerchunk JSON (`refs`, inline, base64, whole-file), handle cache, wiring, tests | store layer only | 2 to 4 days |
| Enable `zlib`, `fletcher32`, `bz2`; NetCDF4 fixture; CI on all targets | Cargo, fixtures, CI | 1 day, plus whatever mingw does |
| Kerchunk Parquet inside the store | Parquet reader or `duckdb_query` callback | 2 to 3 days |
| Manifest as a DuckDB table (`manifest_table=`) | new argument, `duckdb_query` from bind | 3 to 5 days, design discussion first |
| TIFF: LZW, predictor, PackBits, LZMA, delta codecs | pure Rust codec plugins | 1 to 3 days each |
| TIFF: JPEG, WebP, Lerc, PNG | plugins with external decoders, CI | 1 to 2 weeks each, uncertain |
| Icechunk virtual refs | `icechunk` crate | large, separate decision |
| `path_rewrite=` argument | small | half a day |

A first PR worth reviewing: kerchunk JSON store, `zlib` and `fletcher32` enabled, one NetCDF4 fixture generated by VirtualiZarr in `scripts/generate_fixtures.py`, and a SQL test asserting `read_zarr('fixture.json')` equals `read_zarr` over the same data written as real Zarr. That demonstrates the whole chain end to end and leaves TIFF codecs as independent follow-ups, each with its own fixture (a Deflate COG, an LZW COG).

## 9. Directions this opens

- Manifests as SQL. Building a manifest for a directory of COGs is a scan of TIFF headers, and the result is a table. DuckDB could produce, store, filter and hand back manifests with no Python in the loop.
- Cross-format joins. A NetCDF climatology and a GeoTIFF land-cover raster as two `read_zarr` calls in one query, joined on coordinates or on H3 cells.
- Archival data without conversion. Any NetCDF or HDF5 archive with a published kerchunk index becomes a DuckDB table function, and the growing set of public kerchunk indexes (NASA, NOAA, Pangeo) becomes queryable as-is.
- The storage-transformer proposal. If Zarr standardizes manifests inside array metadata, the store here is where it plugs in, and duckdb-zarr would be an early reader.

## Sources

- duckdb-zarr issue 45 and the source at `46fd732` (`src/zarr_reader/`, `docs/design.md`).
- zarrs 0.23.10 `Cargo.toml` features and `src/array/codec/` module list.
- Kerchunk reference specification: https://fsspec.github.io/kerchunk/spec.html
- VirtualiZarr usage and data structures docs: https://virtualizarr.readthedocs.io/
- virtual-tiff README: https://github.com/virtual-zarr/virtual-tiff
- Chunk manifest proposal: https://github.com/zarr-developers/zarr-specs/issues/287
