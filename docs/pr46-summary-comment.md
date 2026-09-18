Pushed three commits addressing the review:

- `docs/virtual-zarr.md` now holds the manifest forms, codec table, checksum status and test layout. The README keeps a short section and a link, and the Status section lists features by group instead of phases. `docs/domains.md` has a remote sensing row for the virtual-tiff fixtures.
- `test/test_kerchunk_property.py` is a Hypothesis suite driven through the extension: random datasets, written as NetCDF4 and indexed by VirtualiZarr's `HDFParser`, must read back through `read_zarr(..., format='kerchunk')` equal to the dataset and equal to the same data in a real Zarr v2 store. `make test_kerchunk` runs 60 examples per property, `make test_kerchunk_deep` 600. Details of what it covers and what it does not are in the thread on `manifest_store.rs`.
- File access in `ManifestStore` is behind two traits, so the read loop, pooling and error paths are unit tested against an in-memory filesystem, and the unsafe code is down to two FFI adapters. Four new SQL cases run broken manifests through DuckDB's real filesystem.

On `format=`: the enum is `StoreFormat` in `meta.rs`, so Icechunk would be one more variant and one more `open_store` arm. The CI-side cost of the property suite is about 4 s at the default profile.

Also fixed the linux_amd64 CI failure, which was already failing on the previous head: that job generates fixtures inside the build container with uv, then runs `make test_release` on the host without uv, and the Makefile's pip fallback did not know about virtualizarr. The fallback list now includes the kerchunk fixture dependencies, and the fixture script imports them only when a kerchunk fixture actually has to be built.
