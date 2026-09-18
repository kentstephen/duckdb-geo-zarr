# Handoff: virtual Zarr (kerchunk manifests) in duckdb-zarr

## Status (2026-09-18, after the first review)

Alex (`alxmrs`) reviewed PR 46 on 2026-09-18 (one summary comment, six inline
threads, no approve or request-changes). Everything he asked for is done and
pushed: PR 46 now has seven commits.

```
405f0e5 CI: cache the kerchunk_errors fixtures like every other fixture
f95bfee CI: kerchunk fixture deps in the pip fallback, lazy VirtualiZarr imports
cc20d14 docs: move virtual Zarr details to docs/virtual-zarr.md, list features by group
8d466b1 Property-based tests: VirtualiZarr kerchunk manifests vs. the data they describe
0589289 manifest_store: put file access behind SourceFile/SourceOpener and test the error paths
55e7bec meta: link the zarrs fletcher32 issue
ca35cdd Read kerchunk JSON manifests (virtual Zarr) via format='kerchunk'
```

Verified locally: `cargo test --release` 31/31, `make lint` clean, all six SQL
suites pass including five new error cases, `make test_kerchunk` 2/2 at 60
examples, deep profile 600 examples per property with no failure. Exported to
`patches/duckdb-zarr/virtual-zarr/`.

CI: the linux_amd64 distribution job was failing on every push of this PR
(including the original head). Two causes, both fixed:

1. `No module named 'virtualizarr'` (f95bfee). The job generates fixtures
   inside the build container with uv, then runs `make test_release` on the
   host without uv, and the Makefile's pip fallback did not list virtualizarr.
   Fallback list extended; kerchunk imports made lazy.
2. `PermissionError ... kerchunk_errors/missing_file.json` (405f0e5). The
   container writes fixtures as root; kerchunk_errors was rebuilt every run,
   so the host could not overwrite it. Now cached like the other fixtures.

Both verified locally on the uv path and the pip fallback path. The run for
405f0e5 is in `action_required`: workflows from the fork need a maintainer
to click "Approve and run". Not verified green in CI yet. Once it is, post a
one-line follow-up comment mentioning the fixture caching fix.

Summary comment posted:
https://github.com/xqlsystems/duckdb-zarr/pull/46#issuecomment-5723922504

Review replies: the five inline replies are live on the PR (created as a
pending review, submitted at 01:22Z with an empty body, so the summary went
up as a separate comment; text in `docs/pr46-summary-comment.md`).

**Summary comment text**

> Pushed three commits addressing the review:
>
> - `docs/virtual-zarr.md` now holds the manifest forms, codec table, checksum status and test layout. The README keeps a short section and a link, and the Status section lists features by group instead of phases. `docs/domains.md` has a remote sensing row for the virtual-tiff fixtures.
> - `test/test_kerchunk_property.py` is a Hypothesis suite driven through the extension: random datasets, written as NetCDF4 and indexed by VirtualiZarr's `HDFParser`, must read back through `read_zarr(..., format='kerchunk')` equal to the dataset and equal to the same data in a real Zarr v2 store. `make test_kerchunk` runs 60 examples per property, `make test_kerchunk_deep` 600. Details of what it covers and what it does not are in the thread on `manifest_store.rs`.
> - File access in `ManifestStore` is behind two traits, so the read loop, pooling and error paths are unit tested against an in-memory filesystem, and the unsafe code is down to two FFI adapters. Four new SQL cases run broken manifests through DuckDB's real filesystem.
>
> On `format=`: the enum is `StoreFormat` in `meta.rs`, so Icechunk would be one more variant and one more `open_store` arm. The CI-side cost of the property suite is about 4 s at the default profile.
>
> Also fixed the linux_amd64 CI failure, which was already failing on the previous head: that job generates fixtures inside the build container with uv, then runs `make test_release` on the host without uv, and the Makefile's pip fallback did not know about virtualizarr. The fallback list now includes the kerchunk fixture dependencies, and the fixture script imports them only when a kerchunk fixture actually has to be built.

### What each review thread got

