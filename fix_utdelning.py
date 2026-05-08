"""
fix_utdelning.py - Extraherar utdelning ur raw_json.
python fix_utdelning.py
"""
import sqlite3, json
from pathlib import Path

DB = Path(__file__).parent / "v85.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

def fmt(kr):
    if kr is None: return "—"
    if kr >= 1e6: return f"{kr/1e6:.2f} Mkr"
    return f"{kr:,.0f} kr"

omgangar = conn.execute(
    "SELECT id, raw_json FROM omgangar WHERE raw_json IS NOT NULL"
).fetchall()
print(f"Behandlar {len(omgangar)} omgångar...\n")

uppdaterade = 0
for omg in omgangar:
    gid = omg["id"]
    try:
        game = json.loads(omg["raw_json"])
    except:
        continue

    races = game.get("races", [])
    if not races:
        continue

    utdelning_8 = None
    vinnare_8 = None
    omsattning = None
    system_count = None

    # Omsättning från game-nivå pools
    game_pools = game.get("pools", {})
    if isinstance(game_pools, dict):
        v85_gp = game_pools.get("V85", {})
        if isinstance(v85_gp, dict):
            t = v85_gp.get("turnover")
            if t: omsattning = t / 100
            system_count = v85_gp.get("numberOfSystems") or v85_gp.get("systemCount")

    # Utdelning från race-pools
    for race in races:
        v85_pool = race.get("pools", {}).get("V85", {})
        result = v85_pool.get("result", {})
        if not result:
            continue
        value = result.get("value", {})
        if value and "amount" in value:
            amount = value["amount"]
            utdelning_8 = amount / 100 if amount else None
        systems = result.get("systems")
        if systems is not None:
            vinnare_8 = systems
        if utdelning_8 is not None:
            break

    jackpot = 1 if vinnare_8 == 0 else 0

    if utdelning_8 is not None or omsattning is not None:
        conn.execute("""
            UPDATE omgangar SET
                utdelning_8  = COALESCE(utdelning_8, ?),
                vinnare_8    = COALESCE(vinnare_8, ?),
                omsattning   = COALESCE(omsattning, ?),
                system_count = COALESCE(system_count, ?),
                jackpot_5    = CASE WHEN jackpot_5 IS NULL THEN ? ELSE jackpot_5 END
            WHERE id=?
        """, (utdelning_8, vinnare_8, omsattning, system_count, jackpot, gid))
        uppdaterade += 1
        print(f"  {gid}: {fmt(utdelning_8)}, {vinnare_8} vinnare")

conn.commit()

tot = conn.execute("SELECT COUNT(*) FROM omgangar").fetchone()[0]
med = conn.execute("SELECT COUNT(*) FROM omgangar WHERE utdelning_8 IS NOT NULL").fetchone()[0]
print(f"\nUppdaterade {uppdaterade} omgångar. Totalt: {tot} | Med utdelning: {med}")

print("\nAlla utdelningar:")
rows = conn.execute("""
    SELECT datum, bana, utdelning_8, vinnare_8, omsattning
    FROM omgangar WHERE utdelning_8 IS NOT NULL
    ORDER BY datum DESC
""").fetchall()
for r in rows:
    oms = fmt(r["omsattning"]) if r["omsattning"] else "—"
    print(f"  {r['datum']}  {(r['bana'] or '—'):<14}  {fmt(r['utdelning_8']):>14}  {r['vinnare_8'] or '?':>6} vinn  {oms}")

conn.close()
print("\nKlart! Starta om app.py.")
