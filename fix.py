"""
fix.py — Kör EN gång för att fixa databasen utan att radera data.
  python fix.py
"""
import sqlite3, requests, time, json
from pathlib import Path

DB = Path(__file__).parent / "v85.db"
BASE = "https://horse-betting-info.prod.c1.atg.cloud/api-public/v0"
H = {"Accept":"application/json","User-Agent":"Mozilla/5.0",
     "Origin":"https://www.atg.se","Referer":"https://www.atg.se/spel/V85"}

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# ── 1. Lägg till saknade kolumner om de inte finns ────────
cols = {r[1] for r in conn.execute("PRAGMA table_info(hastar)")}
print(f"Befintliga kolumner i hastar: {cols}")

for col, typ in [("odds","REAL"), ("spelprocent","REAL"), ("placering","INTEGER")]:
    if col not in cols:
        conn.execute(f"ALTER TABLE hastar ADD COLUMN {col} {typ}")
        print(f"  Lade till kolumn: {col}")

lopp_cols = {r[1] for r in conn.execute("PRAGMA table_info(lopp)")}
for col, typ in [("vinnare_namn","TEXT"), ("vinnare_kusk","TEXT")]:
    if col not in lopp_cols:
        conn.execute(f"ALTER TABLE lopp ADD COLUMN {col} {typ}")
        print(f"  Lade till lopp-kolumn: {col}")

omg_cols = {r[1] for r in conn.execute("PRAGMA table_info(omgangar)")}
for col, typ in [("utdelning_8","REAL"),("utdelning_7","REAL"),("utdelning_6","REAL"),
                 ("utdelning_5","REAL"),("vinnare_8","INTEGER"),("vinnare_7","INTEGER"),
                 ("vinnare_6","INTEGER"),("jackpot_5","INTEGER"),("system_count","INTEGER")]:
    if col not in omg_cols:
        conn.execute(f"ALTER TABLE omgangar ADD COLUMN {col} {typ}")
        print(f"  Lade till omgangar-kolumn: {col}")

conn.commit()
print("✓ Schemafix klar\n")

# ── 2. Hämta utdelning för alla via results-API ────────────
print("Hämtar utdelningsdata från ATG...")
r = requests.get(f"{BASE}/results/V85", headers=H, timeout=15)
results = r.json().get("gameResults", [])
print(f"  API returnerade {len(results)} omgångar med utdelning")

for res in results:
    gid = res["id"]
    omst = res.get("turnover", 0)
    omst_kr = omst / 100 if omst else None
    payouts = res.get("payouts", {})

    def payout(k):
        p = payouts.get(str(k), {})
        a = p.get("payout")
        return a / 100 if a else None

    def winners(k):
        return payouts.get(str(k), {}).get("systems")

    jackpot_5 = 1 if payouts.get("5", {}).get("jackpot") else 0

    # Uppdatera vinnare i lopp från results
    for race_res in res.get("races", []):
        rid = race_res.get("id")
        for w in race_res.get("winners", []):
            conn.execute("""
                UPDATE lopp SET vinnare_namn=?, vinnare_kusk=?, vinnare_nr=?
                WHERE id=?
            """, (w.get("horseName"), w.get("driverName"), w.get("startNumber"), rid))

    conn.execute("""
        UPDATE omgangar SET
            omsattning=?, utdelning_8=?, utdelning_7=?, utdelning_6=?, utdelning_5=?,
            vinnare_8=?, vinnare_7=?, vinnare_6=?, jackpot_5=?, system_count=?
        WHERE id=?
    """, (omst_kr, payout(8), payout(7), payout(6), payout(5),
          winners(8), winners(7), winners(6), jackpot_5,
          res.get("systemCount"), gid))

    print(f"  ✓ {gid}: utd={payout(8)} kr, {winners(8)} vinnare")

conn.commit()

# ── 3. Kolla läget ────────────────────────────────────────
total = conn.execute("SELECT COUNT(*) FROM omgangar").fetchone()[0]
med_utd = conn.execute("SELECT COUNT(*) FROM omgangar WHERE utdelning_8 IS NOT NULL").fetchone()[0]
med_hastar = conn.execute("SELECT COUNT(DISTINCT lopp_id) FROM hastar").fetchone()[0]
print(f"\n✓ Databas OK:")
print(f"  Omgångar totalt : {total}")
print(f"  Med utdelning   : {med_utd}")
print(f"  Lopp med hästar : {med_hastar}")

cols_now = {r[1] for r in conn.execute("PRAGMA table_info(hastar)")}
print(f"  Hastar-kolumner : {sorted(cols_now)}")
conn.close()
print("\nKlar! Starta om app.py.")
