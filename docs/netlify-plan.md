# Hosting the ERA5 pages on Netlify

Outcome (2026-08-29): deployed as https://duckdb-geo-zarr.netlify.app with plan A. The
rewrite passes `Range` and returns 206; `era5.html` and `map.html#selftest-daily` pass
against the live site with local-proxy timings. Plan B is kept below in case CDN caching
of chunks is wanted later.

## Why Netlify

`era5.html` and `map.html` read ARCO ERA5 from `gcp-public-data-arco-era5`, which
sends no CORS headers. On GitHub Pages there is no way to proxy, so those pages only run
behind `wasm/serve.py`. Netlify can proxy `/arco/*` to the bucket at the edge, so the
same pages work unchanged from a static host. The HRRR pages need nothing (Source
Cooperative sends CORS) and keep working on either host.

Both pages already build the store URL as `${location.origin}/arco/ar/...`, so no page
changes are needed for the proxy itself.

## Upstream facts (checked 2026-08-29)

- `2m_temperature/<t>.0.0` chunk: 1,333,118 bytes, `accept-ranges: bytes`, a
  `Range: bytes=0-1023` request returns 206 with `content-range`.
- `.zmetadata`: 30 KB. `cache-control: public, max-age=3600` on everything.
- `wasm/server.log`: one GET per chunk per page run, so the 16 KiB short-read loop in
  `DuckDbStore::get_partial_many` does not multiply HTTP requests.
- One day of one variable over a box = 3 chunks, about 4 MB.

## Layout

```
netlify.toml                      (repo root)
netlify/edge-functions/arco.ts    (only if plan B is needed)
wasm/www/                         publish dir, no build step
```

`netlify.toml`:

```toml
[build]
  publish = "wasm/www"

# Plan A: plain proxy rewrite. Same-origin, so no CORS anywhere.
[[redirects]]
  from = "/arco/*"
  to = "https://storage.googleapis.com/gcp-public-data-arco-era5/:splat"
  status = 200
  force = true

[[headers]]
  for = "/zarr.duckdb_extension.wasm"
  [headers.values]
    Cache-Control = "public, max-age=3600"
```

## Plan A: proxy rewrite

The rewrite forwards the request to GCS and streams the response back. What has to be
verified after the first deploy, since it decides whether A is enough:

1. `curl -sI -H "Range: bytes=0-1023" https://<site>.netlify.app/arco/ar/1959-2022-1h-360x181_equiangular_with_poles_conservative.zarr/2m_temperature/0.0.0`
   must return 206 with `content-range: bytes 0-1023/1333118`. If Netlify's proxy drops
   `Range` or answers 200 with the whole object, plan A fails (duckdb-wasm's HTTP
   filesystem depends on 206).
2. `BASE=https://<site>.netlify.app/ node run.mjs era5.html` from `wasm/` must print the
   same log as against `serve.py` (metadata 0.6 s, one-day box about 1.6 s plus
   whatever the Netlify hop adds).
3. Whether Netlify's CDN caches the proxied 206 responses. GCS sends `max-age=3600`;
   the browser cache handles repeat reads within a tab session either way.

## Plan B: edge function

If the rewrite mangles Range, or if shared edge caching of chunks is wanted (chunks are
immutable, so a long CDN TTL is safe and makes the second visitor's day fast), replace
the redirect with an edge function on the same path:

```ts
// netlify/edge-functions/arco.ts
const UP = "https://storage.googleapis.com/gcp-public-data-arco-era5";
export default async (req: Request) => {
  const path = new URL(req.url).pathname.slice("/arco".length);
  const h = new Headers();
  const range = req.headers.get("range");
  if (range) h.set("range", range);
  const res = await fetch(UP + path, { method: req.method, headers: h });
  const out = new Headers();
  for (const k of ["content-type", "content-length", "content-range", "accept-ranges", "etag", "last-modified"]) {
    const v = res.headers.get(k);
    if (v) out.set(k, v);
  }
  out.set("cache-control", "public, max-age=86400");
  out.set("netlify-cdn-cache-control", "public, max-age=31536000");
  out.set("netlify-vary", "header=range");
  return new Response(res.body, { status: res.status, headers: out });
};
export const config = { path: "/arco/*", cache: "manual" };
```

Costs: edge functions are per-invocation (free tier 1M/month); one invocation per chunk,
plus metadata and coordinate arrays. A day window is under 20 invocations.

## Bandwidth

Proxied bytes count against the site's bandwidth (free tier 100 GB/month). At 4 MB per
day-window that is about 25,000 day-windows a month. A user who pins a year (365 x 3
chunks, about 1.5 GB) is the case to keep in mind; `map.html`'s `winnote` already
tells the user how many chunks a window costs. CDN caching (plan B) turns repeat reads of
the same chunks into cache hits, which still count as bandwidth but not as GCS fetches.

## Deploy

1. Connect the GitHub repo in the Netlify UI (production branch `main`, publish dir and
   redirects from `netlify.toml`), or `npx netlify-cli deploy --prod --dir wasm/www`
   for a first manual deploy without linking.
2. Run the three checks above.
3. `BASE=https://<site>.netlify.app/ node run.mjs "map.html#selftest-var"` to confirm
   the HRRR pages are unaffected.

## Repo edits once it works

- `index.html`: link `era5.html` and `map.html`. (done)
- `map.html` title and `winnote` say "local proxy" / "the proxy caches chunks";
  reword to the hosted proxy.
- `wasm/README.md`, `README.md:57`, `HANDOFF.md`: replace "only work locally" with the
  Netlify URL and a sentence on the `/arco/` rewrite.
- `.github/workflows/pages.yml`: keep (HRRR on Pages still works) or drop in favour of one
  host. Two hosts means two URLs in the docs.
- `serve.py` stays as the local dev server; nothing in it changes.

## Later, not needed now

- `wasm_threads` build: Netlify `_headers` can set `Cross-Origin-Opener-Policy` and
  `Cross-Origin-Embedder-Policy`, which GitHub Pages cannot. Then jsDelivr and GCS
  responses would need `Cross-Origin-Resource-Policy` or `credentialless` COEP, which the
  proxy can add for `/arco/*`.
- A second proxied bucket (another ARCO resolution, or `gcp-public-data-arco-era5/co/`)
  is one more redirect line.
