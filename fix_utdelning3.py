"""
fix_utdelning3.py - Extraherar utdelning ur game-nivå pools i raw_json.
python fix_utdelning3.py
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

omgangar = conn.execute("SELECT id, raw_json FROM omgangar WHERE raw_json IS NOT NULL").fetchall()
print(f"Behandlar {len(omgangar)} omgångar...\n")

# Visa game-pool struktur för första omgången
first = json.loads(omgangar[0]["raw_json"])
gp = first.get("pools", {})
print("=== Game-level pools struktur ===")
if isinstance(gp, dict):
    for k, v in gp.items():
        print(f"  Pool '{k}':")
        if isinstance(v, dict):
            for k2, v2 in v.items():
                print(f"    {k2}: {str(v2)[:120]}")
print()

uppdaterade = 0
for omg in omgangar:
    gid = omg["id"]
    try:
        game = json.loads(omg["raw_json"])
    except:
        continue

    utdelning_8 = None
    vinnare_8 = None
    omsattning = None
    system_count = None
    jackpot_5 = 0

    # Hämta från game-level pools
    game_pools = game.get("pools", {})
    if isinstance(game_pools, dict):
        v85_gp = game_pools.get("V85", {})
        if isinstance(v85_gp, dict):
            # Omsättning
            for tk in ["turnover", "totalTurnover", "total"]:
                if tk in v85_gp:
                    t = v85_gp[tk]
                    omsattning = t / 100 if t and t > 1000 else t
                    break

            # Utdelning
            result = v85_gp.get("result", {})
            if isinstance(result, dict):
                payouts = result.get("payouts", {})
                if isinstance(payouts, dict):
                    for k in ["8", 8]:
                        p = payouts.get(k, {})
                        if isinstance(p, dict):
                            amt = p.get("payout") or p.get("dividend") or p.get("amount")
                            sys = p.get("systems") or p.get("numberOfWinners")
                            if amt:
                                utdelning_8 = amt / 100 if amt > 10000 else amt
                                vinnare_8 = sys
                            jackpot_5 = 1 if payouts.get("5", {}).get("jackpot") else 0
                            break

            # Antal system
            system_count = v85_gp.get("numberOfSystems") or v85_gp.get("systemCount") or v85_gp.get("systems")

    # Fallback: titta i race-pools men på rätt sätt
    # Det sista loppets V85-pool result.value är per-rad för det loppet, INTE total 8/8
    # Men result.systems = antal vinnande rader
    if vinnare_8 is None:
        for race in game.get("races", []):
            v85p = race.get("pools", {}).get("V85", {})
            res = v85p.get("result", {})
            if res.get("systems") is not None:
                vinnare_8 = res["systems"]
                break

    if omsattning or utdelning_8:
        conn.execute("""
            UPDATE omgangar SET
                utdelning_8  = COALESCE(utdelning_8, ?),
                vinnare_8    = COALESCE(vinnare_8, ?),
                omsattning   = COALESCE(omsattning, ?),
                system_count = COALESCE(system_count, ?),
                jackpot_5    = CASE WHEN jackpot_5 IS NULL THEN ? ELSE jackpot_5 END
            WHERE id=?
        """, (utdelning_8, vinnare_8, omsattning, system_count, jackpot_5, gid))
        uppdaterade += 1
        print(f"  {gid}: utd={fmt(utdelning_8)}, vinn={vinnare_8}, oms={fmt(omsattning)}")

conn.commit()

print(f"\nUppdaterade {uppdaterade} omgångar")
med = conn.execute("SELECT COUNT(*) FROM omgangar WHERE utdelning_8 IS NOT NULL").fetchone()[0]
tot = conn.execute("SELECT COUNT(*) FROM omgangar").fetchone()[0]
print(f"Med utdelning: {med}/{tot}")
conn.close()
print("\nKlart! Starta om app.py.")