| Thread | Ask | Done |
| --- | --- | --- |
| README.md:51, kerchunk Parquet | Answered himself ("happy with that call") | Nothing to do. |
| README.md:74, geo paragraph | Move out of the README | Now in `docs/virtual-zarr.md` (manifest forms, codec table, checksum status, test layout, fixture table). README keeps four sentences and a link. `docs/domains.md` gains a remote sensing row. |
| README.md:83, Status section | Rewrite phases as feature groups | Six groups: table functions, Zarr formats, codecs, conventions, storage, selection. Phase history stays in `docs/design.md`. |
| manifest_store.rs:45, property tests | Hypothesis tests that execute the extension against VirtualiZarr's writer, and hunt | `test/test_kerchunk_property.py`, `make test_kerchunk` / `test_kerchunk_deep`. |
| manifest_store.rs:512, testing unsafe code | "Any ideas?" | `SourceFile` / `SourceOpener` traits; the unsafe code is now two FFI adapters with no logic. Nine unit tests on the read loop, pooling and errors with an in-memory opener; four SQL cases through DuckDB's real filesystem. |
| Summary: likes `format=`, room for Icechunk | none | Mention in the reply that the enum is `StoreFormat` in `meta.rs`. |

### What the property search covers, and what it does not

Covers: 1 to 3 dims, up to 6 per dim, nine numeric dtypes (int8..int64,
uint8..uint32, float32/64), NaN masking with and without an explicit
`_FillValue`, contiguous or chunked HDF5 layout with any subset of shuffle,
deflate (levels 1..4) and fletcher32, int64 or float64 coordinates, one or two
data variables. Each example compares the manifest read against the xarray
dataset itself and against a real Zarr v2 twin, and checks
`read_zarr_metadata` shape and chunk shape against the manifest's `.zarray`.

Does not cover (candidates for a follow-up, in rough value order): datetime64
coordinates and CF time units, string attributes with odd characters in
`.zattrs`, `scale_factor`/`add_offset` packed ints through the manifest,
boolean dtype, uint64, multi-file `open_virtual_mfdataset` concatenation,
VirtualiZarr's `ZarrParser` over a real Zarr store, manifests served over the
loopback HTTP server (would exercise short reads on the real HTTP filesystem),
and `dimension_separator='/'`.

Found by the search: nothing. 1200 examples, no failure. Two failures during
development were test bugs (a two-element `[path, offset]` reference the
parser rejects by design, and `read_zarr_metadata` returning `shape` as a JSON
string).

Found by the SQL error cases: a truncated chunk reference surfaced only as
zarrs' bare "unexpected end of file". The scan now wraps chunk decode errors
as `reading chunk [0, 0, 0] of array 'temperature': ...`. That applies to
every store, not only manifests.

### Replies (saved as a pending review on the PR; kept here for reference)

**Summary comment on the PR (superseded by the version above)**

> Pushed three commits addressing the review:
>
> - `docs/virtual-zarr.md` now holds the manifest forms, codec table, checksum status and test layout. The README keeps a short section and a link, and the Status section lists features by group instead of phases. `docs/domains.md` has a remote sensing row for the virtual-tiff fixtures.
> - `test/test_kerchunk_property.py` is a Hypothesis suite driven through the extension: random datasets, written as NetCDF4 and indexed by VirtualiZarr's `HDFParser`, must read back through `read_zarr(..., format='kerchunk')` equal to the dataset and equal to the same data in a real Zarr v2 store. `make test_kerchunk` runs 60 examples per property, `make test_kerchunk_deep` 600. Details of what it covers and what it does not in the thread on `manifest_store.rs`.
> - File access in `ManifestStore` is behind two traits, so the read loop, pooling and error paths are unit tested against an in-memory filesystem, and the unsafe code is down to two FFI adapters. Four new SQL cases run broken manifests through DuckDB's real filesystem.
>
> On `format=`: the enum is `StoreFormat` in `meta.rs`, so Icechunk would be one more variant and one more `open_store` arm. The CI-side cost of the property suite is about 4 s at the default profile.

**README.md:74 (geo paragraph)**

> Moved to `docs/virtual-zarr.md`, with the codec table and the fletcher32 status. The README keeps the four-sentence intro and the SQL examples.

