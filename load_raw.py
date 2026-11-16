"""Land the raw feeds in the warehouse bronze schema (the local stand-in for COPY INTO from object storage).

Bronze is append-only and untouched: every row keeps the `_loaded_at` the source delivered it with, so
silver can deduplicate and pick the latest version deterministically. The answer key goes to a separate
`truth` schema that only tests and the evaluation read.
"""
import argparse
from pathlib import Path

import duckdb


def load(db: str, data: str = "data") -> None:
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(db)
    for schema, folder in (("bronze", "landing"), ("truth", "truth")):
        con.execute(f"create schema if not exists {schema}")
        for f in sorted(Path(data, folder).glob("*.parquet")):
            con.execute(f"create or replace table {schema}.{f.stem} as select * from read_parquet('{f.as_posix()}')")
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="warehouse/dev.duckdb")
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    load(a.db, a.data)
