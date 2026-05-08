"""
fix_utdelning2.py - Rensar fel utdelningsdata och letar rätt fält i raw_json.
python fix_utdelning2.py
"""
import sqlite3, json
from pathlib import Path

DB = Path(__file__).parent / "v85.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# ── Steg 1: Rensa de 5 kända korrekta utdelningarna ──────
# Vi vet vilka som är rätt (från results-API):
KANDA_RATTA = {
    "V85_2026-05-02_27_5": (32497, 605),
    "V85_2026-04-25_32_5": (751937, 10),   # 7.52 Mkr
    "V85_2026-04-18_12_5": None,            # Bollnäs - jackpot 8/8
    "V85_2026-04-11_7_5":  (24724, 1924),
    "V85_2026-04-05_23_5": (141574, 435),
}

# Rensa ALL utdelning utom de kända rätta
print("Steg 1: Rensar felaktig utdelning...")
conn.execute("""
    UPDATE omgangar SET utdelning_8=NULL, vinnare_8=NULL
    WHERE id NOT IN ({})
""".format(",".join(f"'{k}'" for k in KANDA_RATTA.keys())))
conn.commit()
print(f"  ✓ Rensade felaktig data")

# ── Steg 2: Kolla game-nivå pools i raw_json ─────────────
print("\nSteg 2: Letar i game-nivå pools...")
omgangar = conn.execute(
    "SELECT id, raw_json FROM omgangar WHERE raw_json IS NOT NULL"
).fetchall()

for omg in omgangar:
    gid = omg["id"]
    try:
        game = json.loads(omg["raw_json"])
    except:
        continue

    # Game-level pools - detta är aggregerat för hela V85-omgången
    game_pools = game.get("pools", {})
    print(f"\n{gid}:")
    if isinstance(game_pools, dict):
        for pool_name, pool_data in game_pools.items():
            if isinstance(pool_data, dict):
                print(f"  Pool '{pool_name}': {list(pool_data.keys())}")
                # Kolla om det finns payout-info
                for key in ["dividend", "payout", "payouts", "result", "turnover", "amount"]:
                    if key in pool_data:
                        print(f"    {key}: {str(pool_data[key])[:100]}")
    else:
        print(f"  pools-typ: {type(game_pools)}")

conn.close()
print("\n✓ Klar!")