**README.md:83 (Status section)**

> Rewritten as six feature groups (table functions, Zarr formats, codecs, conventions, storage, selection). The phase history is still in `docs/design.md`. If you would rather keep a version history in the README as well, say so and I will add it back under the groups.

**manifest_store.rs:45 (property tests)**

> Added `test/test_kerchunk_property.py`. Each example generates an xarray Dataset (1 to 3 dims, up to 6 per dim, nine numeric dtypes, NaN masking with and without an explicit `_FillValue`, contiguous or chunked HDF5 layout with any subset of shuffle/deflate/fletcher32, int or float coords, one or two variables), writes it as NetCDF4, indexes it with VirtualiZarr's `HDFParser` to kerchunk JSON, and asserts through the loaded extension that `read_zarr(manifest, format='kerchunk')` equals the dataset and equals the same data written as Zarr v2. A second property checks `read_zarr_metadata` against the manifest's `.zarray` documents.
>
> Profiles: `ci` 20 examples, `default` 60, `deep` 600, selected with `HYPOTHESIS_PROFILE` or `make test_kerchunk` / `make test_kerchunk_deep`.
>
> Hunt results so far: 1200 examples at the deep profile, no failure in the reader. The search did not cover datetime coordinates, string attributes, packed ints, bool/uint64, multi-file concatenation, `ZarrParser` over a real Zarr store, or manifests over HTTP. I would add those in a follow-up rather than grow this PR further, unless you want any of them here.

**manifest_store.rs:512 (unsafe methods)**

