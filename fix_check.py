"""
Kontrollerar vad vi faktiskt har för odds/spelprocent i databasen.
python fix_check.py
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).parent / "v85.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

print("=== ODDS OCH SPELPROCENT (10 hästar från senaste omgång) ===")
rows = conn.execute("""
    SELECT h.startnr, h.namn, h.odds, h.spelprocent, h.v85_vinnare, l.v85_leg
    FROM hastar h JOIN lopp l ON h.lopp_id=l.id
    JOIN omgangar o ON l.omgang_id=o.id
    WHERE o.datum = (SELECT MAX(datum) FROM omgangar)
    AND l.v85_leg = 1
    ORDER BY h.startnr
    LIMIT 15
""").fetchall()

print(f"Lopp 1, senaste omgång:")
for r in rows:
    print(f"  Nr {r['startnr']:<3} {r['namn']:<25} odds={r['odds']} spelpct={r['spelprocent']} vann={r['v85_vinnare']}")

# Kolla hur många hästar som har odds vs inte
tot = conn.execute("SELECT COUNT(*) FROM hastar").fetchone()[0]
med_odds = conn.execute("SELECT COUNT(*) FROM hastar WHERE odds IS NOT NULL AND odds > 0").fetchone()[0]
med_sp = conn.execute("SELECT COUNT(*) FROM hastar WHERE spelprocent IS NOT NULL").fetchone()[0]
print(f"\nTotalt hästar: {tot}")
print(f"Med odds: {med_odds} ({100*med_odds//tot if tot else 0}%)")
print(f"Med spelprocent: {med_sp} ({100*med_sp//tot if tot else 0}%)")
conn.close()
