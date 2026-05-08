"""
fix_check2.py — Verifierar statistiken och letar utdelning i raw_json.
python fix_check2.py
"""
import sqlite3, json, requests
from pathlib import Path

DB = Path(__file__).parent / "v85.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# ── Kolla lopp 4 kumulativ statistik ─────────────────────
print("=== LOPP 4 — kumulativ täckning ===")
rows = conn.execute("""
    SELECT h.v85_rank, COUNT(*) as tot, SUM(h.v85_vinnare) as vann
    FROM hastar h JOIN lopp l ON h.lopp_id=l.id
    WHERE l.v85_leg=4 AND h.struken=0 AND h.v85_rank IS NOT NULL
    GROUP BY h.v85_rank ORDER BY h.v85_rank
""").fetchall()

total_lopp = conn.execute(
    "SELECT COUNT(DISTINCT l.id) FROM lopp l WHERE l.v85_leg=4"
).fetchone()[0]

print(f"Totalt {total_lopp} lopp i V85-leg 4")
kum = 0
for r in rows:
    kum += r["vann"]
    pct = 100*kum/total_lopp if total_lopp else 0
    print(f"  Top {r['v85_rank']}: {r['vann']}/{total_lopp} ({pct:.0f}% kumulativt)")

# ── Kolla om raw_json har utdelningsdata ─────────────────
print("\n=== Utdelningsdata i raw_json ===")
omg = conn.execute(
    "SELECT id, raw_json FROM omgangar WHERE raw_json IS NOT NULL LIMIT 3"
).fetchall()
for o in omg:
    g = json.loads(o["raw_json"])
    keys = list(g.keys())
    print(f"\n{o['id']}:")
    print(f"  Game-nycklar: {keys}")
    # Kolla om payouts finns
    if "payouts" in g:
        print(f"  PAYOUTS: {g['payouts']}")
    if "result" in g:
        print(f"  RESULT: {str(g['result'])[:200]}")
    # Kolla race-pools för utdelning
    for race in g.get("races", [])[:1]:
        v85 = race.get("pools", {}).get("V85", {})
        print(f"  V85-pool nycklar: {list(v85.keys())}")
        result = v85.get("result", {})
        print(f"  V85-result nycklar: {list(result.keys())}")
        if "value" in result:
            print(f"  VALUE: {result['value']}")

# ── Prova ATG:s hemsida för historisk utdelning ───────────
print("\n=== Testar ATG webbsida för historisk utdelning ===")
H = {"Accept":"application/json","User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
     "Origin":"https://www.atg.se","Referer":"https://www.atg.se"}

# Prova några historiska game-IDs vi känner till
known_ids = conn.execute(
    "SELECT id FROM omgangar ORDER BY datum DESC LIMIT 8"
).fetchall()

for row in known_ids:
    gid = row["id"]
    # Prova payouts-endpoint
    url = f"https://horse-betting-info.prod.c1.atg.cloud/api-public/v0/games/{gid}/payouts"
    try:
        r = requests.get(url, headers=H, timeout=8)
        if r.status_code == 200 and r.text and r.text != "null":
            print(f"  ✓ PAYOUTS för {gid}: {r.text[:200]}")
        else:
            print(f"  {r.status_code} {gid}")
    except:
        pass

conn.close()
