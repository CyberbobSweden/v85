"""
fix_all.py — Fixar allt i ett svep. Kör med: python fix_all.py
Säker att köra flera gånger.
"""
import sqlite3, json
from pathlib import Path

DB = Path(__file__).parent / "v85.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

print("=== FIX ALL ===\n")

# ── 1. Lägg till kolumner om de saknas ───────────────────
def add_col(table, col, typ):
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        print(f"  + {table}.{col}")

print("1. Kontrollerar schema...")
for col, typ in [("v85_leg","INTEGER"),("vinnare_namn","TEXT"),("vinnare_kusk","TEXT")]:
    add_col("lopp", col, typ)
for col, typ in [("odds","REAL"),("spelprocent","REAL"),("placering","INTEGER"),("v85_rank","INTEGER")]:
    add_col("hastar", col, typ)
for col, typ in [("utdelning_8","REAL"),("utdelning_7","REAL"),("utdelning_6","REAL"),
                 ("utdelning_5","REAL"),("vinnare_8","INTEGER"),("vinnare_7","INTEGER"),
                 ("vinnare_6","INTEGER"),("jackpot_5","INTEGER"),("system_count","INTEGER"),
                 ("omsattning","REAL")]:
    add_col("omgangar", col, typ)
conn.commit()
print("  ✓ Schema OK\n")

# ── 2. Sätt v85_leg (1-8) per omgång ─────────────────────
print("2. Sätter v85_leg (1-8)...")
n = 0
for omg in conn.execute("SELECT id FROM omgangar").fetchall():
    lopp = conn.execute(
        "SELECT id FROM lopp WHERE omgang_id=? ORDER BY nummer", (omg["id"],)
    ).fetchall()
    for leg, l in enumerate(lopp, 1):
        conn.execute("UPDATE lopp SET v85_leg=? WHERE id=?", (leg, l["id"]))
        n += 1
conn.commit()
print(f"  ✓ {n} lopp uppdaterade\n")

# ── 3. Extrahera v85_rank från reserveOrder ───────────────
print("3. Extraherar v85_rank från raw_json...")
omgangar = conn.execute(
    "SELECT id, raw_json FROM omgangar WHERE raw_json IS NOT NULL"
).fetchall()
hastar_upd = 0
for omg in omgangar:
    try:
        game = json.loads(omg["raw_json"])
    except:
        continue
    for race in game.get("races", []):
        rid = race.get("id")
        v85_pool = race.get("pools", {}).get("V85", {})
        reserve_order = v85_pool.get("result", {}).get("reserveOrder", [])
        if not reserve_order:
            continue
        for rank, horse_nr in enumerate(reserve_order, 1):
            n2 = conn.execute(
                "UPDATE hastar SET v85_rank=? WHERE lopp_id=? AND startnr=?",
                (rank, rid, horse_nr)
            ).rowcount
            hastar_upd += n2
conn.commit()
print(f"  ✓ {hastar_upd} hästar fick v85_rank\n")

# ── 4. Uppdatera vinnare i lopp från raw_json ─────────────
print("4. Uppdaterar vinnare i lopp...")
lopp_upd = 0
for omg in omgangar:
    try:
        game = json.loads(omg["raw_json"])
    except:
        continue
    for race in game.get("races", []):
        rid = race.get("id")
        v85_pool = race.get("pools", {}).get("V85", {})
        winners = v85_pool.get("result", {}).get("winners", [])
        if winners:
            vinnare_nr = winners[0]
            # Hitta häst med detta startnummer
            h = conn.execute(
                "SELECT namn, kusk FROM hastar WHERE lopp_id=? AND startnr=?",
                (rid, vinnare_nr)
            ).fetchone()
            if h:
                conn.execute(
                    "UPDATE lopp SET vinnare_nr=?, vinnare_namn=?, vinnare_kusk=? WHERE id=?",
                    (vinnare_nr, h["namn"], h["kusk"], rid)
                )
                lopp_upd += 1
