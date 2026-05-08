"""
fix2.py — Lägger till v85_leg (1-8) på varje lopp baserat på ordning inom omgången.
Kör med: python fix2.py
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent / "v85.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# Lägg till kolumn om den saknas
cols = {r[1] for r in conn.execute("PRAGMA table_info(lopp)")}
if "v85_leg" not in cols:
    conn.execute("ALTER TABLE lopp ADD COLUMN v85_leg INTEGER")
    print("Lade till kolumn v85_leg")

# Sätt v85_leg = rang inom omgången sorterat på nummer
omgangar = conn.execute("SELECT id FROM omgangar").fetchall()
for omg in omgangar:
    oid = omg["id"]
    lopp = conn.execute(
        "SELECT id FROM lopp WHERE omgang_id=? ORDER BY nummer", (oid,)
    ).fetchall()
    for leg, l in enumerate(lopp, 1):
        conn.execute("UPDATE lopp SET v85_leg=? WHERE id=?", (leg, l["id"]))

conn.commit()

# Verifiera
sample = conn.execute("""
    SELECT o.datum, o.bana, l.nummer, l.v85_leg 
    FROM lopp l JOIN omgangar o ON l.omgang_id=o.id
    ORDER BY o.datum DESC, l.nummer LIMIT 16
""").fetchall()
print("\nKontroll (datum, bana, lopp_nr, v85_leg):")
for r in sample:
    print(f"  {r['datum']} {r['bana']:<14} lopp {r['nummer']} → V85-leg {r['v85_leg']}")

conn.close()
print("\n✓ Klar! Starta om app.py.")
