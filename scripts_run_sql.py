"""Run a .sql file statement by statement and report OK/FAIL per statement.
Usage: uv run scripts_run_sql.py sql/00_repo_examples.sql
"""
import sys, time, duckdb
con = duckdb.connect()
con.execute("INSTALL zarr FROM community; INSTALL h3 FROM community; INSTALL spatial; LOAD zarr; LOAD h3; LOAD spatial;")
src = open(sys.argv[1]).read()
for s in src.split(';'):
    lines = [l for l in s.strip().splitlines()]
    comments = [l for l in lines if l.strip().startswith('--')]
    body = '\n'.join(l for l in lines if not l.strip().startswith('--')).strip()
    if not body:
        continue
    label = comments[-1].strip() if comments else body[:60]
    t = time.time()
    try:
        rows = con.sql(body).fetchall()
        print(f"OK   {label}  ({len(rows)} rows, {time.time()-t:.1f}s)")
        if '-v' in sys.argv:
            print(con.sql(body))
    except Exception as e:
        print(f"FAIL {label}\n     {type(e).__name__}: {str(e).splitlines()[0]}")
