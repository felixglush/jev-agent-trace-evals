"""Evals as indexes: routed labels pivoted into one column per rubric.

`trace_labels` has one row per trace and one column per rubric, so a data
agent can filter traces with SQL before reading any of them. Only admitted
rubrics appear unless `include_unadmitted` is set, because a bad rubric
misleads search.
"""

from __future__ import annotations

import duckdb

from s1evals import analysis
from s1evals.rubrics import Rubric
from s1evals.store import Store


def routed_labels(store: Store, rubrics: dict[str, Rubric], run_id: str) -> dict[analysis.Key, str]:
    verdicts = [v for _, v in store.scores(run_id=run_id)]
    trace_ids = sorted({v.trace_id for v in verdicts})
    slices = {}
    for tid in trace_ids:
        for r in rubrics.values():
            s = store.get_slice(tid, r.id, r.version)
            if s is not None:
                slices[(tid, r.id)] = s
    return analysis.compute(rubrics, slices, verdicts).labels[analysis.ROUTED]


def query(
    store: Store, rubrics: dict[str, Rubric], sql: str, run_id: str | None = None, include_unadmitted: bool = False
) -> list[dict]:
    runs = store.run_ids()
    if run_id is None and not runs:
        raise ValueError("no scored runs yet")
    run_id = run_id or runs[-1]
    cols = sorted(r.id for r in rubrics.values() if include_unadmitted or r.admitted)
    labels = routed_labels(store, {rid: rubrics[rid] for rid in cols}, run_id)
    con = duckdb.connect()
    try:
        con.execute(f"ATTACH '{store.path}' AS s (READ_ONLY)")
        con.execute("CREATE TEMP TABLE routed(trace_id VARCHAR, rubric_id VARCHAR, label VARCHAR)")
        if labels:
            con.executemany("INSERT INTO routed VALUES (?, ?, ?)", [[t, r, lab] for (t, r), lab in labels.items()])
        pivots = ", ".join(f"MAX(label) FILTER (WHERE rubric_id = '{c}') AS \"{c}\"" for c in cols)
        con.execute(
            "CREATE TEMP VIEW trace_labels AS SELECT t.trace_id"
            + (f", {', '.join(f'l."{c}"' for c in cols)}" if cols else "")
            + " FROM s.traces t LEFT JOIN (SELECT trace_id"
            + (f", {pivots}" if cols else "")
            + " FROM routed GROUP BY trace_id) l USING (trace_id)"
        )
        con.execute("CREATE TEMP VIEW events AS SELECT * FROM s.events")
        con.execute("CREATE TEMP VIEW traces AS SELECT * FROM s.traces")
        con.execute("CREATE TEMP VIEW scores AS SELECT * FROM s.scores")
        cur = con.execute(sql)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]
    finally:
        con.close()