> The approach I took: move every branch out of the unsafe functions. `SourceFile` (size, seek, read with the C API's negative/zero/positive contract) and `SourceOpener` (open, `None` if it cannot) are the whole surface the store needs. `DuckDbFile` and `DuckDbOpener` implement them over FFI and contain no logic beyond mapping status codes, so there is nothing left in the `unsafe` blocks to get wrong that the compiler or a test could catch.
>
> Everything else (the short-read loop, EOF mid-read, failed seek, failed read, missing file, range clamping, whole-file references, the pool cap, manifest open and parse errors) is unit tested against `MemoryOpener`, which can cap bytes per read and force each failure. Nine tests, no DuckDB in the loop.
>
> The FFI adapters themselves are covered end to end by the SQL suite: four new `kerchunk_errors/*.json` fixtures (missing file, range past EOF, offset beyond EOF, truncated chunk) run through DuckDB's real filesystem and must fail with an error naming the file. The truncated case turned up that zarrs' decode error did not say which chunk, so the scan now wraps it with the array name and chunk indices.
>
> One more layer would be a fault-injecting HTTP server in the pytest suite (truncate mid-scan, return 500s) to hit the HTTP filesystem's short reads for real. Happy to add that if you think it is worth the CI time.

**README.md:51 (Parquet)**

> No reply needed, or a one-line "Right, JSON only for now; Parquet is in the follow-ups list."

## Original plan (kept for reference)

Goal: implement kerchunk JSON manifest reading in duckdb-zarr for [issue 45](https://github.com/xqlsystems/duckdb-zarr/issues/45) and open a PR upstream. David reviews the PR. The design is in `docs/virtual-zarr-duckdb-zarr.md` (upstream-framed, paste-able into the PR) and `docs/virtual-zarr-report.md` (same study with this repo's context). Read section 4 (design), 5 (codecs) and 8 (first PR shape) of the upstream doc before touching code.

## Scope of PR 1

1. `ManifestStore`: a `ReadableStorageTraits` impl that serves metadata and inline keys from a parsed kerchunk JSON document and chunk keys as byte ranges from the referenced files through DuckDB's file API.
2. `read_zarr('refs.json', format='kerchunk')` wiring, plus `read_zarr_metadata` and `read_zarr_groups` on the same path.
3. Enable zarrs features `zlib` and `fletcher32` (and `bz2` if cheap) in `Cargo.toml`.
4. A NetCDF4 fixture generated by VirtualiZarr in `scripts/generate_fixtures.py`, and SQL tests asserting the manifest read equals the same data written as real Zarr.

Out of scope for PR 1: kerchunk Parquet, `gen`/`templates`, Icechunk, TIFF codecs, manifest-as-table. Each is a follow-up in the report's effort table.

## Where to work

- Repo: `vendor/duckdb-zarr` (gitignored here, so the branch is the only record). Remote `origin` is upstream `xqlsystems/duckdb-zarr`. No fork exists under `kentstephen` yet. First step: `gh repo fork xqlsystems/duckdb-zarr --remote=true` from inside `vendor/duckdb-zarr`, which adds a `fork` remote (check the name with `git remote -v`).
- Branch off upstream `main` (`885f8dd`, two housekeeping commits past `46fd732`), not `wasm-attempt`. The wasm and `ranges=` work stays separate. `git checkout -b virtual-zarr origin/main`.
- State to clear first: `wasm-attempt` has an uncommitted change in `src/zarr_reader/meta.rs` (probing sibling coordinate arrays when the array list is empty, 6 lines) and an untracked `zarr` directory. Commit the meta.rs change on `wasm-attempt` before switching (`git commit -am "meta: probe sibling coord arrays when the store has no listing"`), and leave `zarr/` alone or add it to `.git/info/exclude`.
- Toolchain: brew rustup on PATH via `/opt/homebrew/opt/rustup/bin`. If `configure/platform.txt` says `wasm_mvp` from an earlier wasm build, `rm configure/platform.txt && make configure` before native builds.

## Code map (upstream `main`)

- `src/zarr_reader/duckdb_store.rs`: `DuckDbStore`, the DuckDB file API store. `get_partial_many` opens, seeks, reads with a short-read loop, closes per call. Reuse its open/seek/read code in `ManifestStore`, but keep handles open across calls.
- `src/zarr_reader/consolidated_store.rs`: `ConsolidatedCacheStore`, `HashMap<StoreKey, Bytes>` in front of an inner store. Its `get_partial_many` range clamping and `is_metadata_key` are exactly what the metadata half of `ManifestStore` needs. Either generalize it or copy the pattern. Its unit tests (`PanicStore`, `CountingStore`) are the model for testing the new store without I/O.
- `src/zarr_reader/meta.rs`: `open_store` (around line 69) picks the store by scheme; `with_consolidated_cache` and `build_consolidated_cache` (around 117 and 145) build the metadata map; `list_array_names_remote` and `list_array_names_zmetadata` (around 274 and 317) enumerate arrays from consolidated metadata, which a kerchunk manifest already is; `open_array` at 337 is `Array::open`. `extract_file_system` at 33 captures the `duckdb_file_system` from bind.
- `src/zarr_reader/types.rs`: `ZarrStore` alias, `ZarrArray`, dtype enums.
- `src/read_zarr.rs`: bind reads named parameters (find where `array_path` is parsed and add `format`), scan calls `retrieve_chunk` at about line 414.
- `src/read_zarr_metadata.rs`, `src/read_zarr_groups.rs`: share `open_store`, so they get the manifest path once `open_store` knows about it.
- `Cargo.toml`: zarrs feature list at line 27. Add `"zlib"`, `"fletcher32"`. zarrs 0.23.10 has `bytes_to_bytes/{zlib,shuffle,fletcher32,bz2}` and `array_to_array/fixedscaleoffset`; shuffle and fixedscaleoffset need no flag.
- `docs/design.md`: storage backends section around line 343 says a DuckDB-backed store is "a few hundred lines, not a fork". Cite it in the PR.

## `ManifestStore` sketch

```rust
pub enum ChunkRef { Range { path: String, offset: u64, length: Option<u64> }, Inline(Bytes) }
pub struct ManifestStore {
    file_system: duckdb_file_system,
    metadata: HashMap<StoreKey, Bytes>,   // .zgroup/.zarray/.zattrs and inline values
    chunks: HashMap<StoreKey, ChunkRef>,
    handles: Mutex<LruCache<String, (duckdb_file_handle, u64 /*size*/)>>,
}
```

- Parse: `serde_json::Value`. Version 0 is a flat map; version 1 has `refs` (use it) and `templates`/`gen` (return an error naming the feature). String value: plain text, or `base64:` prefix decoded. Array value: `[url]` or `[url, offset, length]`.
- `get_partial_many`: metadata or inline key returns clamped slices (copy the clamping from `ConsolidatedCacheStore`, including the past-end test). Range key: get or open the handle, seek to `offset + range.start(len)`, read `range.length(len)` with the short-read loop. Absent key returns `Ok(None)`.
- `size_key`: inline length, `length`, or file size for whole-file refs.
- `supports_get_partial`: true.
- Send/Sync: same `unsafe impl` as `DuckDbStore`, with the handle cache behind a `Mutex`. Read the comment there about DuckDB's internal locking. If the parallel scan opens one handle per thread cheaply, a per-thread cache is simpler than a shared LRU; measure before choosing.
- Do not wrap in `ConsolidatedCacheStore`; the manifest already is one. `with_consolidated_cache` should short-circuit for it.

## Fixture and tests

- Add `virtualizarr` (and `kerchunk` only if VirtualiZarr's kerchunk writer needs it; check) to `vendor/duckdb-zarr/pyproject.toml`. `h5netcdf`, `h5py`, `xarray`, `zarr` are already there.
- In `scripts/generate_fixtures.py`, follow `write_zarr` and the v2 gzip fixtures near line 555: take one of the existing tutorial datasets, write it as NetCDF4 with `encoding={var: {"zlib": True, "shuffle": True, "complevel": 1}}` via `h5netcdf`, then `virtualizarr.open_virtual_dataset(path)` and `.virtualize.to_kerchunk("...refs.json", format="json")`. Write the same dataset as real Zarr v2 beside it. Fixture paths must be absolute or relative to the store, so write the manifest with paths relative to `test/fixtures/` and confirm how DuckDB resolves them from the test working directory.
- Add a second variant with `fletcher32=True` in the encoding, and one variable with a `_FillValue`, to cover the two feature flags and the missing-chunk path.
- SQL test `test/sql/read_zarr_kerchunk.test`, modelled on `read_zarr_v2.test`: `read_zarr('refs.json', format='kerchunk')` `EXCEPT` `read_zarr('same.zarr')` in both directions is empty; `read_zarr_metadata` lists the same arrays; a `WHERE` on a coordinate still works.
- Rust unit tests in the store file: parse each ref form, absent key is `None`, base64 decode, `gen` rejected, past-end range on inline value does not panic.

## Build and test commands

```sh
cd vendor/duckdb-zarr
make configure                      # once, or after a wasm build
make release                        # make test_release does not rebuild
make test_release                   # generate_fixtures + SQL suite
cargo test --release                # Rust unit tests
make lint                           # fmt-check + clippy, CI runs both
uv run scripts/generate_fixtures.py # fixtures alone
```

Manual check against a public kerchunk index once the fixture passes: pick any NASA or NOAA kerchunk JSON on S3 (anonymous), `SET s3_region` and `CREATE SECRET` per DuckDB docs, `SELECT * FROM read_zarr('s3://.../refs.json', format='kerchunk') LIMIT 5`.

## Decisions to confirm with David before or in the PR

- `format='kerchunk'` on `read_zarr` versus sniffing `.json`, versus a separate `read_virtual_zarr`. The report recommends the explicit argument. Ask on the issue or in the PR description.
- Whether `ManifestStore` replaces `ConsolidatedCacheStore` internals or sits beside it.
- Handle cache policy: shared LRU with a cap, or per-thread handles.
- Whether `bz2` goes in now. It is one more C dependency (`bzip2` crate) on the mingw target.

## PR description outline

Link issue 45. Two paragraphs from the report's summary. The codec table from section 5 trimmed to the HDF5 rows. Test evidence: unit count, SQL suite, one public-manifest query with timing. Follow-ups listed with the effort table. Mention the storage-backends line in `docs/design.md`.

## Known unknowns (from the report, section 7)

- zarrs v2 dtype acceptance for HDF parser output (`|O`, compound). Will show up on the first real NetCDF.
- Handle cost across a scan on DuckDB's HTTP filesystem.
- Secrets across many referenced files.
- `dimension_separator` of `/` in VirtualiZarr output.