conn.commit()
print(f"  ✓ {lopp_upd} lopp fick vinnare\n")

# ── 5. Utdelning för de 5 senaste via results-API ─────────
print("5. Hämtar utdelning från ATG...")
try:
    import requests
    H = {"Accept":"application/json","User-Agent":"Mozilla/5.0",
         "Origin":"https://www.atg.se","Referer":"https://www.atg.se/spel/V85"}
    r = requests.get("https://horse-betting-info.prod.c1.atg.cloud/api-public/v0/results/V85",
                     headers=H, timeout=15)
    results = r.json().get("gameResults", [])
    for res in results:
        gid = res["id"]
        omst = res.get("turnover", 0)
        omst_kr = omst / 100 if omst else None
        payouts = res.get("payouts", {})
        def p(k): a=payouts.get(str(k),{}).get("payout"); return a/100 if a else None
        def w(k): return payouts.get(str(k),{}).get("systems")
        jp5 = 1 if payouts.get("5",{}).get("jackpot") else 0
        # Uppdatera vinnare från results
        for race_res in res.get("races", []):
            rid = race_res.get("id")
            for ww in race_res.get("winners", []):
                h = conn.execute(
                    "SELECT namn, kusk FROM hastar WHERE lopp_id=? AND startnr=?",
                    (rid, ww.get("startNumber"))
                ).fetchone()
                if h:
                    conn.execute("UPDATE lopp SET vinnare_namn=?, vinnare_kusk=?, vinnare_nr=? WHERE id=?",
                        (h["namn"] or ww.get("horseName"), h["kusk"] or ww.get("driverName"),
                         ww.get("startNumber"), rid))
        conn.execute("""
            UPDATE omgangar SET omsattning=?, utdelning_8=?, utdelning_7=?,
                utdelning_6=?, utdelning_5=?, vinnare_8=?, vinnare_7=?,
                vinnare_6=?, jackpot_5=?, system_count=?
            WHERE id=?
        """, (omst_kr, p(8), p(7), p(6), p(5), w(8), w(7), w(6), jp5,
              res.get("systemCount"), gid))
        print(f"  ✓ {gid}: {p(8) and f'{p(8):,.0f} kr'}")
    conn.commit()
except Exception as e:
    print(f"  ⚠ Kunde inte hämta utdelning: {e}")

# ── Sammanfattning ─────────────────────────────────────────
print("\n=== SAMMANFATTNING ===")
tot = conn.execute("SELECT COUNT(*) FROM omgangar").fetchone()[0]
med_utd = conn.execute("SELECT COUNT(*) FROM omgangar WHERE utdelning_8 IS NOT NULL").fetchone()[0]
med_rank = conn.execute("SELECT COUNT(*) FROM hastar WHERE v85_rank IS NOT NULL").fetchone()[0]
med_leg = conn.execute("SELECT COUNT(*) FROM lopp WHERE v85_leg IS NOT NULL").fetchone()[0]
print(f"  Omgångar: {tot} | Med utdelning: {med_utd}")
print(f"  Hästar med v85_rank: {med_rank}")
print(f"  Lopp med v85_leg: {med_leg}")

# Visa rankingexempel
print("\nKontroll — Lopp 1 senaste omgång:")
rows = conn.execute("""
    SELECT h.v85_rank, h.startnr, h.namn, h.v85_vinnare
    FROM hastar h JOIN lopp l ON h.lopp_id=l.id
    JOIN omgangar o ON l.omgang_id=o.id
    WHERE o.datum=(SELECT MAX(datum) FROM omgangar) AND l.v85_leg=1
    ORDER BY h.v85_rank LIMIT 8
""").fetchall()
for r in rows:
    print(f"  Rank {r['v85_rank']} | Nr {r['startnr']:<3} | {r['namn']:<25} {'★ VANN' if r['v85_vinnare'] else ''}")

conn.close()
print("\n✓ Klart! Starta om app.py.")
