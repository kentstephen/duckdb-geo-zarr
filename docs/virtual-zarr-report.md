# Virtual Zarr in duckdb-zarr: feasibility report

Date: 2026-09-17. Context: [xqlsystems/duckdb-zarr#45](https://github.com/xqlsystems/duckdb-zarr/issues/45) ("Virtual Zarr support for non-Zarr array formats"), opened by d33bs after a Discord discussion. The question: how much work is it for `duckdb-zarr` to read TIFF, HDF5 and NetCDF files through VirtualiZarr-style chunk manifests, without converting the data.

Findings are based on the vendored extension at `wasm-attempt` (`e9945b7`, on top of upstream `46fd732`), zarrs 0.23.10 as resolved in its `Cargo.lock`, the kerchunk reference spec, the VirtualiZarr docs, and the virtual-tiff README.

## 1. Summary

- The manifest layer is small. A virtual Zarr is metadata plus a map from chunk key to (path, offset, length). `duckdb-zarr` already routes every read through a custom zarrs store with byte-range reads and already serves metadata from an in-memory cache. A manifest-backed store is the same shape: a few hundred lines of Rust in the store layer, no change to scanning, dimension inference, `ranges=` pruning or the wasm build.
- The codec layer is where the effort is. Chunks decode with whatever compressor the source file used. HDF5/NetCDF4 sources (zlib, shuffle, fletcher32) are covered by zarrs behind feature flags that are currently off. TIFF sources need codecs zarrs does not have (LZW, JPEG, WebP, LZMA, Lerc, predictor). Each is a separate plugin.
- The manifest format decides reach. Kerchunk JSON is a single file and works in the browser. Kerchunk Parquet is a directory of Parquet tables, which DuckDB can read natively. Icechunk is the only format virtual-tiff writes today, and its Rust crate is not viable for the wasm build (tokio, reqwest, object_store, opentelemetry).
- Rough effort: NetCDF/HDF5 over kerchunk JSON in days. Deflate TIFF for free once that exists. LZW and predictor a few days each in pure Rust. JPEG/WebP/Lerc weeks, with CI risk on every DuckDB target. Icechunk out until the crate slims down or a lighter reader exists.

## 2. What a virtual Zarr is

VirtualiZarr's in-memory model is a `ChunkManifest`: three arrays (paths, offsets, lengths) indexed by chunk key. A `ManifestArray` pairs one manifest with the ordinary Zarr array metadata (shape, dtype, chunks, codecs, fill value, attrs). A chunk is virtual (points into an external file), missing (empty path, decoded as fill value) or inlined (raw bytes carried in the manifest). Nothing in the model is specific to the source format: an HDF5 dataset chunk, a TIFF tile and a NetCDF3 record all become (path, offset, length).

VirtualiZarr persists this three ways:

| Format | Layout | Notes |
|---|---|---|
| Kerchunk JSON | one `.json` file: `version`, `templates`, `gen`, `refs` | Zarr v2 keys (`.zgroup`, `.zarray`, `.zattrs`, `var/0.0.1`). Ref values are an inline string, a `base64:` string, `[url]` (whole file) or `[url, offset, length]`. |
| Kerchunk Parquet | directory: `.zmetadata` plus `var/refs.N.parq` | Columns `path`, `offset`, `size`, `raw`. `record_size` refs per file (default 10,000). `.zmetadata` holds all Zarr metadata. |
| Icechunk | Icechunk repo with virtual chunk refs | Zarr v3 model. Binary manifests, transactional. Needs the `icechunk` crate to read. |

Parsers exist for HDF5/NetCDF4, NetCDF3, FITS, TIFF (virtual-tiff) and existing kerchunk refs. virtual-tiff persists only to Icechunk today, so TIFF manifests reach a kerchunk target only via a Python round trip (`open_virtual_dataset` then `to_kerchunk`).

A separate, older proposal (zarr-specs issue 287, February 2024) defines a chunk manifest as a Zarr v3 storage transformer stored next to the array. It did not land in the spec and zarrs does not implement it. It is worth knowing about because a manifest-backed store in `duckdb-zarr` would be the natural place to honor it if it ever does.

## 3. How duckdb-zarr reads today

Reading is layered as:

1. `open_store` builds a `ZarrStore`, an `Arc<dyn ReadableStorageTraits>`. Native builds use `zarrs_http` or the filesystem store; wasm builds and any DuckDB-managed path use `DuckDbStore` (`src/zarr_reader/duckdb_store.rs`), which implements `get_partial_many` (byte ranges) and `size_key` over DuckDB's file API (`duckdb_file_system_open`, `seek`, `read`). This is how S3, GCS, Azure and duckdb-wasm's HTTP filesystem come for free, credentials included.
2. `ConsolidatedCacheStore` wraps the store and serves metadata keys (`zarr.json`, `.zarray`, `.zattrs`, `.zgroup`, `.zmetadata`) from a `HashMap<StoreKey, Bytes>` built from consolidated metadata, so `Array::open` costs zero round trips. Non-metadata keys pass through to the inner store.
3. `Array::open` (zarrs) parses metadata, v2 or v3, and `retrieve_chunk` decodes one chunk through the codec chain. Missing chunks become fill value.
4. Everything above (dimension groups, coordinate loading, `ranges=` pruning, row emission) sees only arrays and chunk indices.

The key observation: layer 2 is already half of a manifest store. It maps keys to bytes from a parsed document. A virtual store only adds the other half, mapping chunk keys to byte ranges in other files.

## 4. Design: a manifest-backed store

### 4.1 `ManifestStore`

A new `ReadableStorageTraits` implementation:

- Construction: read the manifest document through the DuckDB file API (so the manifest itself can live on S3 or behind the wasm proxy), parse it into `metadata: HashMap<StoreKey, Bytes>` and `chunks: HashMap<StoreKey, ChunkRef>` where `ChunkRef` is `{ path: String, offset: u64, length: Option<u64> }` or `Inline(Bytes)`.
- `get_partial_many(key, ranges)`: metadata or inline key returns slices of the cached bytes (same range clamping as `ConsolidatedCacheStore` already does). Chunk key opens `path`, seeks to `offset + range.start`, reads. Unknown key returns `None`, which zarrs turns into fill value.
- `size_key`: `length` for chunk refs, byte length for cached values, file size when `length` is absent (whole-file refs).
- Handle cache: one NetCDF file backs thousands of chunks, and DuckDB's open is not free (a remote open is at least a HEAD). Keep an LRU of open `duckdb_file_handle`s keyed by path. The current `DuckDbStore` opens and closes per call; that is fine for a real Zarr where every chunk is a distinct object, and wrong here.
- Path resolution: kerchunk paths are absolute URLs or paths as written by the producer. Pass them through DuckDB unchanged, so `s3://`, `gs://`, `https://` and local paths all work and the secrets manager applies. On wasm, remote paths need the same proxy rewrite the ERA5 pages use; a `remap=` argument or a `SET zarr_path_rewrite` would cover it.

`ConsolidatedCacheStore` and `ManifestStore` share the metadata half. Either fold the manifest into the cache store (a `chunks` map that is empty for real Zarr) or extract the cached-metadata behaviour into a helper both use.

### 4.2 Wiring

`read_zarr('refs.json')` can detect a manifest by extension or by a `version`/`refs` top-level key after one read, and `read_zarr_metadata` / `read_zarr_groups` work unchanged because array listing already prefers consolidated metadata, and a manifest is fully consolidated by construction. Explicit `format='kerchunk'` avoids probing cost on remote paths.

Zarr v2 keys from kerchunk (`var/0.0.1` with `.` separators) are already handled: zarrs's v2 chunk key encoding produces the same keys the store is asked for.

### 4.3 Kerchunk JSON details that need handling

- `version: 1` `templates` and `gen`: jinja-style `{{name}}` substitution and cartesian key generation. VirtualiZarr does not emit these, kerchunk's own combiners do. Support `refs` first and reject `gen` with a clear error; add a minimal template substituter later if real files need it.
- `base64:` inline chunks: decode at parse time (base64 crate is already a dependency).
- Plain-string inline values: metadata, and small coordinate arrays, which is common.
- `[url]` without offset/length: whole file. `size_key` must stat the file.
- Manifests are one JSON document. A large one (millions of chunks) is a memory and parse-time concern; this is exactly why kerchunk Parquet exists.

### 4.4 Kerchunk Parquet

Two ways to go:

- Inside the store: read `.zmetadata` for metadata and, on first touch of an array, read its `refs.N.parq` files. That means a Parquet reader in the Rust extension, or calling back into DuckDB to run `read_parquet` through the C API, which the extension does not do today.
- As a DuckDB table: `read_zarr` (or a new `read_virtual_zarr`) takes the manifest as a relation, `(key VARCHAR, path VARCHAR, offset BIGINT, size BIGINT, raw BLOB)`. The user builds it with `read_parquet('refs/**/*.parq')` or from any other table. This turns the manifest into ordinary SQL data: filterable, joinable, materializable, and it lets someone generate a manifest for a set of COGs in SQL without VirtualiZarr. Table-valued input to a table function is awkward in the C API (no direct relation argument), so this likely means a two-step: `CREATE TABLE refs AS ...` then `read_zarr(manifest_table='refs')` with the extension querying it through `duckdb_query`.

The second is the more interesting direction for a DuckDB extension specifically and is not available to any other Zarr reader.

### 4.5 Icechunk

Reading virtual refs out of Icechunk means the `icechunk` crate, which pulls tokio, reqwest, object_store and opentelemetry. The README already rules it out for wasm, and it would roughly double native build complexity. Two mitigations, both outside this extension: ask VirtualiZarr users to `to_kerchunk` as well, or wait for a lightweight Icechunk manifest reader. Not in scope for a first version.

## 5. Codecs

The manifest gives bytes; zarrs must then decode them with the codec chain the producer wrote into `.zarray`. Coverage in zarrs 0.23.10, checked against its `Cargo.toml` features and `src/array/codec/`:

| Codec (v2 numcodecs id) | Typical source | zarrs status | In `duckdb-zarr` build |
|---|---|---|---|
| `zlib` | HDF5/NetCDF4 deflate, TIFF Deflate | `zlib` feature | off, add feature |
| `shuffle` | HDF5 shuffle filter | always on (`bytes_to_bytes/shuffle`) | yes |
| `fletcher32` | HDF5 checksum filter | `fletcher32` feature | off, add feature |
| `fixedscaleoffset` | HDF5 scale-offset filter | always on | yes |
| `bz2` | rare HDF5 | `bz2` feature | off, add feature |
| `gzip`, `zstd`, `blosc` | native Zarr | on | yes |
| `delta` | some kerchunk outputs | not in zarrs | plugin |
| LZW, predictor | GeoTIFF (very common) | not in zarrs | plugin, pure Rust, small |
| PackBits | GeoTIFF | zarrs has `packbits` but it is Zarr v3 bit-packing, not TIFF PackBits | plugin, small |
| JPEG, JPEGXL, WebP | aerial imagery COGs | not in zarrs | plugin with C or Rust decoder |
| LZMA | GeoTIFF | not in zarrs | plugin (`xz2` or `lzma-rs`) |
| Lerc, PNG | GeoTIFF | not in zarrs | plugin |
| szip | older HDF5 | not in zarrs, license issues | skip |

Consequences:

- NetCDF4/HDF5 as produced by VirtualiZarr's HDFParser is two feature flags away (`zlib`, `fletcher32`) plus the store.
- Deflate GeoTIFFs decode with `zlib` too, provided virtual-tiff writes the codec as numcodecs `zlib` and the predictor is none. With predictor 2 or 3 (horizontal or floating-point differencing), a predictor codec is needed; it is a few dozen lines.
- LZW is the common case for legacy COGs and is small to implement (the TIFF variant, MSB-first with early change). Worth doing early.
- JPEG-family and WebP are where the cost and CI risk sit: a C decoder must build on linux, macOS, windows_amd64_mingw and wasm32-emscripten, and the mingw target already forces `blosc` off. Pure-Rust decoders (`zune-jpeg`, `image-webp`) reduce that risk.
- Codec ids must match. virtual-tiff and VirtualiZarr write numcodecs-style names and configs; zarrs converts v2 `compressor`/`filters` to v3 codec names through `zarrs_metadata_ext`. Anything it does not recognize fails at `Array::open`, before any bytes are read, which is at least a clean failure mode.
- HDF5 also carries semantics outside the codec chain: `_FillValue` versus HDF5 fill, `scale_factor`/`add_offset` as attrs (already handled by the existing CF path or passed through as raw values), and datatypes zarrs's "v3-compatible subset of v2" excludes: compound types, variable-length strings (`|O` with `vlen-utf8` filter is supported through `vlen_v2`; arbitrary object dtypes are not), and enum types.

## 6. What works unchanged

- `ranges=['dim:lo:hi']` chunk pruning. It operates on coordinate values and chunk indices, so it never touches the store. It is more valuable here than for real Zarr: a pruned chunk means never opening the backing NetCDF or TIFF at all.
- Dimension inference, CF time units, auxiliary coordinates, bounds variables. Kerchunk carries `_ARRAY_DIMENSIONS` in `.zattrs`, which the v2 path already reads.
- wasm. Kerchunk JSON is a file, the DuckDB file API is already the wasm store, and the codecs listed as pure Rust compile there. The map page could point at a manifest over a stack of daily NetCDFs with no change to the SQL.
- `read_zarr_metadata` and `read_zarr_groups`, because a manifest is consolidated by construction.

## 7. Open questions and risks

- zarrs v2 metadata acceptance for HDF5-derived arrays: `dtype` strings like `<f4` are fine, `|S16` fixed strings should be fine, `|O` and compound are not. Needs a test against a real HDFParser output (a NOAA or CMIP6 NetCDF4 is the natural fixture).
- DuckDB file handle cost across a scan: how many handles can stay open, and whether duckdb-wasm's HTTP filesystem tolerates many concurrent range reads on one URL. The short-read loop in `DuckDbStore` was written for exactly that filesystem and carries over.
- Manifests referencing many files with per-file credentials: DuckDB secrets are scoped by path prefix, so this should just work, but is untested.
- Whole-file refs (`[url]` with no offset) on remote paths cost a stat per call; cache sizes with the handle.
- Chunk key encoding in kerchunk output for arrays with a `dimension_separator` of `/` (VirtualiZarr can write either). zarrs handles both v2 separators; the store must not assume `.`.
- Version 1 `gen` blocks: reject or implement. Reject first.
- Whether upstream wants a `format=` argument or extension sniffing. Ask on the issue.

## 8. Effort

| Piece | Scope | Estimate |
|---|---|---|
| `ManifestStore` for kerchunk JSON (`refs`, inline, base64, whole-file), handle cache, wiring, tests | store layer only | 2 to 4 days |
| Enable `zlib`, `fletcher32`, `bz2` features; NetCDF4 fixture; CI on all targets | Cargo, tests | 1 day, plus whatever mingw does |
| Kerchunk Parquet inside the store | Parquet reader in Rust, or C API callback | 2 to 3 days |
| Manifest as a DuckDB table (`manifest_table=`) | new argument, `duckdb_query` from bind | 3 to 5 days, design discussion first |
| TIFF: LZW, predictor, PackBits, LZMA codecs | pure Rust plugins | 1 to 3 days each |
| TIFF: JPEG, WebP, Lerc, PNG | plugins with external decoders, CI | 1 to 2 weeks each, uncertain |
| Icechunk virtual refs | `icechunk` crate | not viable for wasm; native only, large |
| Wasm proxy path rewrite for manifest paths | small argument | half a day |

A first PR that is worth showing upstream: kerchunk JSON store, `zlib` and `fletcher32` on, one NetCDF4 fixture generated by VirtualiZarr in `scripts/`, the SQL test being `read_zarr('fixture.json')` equal to `read_zarr` on the same data converted to real Zarr. That demonstrates the whole chain end to end and leaves TIFF codecs as independent follow-ups, each with a clear fixture (a Deflate COG, an LZW COG).

## 9. Directions this opens

Not recommendations, just where it could go:

- Manifests as SQL. Building a manifest for a directory of COGs is a scan of TIFF headers, which is a small amount of code, and the result is a table. DuckDB could produce, store, filter and hand back manifests without Python in the loop.
- Cross-format joins. A NetCDF climatology and a GeoTIFF land-cover raster as two `read_zarr` calls in one query, polyfilled to H3, joined on cell. That is the original goal of this repo with the conversion step removed.
- The browser map over archival data. The ERA5 page reads a real Zarr; the same page over a manifest of NetCDFs on Source Cooperative would need no conversion on the publisher's side.
- The storage-transformer proposal. If Zarr ever standardizes manifests inside the array metadata, the store here is where it plugs in, and `duckdb-zarr` would be an early reader.

## Sources

- duckdb-zarr issue 45 and the vendored source at `e9945b7` (`src/zarr_reader/`).
- zarrs 0.23.10 `Cargo.toml` features and `src/array/codec/` module list.
- Kerchunk reference specification: https://fsspec.github.io/kerchunk/spec.html
- VirtualiZarr usage and data structures docs: https://virtualizarr.readthedocs.io/
- virtual-tiff README: https://github.com/virtual-zarr/virtual-tiff
- Chunk manifest proposal: https://github.com/zarr-developers/zarr-specs/issues/287
