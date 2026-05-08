"""
fix3.py — Extraherar utdelning ur raw_json som redan finns i databasen.
Kör med: python fix3.py
"""
import sqlite3, json
from pathlib import Path

DB = Path(__file__).parent / "v85.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

uppdaterade = 0
saknar = conn.execute(
    "SELECT id, raw_json FROM omgangar WHERE utdelning_8 IS NULL AND raw_json IS NOT NULL"
).fetchall()

print(f"Omgångar utan utdelning men med raw_json: {len(saknar)}")

for row in saknar:
    gid = row["id"]
    try:
        game = json.loads(row["raw_json"])
    except:
        continue

    # Leta efter V85-pooldata i race-listan
    races = game.get("races", [])
    
    # Hämta omsättning
    turnover = game.get("turnover")
    omst_kr = turnover / 100 if turnover else None

    # Hämta system_count
    system_count = game.get("systemCount") or game.get("numberOfSystems")

    # Leta utdelning i game-nivå payouts
    payouts_raw = game.get("payouts", {})
    
    utd8 = utd7 = utd6 = utd5 = None
    vinn8 = vinn7 = vinn6 = None
    jackpot5 = 0

    if payouts_raw and isinstance(payouts_raw, dict):
        for k, v in payouts_raw.items():
            if not isinstance(v, dict):
                continue
            amt = v.get("payout") or v.get("amount") or v.get("dividend")
            sys = v.get("systems") or v.get("numberOfWinners") or v.get("winners")
            jp  = v.get("jackpot", False)
            amt_kr = amt / 100 if amt else None
            if k == "8":   utd8, vinn8 = amt_kr, sys
            elif k == "7": utd7, vinn7 = amt_kr, sys
            elif k == "6": utd6, vinn6 = amt_kr, sys
            elif k == "5":
                utd5 = amt_kr
                if jp: jackpot5 = 1

    # Alternativt: leta i races -> pools -> V85
    if utd8 is None:
        for race in races:
            pools = race.get("pools", {})
            v85 = pools.get("V85", {})
            result = v85.get("result", {})
            if not result:
                continue
            # Försök hitta payout-info
            game_result = game.get("result", {})
            v85_game = game_result.get("V85", {}) if isinstance(game_result, dict) else {}
            if v85_game:
                payouts_inner = v85_game.get("payouts", {})
                for k, v in payouts_inner.items():
                    amt = v.get("payout")
                    amt_kr = amt / 100 if amt else None
                    sys = v.get("systems")
                    if k == "8":   utd8, vinn8 = amt_kr, sys
                    elif k == "7": utd7, vinn7 = amt_kr, sys
                break

    # Uppdatera om vi hittade något
    if any(x is not None for x in [omst_kr, utd8, utd7, system_count]):
        conn.execute("""
            UPDATE omgangar SET
                omsattning    = COALESCE(omsattning, ?),
                utdelning_8   = COALESCE(utdelning_8, ?),
                utdelning_7   = COALESCE(utdelning_7, ?),
                utdelning_6   = COALESCE(utdelning_6, ?),
                utdelning_5   = COALESCE(utdelning_5, ?),
                vinnare_8     = COALESCE(vinnare_8, ?),
                vinnare_7     = COALESCE(vinnare_7, ?),
                vinnare_6     = COALESCE(vinnare_6, ?),
                jackpot_5     = COALESCE(jackpot_5, ?),
                system_count  = COALESCE(system_count, ?)
            WHERE id=?
        """, (omst_kr, utd8, utd7, utd6, utd5,
              vinn8, vinn7, vinn6, jackpot5, system_count, gid))
        uppdaterade += 1
        print(f"  {gid}: oms={omst_kr and f'{omst_kr/1e6:.1f}Mkr'}, utd8={utd8}, sys={system_count}")

conn.commit()

# Visa resultat
total  = conn.execute("SELECT COUNT(*) FROM omgangar").fetchone()[0]
med    = conn.execute("SELECT COUNT(*) FROM omgangar WHERE utdelning_8 IS NOT NULL").fetchone()[0]
med_om = conn.execute("SELECT COUNT(*) FROM omgangar WHERE omsattning IS NOT NULL").fetchone()[0]
print(f"\n✓ Uppdaterade {uppdaterade} omgångar")
print(f"  Totalt: {total} | Med utdelning: {med} | Med omsättning: {med_om}")
conn.close()
