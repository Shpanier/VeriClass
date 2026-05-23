from backend import db, exercises


def assign(exercise_id: str) -> str:
    """Round-robin: assign the variant with the fewest open sessions so far."""
    all_variants = [v["id"] for v in exercises.variants(exercise_id)]
    with db.conn() as c:
        rows = c.execute(
            "SELECT variant, COUNT(*) AS n FROM sessions "
            "WHERE exercise = ? GROUP BY variant",
            (exercise_id,),
        ).fetchall()
    counts = {v: 0 for v in all_variants}
    for r in rows:
        if r["variant"] in counts:
            counts[r["variant"]] = r["n"]
    return min(counts, key=lambda v: (counts[v], all_variants.index(v)))
