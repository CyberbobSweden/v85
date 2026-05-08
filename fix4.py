"""
fix4.py — Extraherar ATG:s V85-ranking (reserveOrder) ur raw_json
och sparar som v85_rank per häst. Kör med: python fix4.py
"""
import sqlite3, json
from pathlib import Path

DB = Path(__file__).parent / "v85.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# Lägg till kolumn om den saknas
cols = {r[1] for r in conn.execute("PRAGMA table_info(hastar)")}
if "v85_rank" not in cols:
    conn.execute("ALTER TABLE hastar ADD COLUMN v85_rank INTEGER")
    print("✓ Lade till kolumn v85_rank")
conn.commit()

# Gå igenom alla omgångar och extrahera reserveOrder
omgangar = conn.execute(
    "SELECT id, raw_json FROM omgangar WHERE raw_json IS NOT NULL"
).fetchall()

print(f"Behandlar {len(omgangar)} omgångar...")
uppdaterade_hastar = 0

for omg in omgangar:
    gid = omg["id"]
    try:
        game = json.loads(omg["raw_json"])
    except:
        continue

    for race in game.get("races", []):
        rid = race.get("id")
        if not rid:
            continue

        # Hämta reserveOrder från V85-pool
        v85_pool = race.get("pools", {}).get("V85", {})
        result   = v85_pool.get("result", {})
        reserve_order = result.get("reserveOrder", [])

        if not reserve_order:
            continue

        # reserveOrder = [7, 1, 9, 2, ...] = häst nr 7 är rank 1, nr 1 är rank 2 osv
        rank_map = {horse_nr: rank for rank, horse_nr in enumerate(reserve_order, 1)}

        for horse_nr, rank in rank_map.items():
            rows_updated = conn.execute("""
                UPDATE hastar SET v85_rank=?
                WHERE lopp_id=? AND startnr=?
            """, (rank, rid, horse_nr)).rowcount
            uppdaterade_hastar += rows_updated

conn.commit()

# Visa exempel
print(f"\n✓ Uppdaterade {uppdaterade_hastar} hästar med v85_rank")
print("\nKontroll — Lopp 1, senaste omgång (sorterat på v85_rank):")
rows = conn.execute("""
    SELECT h.startnr, h.namn, h.v85_rank, h.v85_vinnare
    FROM hastar h JOIN lopp l ON h.lopp_id=l.id
    JOIN omgangar o ON l.omgang_id=o.id
    WHERE o.datum=(SELECT MAX(datum) FROM omgangar) AND l.v85_leg=1
    ORDER BY h.v85_rank
    LIMIT 10
""").fetchall()
for r in rows:
    print(f"  Rank {r['v85_rank']:<3} Nr {r['startnr']:<3} {r['namn']:<25} {'★ VANN' if r['v85_vinnare'] else ''}")

conn.close()
print("\n✓ Klar! Starta om app.py.")
