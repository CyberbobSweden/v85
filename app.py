"""
app.py — Flask-webbgränssnitt för V85-databasen.
"""
import os, threading
from flask import Flask, render_template, jsonify, request
from pathlib import Path
from fetch import get_db, hamta_datum
from datetime import date

app = Flask(__name__)
DB_PATH = Path(os.environ.get("DB_PATH", str(Path(__file__).parent / "v85.db")))

# Auto-init vid Railway-start
def _auto_init():
    try:
        from startup import init_db_if_empty
        init_db_if_empty()
    except Exception as e:
        print(f"Auto-init: {e}")
threading.Thread(target=_auto_init, daemon=True).start()

def q(sql, params=()):
    conn = get_db(DB_PATH)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def q1(sql, params=()):
    conn = get_db(DB_PATH)
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return dict(row) if row else {}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/summary")
def api_summary():
    return jsonify(q1("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN utdelning_8 IS NOT NULL THEN 1 ELSE 0 END) as avslutade,
               AVG(utdelning_8) as snitt, MAX(utdelning_8) as max_utd,
               MIN(utdelning_8) as min_utd, SUM(jackpot_5) as jackpots,
               AVG(omsattning) as snitt_oms
        FROM omgangar
    """))

@app.route("/api/omgangar")
def api_omgangar():
    limit = int(request.args.get("limit", 60))
    return jsonify(q("""
        SELECT id, datum, vecka, bana, status, omsattning,
               utdelning_8, utdelning_7, utdelning_6,
               vinnare_8, vinnare_7, jackpot_5, system_count
        FROM omgangar ORDER BY datum DESC LIMIT ?
    """, (limit,)))

@app.route("/api/omgang/<path:gid>")
def api_omgang(gid):
    omg = q1("SELECT * FROM omgangar WHERE id=?", (gid,))
    if not omg:
        return jsonify({"error": "Hittades inte"}), 404
    omg.pop("raw_json", None)
    lopp = q("SELECT * FROM lopp WHERE omgang_id=? ORDER BY nummer", (gid,))
    for l in lopp:
        l["hastar"] = q("SELECT * FROM hastar WHERE lopp_id=? ORDER BY startnr", (l["id"],))
    omg["lopp"] = lopp
    return jsonify(omg)

@app.route("/api/statistik/utdelningar")
def api_utdelningar():
    return jsonify(q("""
        SELECT datum, bana, omsattning, utdelning_8, utdelning_7, utdelning_6,
               vinnare_8, vinnare_7, jackpot_5, system_count
        FROM omgangar WHERE utdelning_8 IS NOT NULL ORDER BY datum DESC
    """))

@app.route("/api/statistik/startnummer")
def api_startnummer():
    return jsonify(q("""
        SELECT startnr, COUNT(*) as vinster FROM hastar
        WHERE v85_vinnare=1 GROUP BY startnr ORDER BY vinster DESC LIMIT 12
    """))

@app.route("/api/statistik/kuskar")
def api_kuskar():
    return jsonify(q("""
        SELECT kusk, COUNT(*) as vinster FROM hastar
        WHERE v85_vinnare=1 AND kusk != ''
        GROUP BY kusk ORDER BY vinster DESC LIMIT 15
    """))

@app.route("/api/statistik/banor")
def api_banor():
    return jsonify(q("""
        SELECT bana, COUNT(*) as omgangar,
               AVG(utdelning_8) as snitt_utd, MAX(utdelning_8) as max_utd,
               AVG(omsattning) as snitt_oms
        FROM omgangar WHERE bana IS NOT NULL AND bana != ''
        GROUP BY bana ORDER BY omgangar DESC
    """))

@app.route("/api/hamta", methods=["POST"])
def api_hamta():
    dag_str = request.json.get("datum", str(date.today()))
    try:
        date.fromisoformat(dag_str)
    except ValueError:
        return jsonify({"error": "Ogiltigt datum"}), 400
    def do_fetch():
        conn = get_db(DB_PATH)
        hamta_datum(dag_str, conn, force=True)
        conn.close()
    threading.Thread(target=do_fetch, daemon=True).start()
    return jsonify({"status": "started", "datum": dag_str})

@app.route("/api/analys/filter-options")
def api_filter_options():
    return jsonify({
        "distanser": q("""
            SELECT COALESCE(l.v85_leg, l.nummer) as nummer, l.distans, COUNT(*) as n
            FROM lopp l WHERE l.distans IS NOT NULL
            GROUP BY COALESCE(l.v85_leg, l.nummer), l.distans
            ORDER BY nummer, n DESC
        """),
        "startmetoder": q("""
            SELECT COALESCE(l.v85_leg, l.nummer) as nummer, l.startmetod, COUNT(*) as n
            FROM lopp l WHERE l.startmetod IS NOT NULL AND l.startmetod != ''
            GROUP BY COALESCE(l.v85_leg, l.nummer), l.startmetod
            ORDER BY nummer, n DESC
        """)
    })

@app.route("/api/analys/lopp/<int:lopp_nr>")
def api_analys_lopp(lopp_nr):
    distans    = request.args.get("distans")
    startmetod = request.args.get("startmetod")
    where  = ["COALESCE(l.v85_leg, l.nummer) = ?"]
    params = [lopp_nr]
    if distans:
        where.append("l.distans = ?"); params.append(int(distans))
    if startmetod:
        where.append("l.startmetod = ?"); params.append(startmetod)
    w = " AND ".join(where)

    return jsonify({
        "lopp_nr": lopp_nr,
        "filter": {"distans": distans, "startmetod": startmetod},
        "totalt_lopp": q1(f"SELECT COUNT(*) as n FROM lopp l WHERE {w}", params).get("n", 0),
        "startnummer": q(f"""
            SELECT h.startnr, COUNT(*) as starter,
                   SUM(h.v85_vinnare) as vinster,
                   ROUND(100.0*SUM(h.v85_vinnare)/COUNT(*),1) as vinstprocent
            FROM hastar h JOIN lopp l ON h.lopp_id=l.id
            WHERE {w} AND h.struken=0 GROUP BY h.startnr ORDER BY h.startnr
        """, params),
        "odds_rank": q(f"""
            SELECT COALESCE(h.v85_rank, h.startnr) as odds_rank,
                   COUNT(*) as lopp_totalt,
                   SUM(h.v85_vinnare) as vinster,
                   ROUND(100.0*SUM(h.v85_vinnare)/COUNT(*),1) as vinstprocent
            FROM hastar h JOIN lopp l ON h.lopp_id=l.id
            WHERE {w} AND h.struken=0 AND COALESCE(h.v85_rank, h.startnr) <= 10
            GROUP BY COALESCE(h.v85_rank, h.startnr)
            ORDER BY odds_rank
        """, params),
        "distanser": q(f"SELECT l.distans, COUNT(*) as n FROM lopp l WHERE {w} AND l.distans IS NOT NULL GROUP BY l.distans ORDER BY n DESC", params),
        "startmetoder": q(f"SELECT l.startmetod, COUNT(*) as n FROM lopp l WHERE {w} AND l.startmetod IS NOT NULL AND l.startmetod!='' GROUP BY l.startmetod ORDER BY n DESC", params),
        "kon_stat": q(f"""
            SELECT h.kon, COUNT(*) as starter, SUM(h.v85_vinnare) as vinster,
                   ROUND(100.0*SUM(h.v85_vinnare)/NULLIF(COUNT(*),0),1) as vinstprocent
            FROM hastar h JOIN lopp l ON h.lopp_id=l.id
            WHERE {w} AND h.struken=0 AND h.kon!='' GROUP BY h.kon ORDER BY vinster DESC
        """, params),
        "alder_stat": q(f"""
            SELECT h.alder, COUNT(*) as starter, SUM(h.v85_vinnare) as vinster,
                   ROUND(100.0*SUM(h.v85_vinnare)/NULLIF(COUNT(*),0),1) as vinstprocent
            FROM hastar h JOIN lopp l ON h.lopp_id=l.id
            WHERE {w} AND h.struken=0 AND h.alder IS NOT NULL
            GROUP BY h.alder ORDER BY h.alder
        """, params),
        "kuskar": q(f"""
            SELECT h.kusk, SUM(h.v85_vinnare) as vinster, COUNT(*) as starter,
                   ROUND(100.0*SUM(h.v85_vinnare)/COUNT(*),1) as vinstprocent
            FROM hastar h JOIN lopp l ON h.lopp_id=l.id
            WHERE {w} AND h.struken=0 AND h.kusk!=''
            GROUP BY h.kusk HAVING vinster>0 ORDER BY vinster DESC LIMIT 15
        """, params),
        "senaste_vinnare": q(f"""
            SELECT o.datum, o.bana, l.distans, l.startmetod,
                   h.startnr, h.namn, h.kusk, h.v85_rank,
                   (SELECT COUNT(*) FROM hastar h2 WHERE h2.lopp_id=l.id AND h2.struken=0) as falt_storlek
            FROM hastar h JOIN lopp l ON h.lopp_id=l.id JOIN omgangar o ON l.omgang_id=o.id
            WHERE {w} AND h.v85_vinnare=1 ORDER BY o.datum DESC LIMIT 15
        """, params),
        "rank_fordelning": q(f"""
            SELECT h.v85_rank, COUNT(*) as tot, SUM(h.v85_vinnare) as vann,
                   ROUND(100.0*SUM(h.v85_vinnare)/NULLIF(COUNT(DISTINCT l.id),0),1) as kum_pct
            FROM hastar h JOIN lopp l ON h.lopp_id=l.id
            WHERE {w} AND h.struken=0 AND h.v85_rank IS NOT NULL
            GROUP BY h.v85_rank ORDER BY h.v85_rank
        """, params),

    })

@app.route("/api/analys/system")
def api_analys_system():
    raw = q("""
        SELECT COALESCE(l.v85_leg, l.nummer) as lopp_nr,
               h.v85_rank as odds_rank,
               COUNT(*) as lopp_totalt,
               SUM(h.v85_vinnare) as vinster,
               ROUND(100.0*SUM(h.v85_vinnare)/COUNT(*),1) as vinstprocent
        FROM hastar h
        JOIN lopp l ON h.lopp_id = l.id
        WHERE h.struken = 0
          AND h.v85_rank IS NOT NULL
          AND h.v85_rank <= 12
          AND COALESCE(l.v85_leg, l.nummer) BETWEEN 1 AND 8
        GROUP BY COALESCE(l.v85_leg, l.nummer), h.v85_rank
        ORDER BY lopp_nr, odds_rank
    """)

    from collections import defaultdict
    per_lopp = defaultdict(list)
    for r in raw:
        per_lopp[r["lopp_nr"]].append(r)

    result = []
    for lopp_nr in sorted(per_lopp.keys()):
        rader = per_lopp[lopp_nr]
        totalt = rader[0]["lopp_totalt"] if rader else 0
        # Räkna totalt antal lopp för detta lopp_nr
        tot_lopp = q("""
            SELECT COUNT(DISTINCT l.id) as n FROM lopp l
            WHERE COALESCE(l.v85_leg, l.nummer)=?
        """, (lopp_nr,))
        totalt = tot_lopp[0]["n"] if tot_lopp else totalt

        kumulativ_vinster = 0
        for r in rader:
            kumulativ_vinster += (r["vinster"] or 0)
            kum_pct = round(100.0 * kumulativ_vinster / totalt, 1) if totalt else 0
            result.append({
                "lopp_nr": lopp_nr,
                "odds_rank": r["odds_rank"],
                "lopp_totalt": totalt,
                "vinster": r["vinster"],
                "vinstprocent": r["vinstprocent"],
                "kumulativ_pct": kum_pct,
                "kumulativ_vinster": kumulativ_vinster,
            })
    return jsonify(result)



@app.route("/api/analys/systemforslag")
def api_systemforslag():
    """Genererar ett statistikbaserat systemförslag baserat på budget."""
    budget = float(request.args.get("budget", 200))
    pris_per_rad = float(request.args.get("pris", 0.5))
    max_rader = int(budget / pris_per_rad)
    if max_rader < 1: max_rader = 1

    # Hämta kumulativ täckning per lopp
    raw = q("""
        SELECT COALESCE(l.v85_leg, l.nummer) as lopp_nr,
               h.v85_rank,
               COUNT(DISTINCT l.id) as tot_lopp,
               SUM(h.v85_vinnare) as vann
        FROM hastar h JOIN lopp l ON h.lopp_id=l.id
        WHERE h.struken=0 AND h.v85_rank IS NOT NULL
          AND COALESCE(l.v85_leg, l.nummer) BETWEEN 1 AND 8
        GROUP BY lopp_nr, h.v85_rank
        ORDER BY lopp_nr, h.v85_rank
    """)

    from collections import defaultdict
    per_lopp = defaultdict(list)
    for r in raw:
        per_lopp[r["lopp_nr"]].append(r)

    # Beräkna hur många hästar man behöver per lopp för olika täckningsmål
    lopp_analys = {}
    for lopp_nr in range(1, 9):
        rader = per_lopp.get(lopp_nr, [])
        tot = rader[0]["tot_lopp"] if rader else 1
        kum = 0
        kum_data = []
        for r in rader:
            kum += (r["vann"] or 0)
            kum_data.append({
                "rank": r["v85_rank"],
                "kum_pct": round(100 * kum / tot, 1) if tot else 0,
                "kum_vann": kum,
                "tot": tot,
            })
        lopp_analys[lopp_nr] = kum_data

    # Hitta minsta antal hästar per lopp för olika mål
    def hastar_for_mal(lopp_nr, mal_pct):
        data = lopp_analys.get(lopp_nr, [])
        for d in data:
            if d["kum_pct"] >= mal_pct:
                return d["rank"]
        return len(data) if data else 8

    # Bygg system för 60%, 75%, 90% täckning
    system_mal = {}
    for mal in [60, 75, 90]:
        val_per_lopp = {}
        for l in range(1, 9):
            n = hastar_for_mal(l, mal)
            val_per_lopp[l] = n
        rader = 1
        for n in val_per_lopp.values():
            rader *= n
        system_mal[str(mal)] = {
            "mal": mal,
            "hastar_per_lopp": val_per_lopp,
            "antal_rader": rader,
            "kostnad_50ore": round(rader * 0.5, 2),
            "kostnad_1kr": rader,
            "ryms_i_budget": rader * pris_per_rad <= budget,
        }

    # Budget-optimerat system: greedy-algoritm som maximerar täckning inom budget
    # Börja med 1 häst per lopp, lägg till hästar i ordning av störst täckningsökning
    val = {l: 1 for l in range(1, 9)}
    
    def berakna_rader(v):
        r = 1
        for n in v.values(): r *= n
        return r
    
    def snitt_tackning(v):
        tot = 0
        for l in range(1, 9):
            n = v[l]
            data = lopp_analys.get(l, [])
            row = next((d for d in data if d["rank"] >= n), data[-1] if data else None)
            tot += row["kum_pct"] if row else 0
        return tot / 8

    # Lägg till hästar en i taget - alltid den häst som ger mest täckning per rad
    while True:
        bast_lopp = None
        bast_gain = -1
        for l in range(1, 9):
            data = lopp_analys.get(l, [])
            max_rank = data[-1]["rank"] if data else 1
            if val[l] >= max_rank:
                continue
            # Räkna täckningsökning om vi lägger till en häst i lopp l
            ny_val = dict(val)
            ny_val[l] += 1
            ny_rader = berakna_rader(ny_val)
            if ny_rader * pris_per_rad > budget:
                continue
            # Täckningsökning för detta lopp
            curr_data = next((d for d in data if d["rank"] >= val[l]), None)
            new_data  = next((d for d in data if d["rank"] >= ny_val[l]), None)
            curr_pct  = curr_data["kum_pct"] if curr_data else 0
            new_pct   = new_data["kum_pct"] if new_data else curr_pct
            gain = new_pct - curr_pct
            extra_rader = ny_rader - berakna_rader(val)
            # gain per extra rad
            gain_per_rad = gain / max(extra_rader, 1)
            if gain_per_rad > bast_gain:
                bast_gain = gain_per_rad
                bast_lopp = l
        if bast_lopp is None:
            break
        val[bast_lopp] += 1

    rader = berakna_rader(val)
    tackning = snitt_tackning(val)
    
    basta_system = {
        "mal": None,
        "hastar_per_lopp": val,
        "antal_rader": rader,
        "kostnad": round(rader * pris_per_rad, 2),
        "snitt_tackning": round(tackning, 1),
    } if rader > 0 else None

    return jsonify({
        "budget": budget,
        "pris_per_rad": pris_per_rad,
        "max_rader": max_rader,
        "system_per_mal": system_mal,
        "basta_system": basta_system,
        "lopp_analys": {str(k): v for k, v in lopp_analys.items()},
    })


@app.route("/api/kommande")
def api_kommande():
    """Hämtar kommande V85 eller V86-omgång från ATG."""
    import requests, time
    from datetime import date, timedelta

    speltyp = request.args.get("typ", "V85").upper()  # V85 eller V86

    H = {"Accept":"application/json","User-Agent":"Mozilla/5.0",
         "Origin":"https://www.atg.se","Referer":f"https://www.atg.se/spel/{speltyp}"}
    CAL = "https://www.atg.se/services/racinginfo/v1/api"
    BET = "https://horse-betting-info.prod.c1.atg.cloud/api-public/v0"

    # V85 = lördag (weekday 5), V86 = söndag (weekday 6)
    malfdag = 5 if speltyp == "V85" else 6
    dag = date.today()
    dagar_fram = 0
    while dag.weekday() != malfdag:
        dag += timedelta(days=1)
        dagar_fram += 1
    # Om dagens dag redan är rätt veckodag men sent på kvällen, ta nästa vecka
    # (Vi tar alltid "nästa" förekomst, aldrig historisk)

    # Hämta kalender för lördagen
    try:
        kal = requests.get(f"{CAL}/calendar/day/{dag}", headers=H, timeout=10).json()
    except:
        return jsonify({"error": "Kunde inte hämta kalender"}), 500

    tracks = kal.get("tracks", [])
    UTLANDSKA = {54, 78, 91, 92, 93, 94, 95, 96, 97, 98}

    # Hitta spelet (V85 eller V86)
    game = None
    game_id = None
    for lnr in [3, 4, 5, 6, 2, 7, 1, 8]:
        for track in tracks:
            tid = track.get("id")
            if not tid or tid in UTLANDSKA:
                continue
            gid = f"{speltyp}_{dag}_{tid}_{lnr}"
            try:
                g = requests.get(f"{BET}/games/{gid}", headers=H, timeout=8).json()
                time.sleep(0.2)
                if g and isinstance(g, dict) and g.get("id"):
                    game = g
                    game_id = gid
                    break
            except:
                pass
        if game:
            break

    if not game:
        return jsonify({"error": f"Ingen V85 hittad för {dag}", "datum": str(dag)}), 404

    # Bygg loppdata med hästar och spelprocent
    lopp_lista = []
    for i, race in enumerate(game.get("races", []), 1):
        rid = race.get("id")
        hastar = []

        # Hämta fullständigt startfält från races-endpoint
        try:
            race_data = requests.get(f"{BET}/races/{rid}", headers=H, timeout=10).json()
            time.sleep(0.3)
            starts = race_data.get("starts", []) if race_data else []
        except:
            starts = race.get("starts", [])

        struktna = set(race.get("result", {}).get("scratchings", []))

        for s in starts:
            nr = s.get("number")
            horse = s.get("horse", {}) or {}
            driver = s.get("driver", {}) or {}
            pools = s.get("pools", {}) or {}

            # Spelprocent från V85-pool
            sp_pct = None
            for pk in ["V85", "vinnare", "win"]:
                pool = pools.get(pk, {})
                if isinstance(pool, dict):
                    sp_pct = pool.get("betDistribution") or pool.get("percentage")
                    if sp_pct:
                        break

            # Odds från vinnare-pool
            odds = None
            for pk in ["vinnare", "win"]:
                pool = pools.get(pk, {})
                if isinstance(pool, dict):
                    odds = pool.get("odds")
                    if odds:
                        break

            kusk = (driver.get("firstName","") + " " + driver.get("lastName","")).strip()
            struken = 1 if nr in struktna else 0

            hastar.append({
                "nr": nr,
                "namn": horse.get("name", ""),
                "kusk": kusk,
                "alder": horse.get("age"),
                "kon": horse.get("sex", ""),
                "odds": odds,
                "sp_pct": sp_pct,
                "struken": struken,
                "rekord": None,
            })

        # Sortera efter spelprocent (högst = rank 1) om tillgänglig, annars startnr
        hastar_aktiva = [h for h in hastar if not h["struken"]]
        hastar_aktiva.sort(key=lambda h: -(h["sp_pct"] or 0) if h["sp_pct"] else h["nr"])
        for rank, h in enumerate(hastar_aktiva, 1):
            h["rank"] = rank

        lopp_lista.append({
            "leg": i,
            "id": rid,
            "namn": race.get("name", f"Lopp {i}"),
            "distans": race.get("distance"),
            "startmetod": race.get("startMethod", ""),
            "starttid": str(race.get("scheduledStartTime", ""))[:16].replace("T", " "),
            "status": race.get("status", "upcoming"),
            "hastar": hastar,
        })

    return jsonify({
        "datum": str(dag),
        "speltyp": speltyp,
        "game_id": game_id,
        "status": game.get("status", "upcoming"),
        "bana": next((t["name"] for t in tracks if str(t.get("id","")) in game_id), tracks[0]["name"] if tracks else "?"),
        "lopp": lopp_lista,
    })


@app.route("/api/kommande/system", methods=["POST"])
def api_kommande_system():
    """Beräknar system baserat på A/B/C-märkning och budget."""
    data = request.json
    budget = float(data.get("budget", 200))
    pris = float(data.get("pris", 0.5))
    abc = data.get("abc", {})  # {lopp_leg: {nr: "A"|"B"|"C"}}
    max_rader = int(budget / pris)

    # Räkna ut alla kombinationer av hästar per lopp
    # A = alltid med, B = kan tas med, C = kan tas med om utrymme
    # Minimum: alla A-hästar
    # Maximum: A + B + C

    lopp_val = {}  # leg -> list of nr to include
    for leg in range(1, 9):
        leg_str = str(leg)
        abc_leg = abc.get(leg_str, {})
        a_hastar = [int(nr) for nr, cat in abc_leg.items() if cat == "A"]
        b_hastar = [int(nr) for nr, cat in abc_leg.items() if cat == "B"]
        c_hastar = [int(nr) for nr, cat in abc_leg.items() if cat == "C"]

        # Minimum: minst 1 häst (a om finns, annars alla)
        base = a_hastar if a_hastar else list(range(1, 3))
        lopp_val[leg] = {
            "a": a_hastar,
            "b": b_hastar,
            "c": c_hastar,
            "min": a_hastar if a_hastar else [],
            "current": list(a_hastar),
        }

    # Greedy: lägg till B-hästar i ordning av flest spel-% tills budget tar slut
    def raeder(val):
        r = 1
        for l in range(1, 9):
            n = len(val[l]["current"])
            r *= max(n, 1)
        return r

    # Lägg alltid till alla A
    for leg in range(1, 9):
        lopp_val[leg]["current"] = list(lopp_val[leg]["a"]) if lopp_val[leg]["a"] else []

    # Försök lägga till B och C
    kandidater = []
    for leg in range(1, 9):
        for nr in lopp_val[leg]["b"]:
            kandidater.append((leg, nr, "B", 0))
        for nr in lopp_val[leg]["c"]:
            kandidater.append((leg, nr, "C", 1))  # lägre prio

    kandidater.sort(key=lambda x: x[3])  # B före C

    for leg, nr, cat, _ in kandidater:
        test_val = {l: dict(lopp_val[l]) for l in range(1, 9)}
        test_val[leg]["current"] = list(test_val[leg]["current"]) + [nr]
        if raeder(test_val) * pris <= budget:
            lopp_val[leg]["current"].append(nr)

    # Se till att varje lopp har minst 1 häst
    for leg in range(1, 9):
        if not lopp_val[leg]["current"]:
            lopp_val[leg]["current"] = [1]  # fallback

    antal_rader = raeder(lopp_val)
    kostnad = antal_rader * pris

    result = {}
    for leg in range(1, 9):
        result[str(leg)] = {
            "a": lopp_val[leg]["a"],
            "b": lopp_val[leg]["b"],
            "c": lopp_val[leg]["c"],
            "med": lopp_val[leg]["current"],
            "antal": len(lopp_val[leg]["current"]),
        }

    return jsonify({
        "antal_rader": antal_rader,
        "kostnad": round(kostnad, 2),
        "budget": budget,
        "pris": pris,
        "lopp": result,
    })


@app.route("/api/kommande/reducerat", methods=["POST"])
def api_reducerat():
    """
    Bygger reducerade systemkuponger baserat på A/B/C-märkning och budget.
    
    Reducering:
    - A = gardering (alltid med i ALLA kuponger)
    - B = troliga (delas upp mellan kupongerna)
    - C = möjliga (tas med i enstaka kuponger)
    - Antal kuponger bestäms av budget och antal rader per kupong
    """
    data = request.json
    budget    = float(data.get("budget", 200))
    pris      = float(data.get("pris", 0.5))
    abc       = data.get("abc", {})    # {leg: {nr: A|B|C}}
    n_kupong  = int(data.get("kuponger", 2))  # önskat antal kuponger

    budget_per_kupong = budget / n_kupong
    max_rader = int(budget_per_kupong / pris)

    # Bygg per-lopp struktur
    lopp = {}
    for leg in range(1, 9):
        leg_str = str(leg)
        abc_leg = abc.get(leg_str, {})
        lopp[leg] = {
            "A": sorted([int(n) for n, c in abc_leg.items() if c == "A"]),
            "B": sorted([int(n) for n, c in abc_leg.items() if c == "B"]),
            "C": sorted([int(n) for n, c in abc_leg.items() if c == "C"]),
        }

    def rader(val):
        r = 1
        for v in val.values(): r *= max(len(v), 1)
        return r

    def bygg_bas():
        """Basval: bara A-hästar (eller dummy om inga A)."""
        return {l: list(lopp[l]["A"]) or [] for l in range(1, 9)}

    # Generera kupongvariationer:
    # Kupong 1: A + alla B + inga C
    # Kupong 2: A + dela B + alla C  
    # Kupong 3+: A + rotera B/C
    
    kuponger = []
    
    if n_kupong == 1:
        # En kupong: greedy fyll med B sedan C
        val = {l: list(lopp[l]["A"]) for l in range(1, 9)}
        # Se till minst 1 per lopp
        for l in range(1, 9):
            if not val[l]:
                if lopp[l]["B"]: val[l] = [lopp[l]["B"][0]]
                elif lopp[l]["C"]: val[l] = [lopp[l]["C"][0]]
                else: val[l] = [1]
        # Lägg till fler hästar inom budget
        kandidater = [(l, n, "B") for l in range(1,9) for n in lopp[l]["B"] if n not in val[l]]
        kandidater += [(l, n, "C") for l in range(1,9) for n in lopp[l]["C"] if n not in val[l]]
        for l, n, cat in kandidater:
            test = {ll: list(v) for ll, v in val.items()}
            test[l].append(n)
            if rader(test) * pris <= budget:
                val[l].append(n)
        kuponger.append(val)

    else:
        # Flera kuponger: dela upp B-hästar mellan kupongerna
        # Strategi: B-hästar roteras, A alltid med, C i sista kuponger
        
        for k in range(n_kupong):
            val = {l: list(lopp[l]["A"]) for l in range(1, 9)}
            
            for l in range(1, 9):
                b_hastar = lopp[l]["B"]
                c_hastar = lopp[l]["C"]
                
                if not b_hastar and not c_hastar:
                    if not val[l]:
                        val[l] = [1]  # fallback
                    continue
                
                if not b_hastar:
                    # Bara C: ta en C per kupong roterandes
                    if c_hastar:
                        val[l].append(c_hastar[k % len(c_hastar)])
                    continue
                
                # Dela B-hästar: 
                # k=0: ta halva B (de med lägst nr = favoriter)
                # k=1: ta andra halvan B
                # k=2+: ta alla B (om budget räcker)
                mid = max(1, len(b_hastar) // 2)
                if k == 0:
                    val[l].extend(b_hastar[:mid])
                elif k == 1:
                    val[l].extend(b_hastar[mid:] or b_hastar)
                else:
                    val[l].extend(b_hastar)
                
                # Lägg till C i senare kuponger
                if k >= n_kupong - 1:
                    for cn in c_hastar:
                        test = {ll: list(v) for ll, v in val.items()}
                        test[l].append(cn)
                        if rader(test) * pris <= budget_per_kupong:
                            val[l].append(cn)
                
                if not val[l]:
                    val[l] = b_hastar[:1] or [1]
            
            # Justera om för många rader
            while rader(val) * pris > budget_per_kupong:
                # Minska det lopp med lägst "vinst per häst"
                target = max(
                    (l for l in range(1,9) if len(val[l]) > max(len(lopp[l]["A"]), 1)),
                    key=lambda l: len(val[l]),
                    default=None
                )
                if target is None: break
                # Ta bort sista B eller C häst
                removable = [n for n in val[target] if n not in lopp[target]["A"]]
                if removable:
                    val[target].remove(removable[-1])
                else:
                    break
            
            # Se till minst 1 per lopp
            for l in range(1, 9):
                if not val[l]:
                    if lopp[l]["B"]: val[l] = [lopp[l]["B"][0]]
                    elif lopp[l]["C"]: val[l] = [lopp[l]["C"][0]]
                    elif lopp[l]["A"]: val[l] = lopp[l]["A"][:1]
                    else: val[l] = [1]
            
            kuponger.append(val)

    # Bygg resultat
    resultat = []
    total_rader = 0
    total_kostnad = 0
    
    for i, val in enumerate(kuponger):
        r = rader(val)
        k = r * pris
        total_rader += r
        total_kostnad += k
        
        # Märk skillnader mot föregående kupong
        diff = {}
        if i > 0:
            prev = kuponger[i-1]
            for l in range(1, 9):
                added   = [n for n in val[l] if n not in prev[l]]
                removed = [n for n in prev[l] if n not in val[l]]
                if added or removed:
                    diff[l] = {"added": added, "removed": removed}
        
        lopp_info = {}
        for l in range(1, 9):
            lopp_info[str(l)] = {
                "hastar": sorted(val[l]),
                "antal":  len(val[l]),
                "A": [n for n in val[l] if n in lopp[l]["A"]],
                "B": [n for n in val[l] if n in lopp[l]["B"]],
                "C": [n for n in val[l] if n in lopp[l]["C"]],
                "diff": diff.get(l, {}),
            }
        
        resultat.append({
            "kupong": i + 1,
            "rader": r,
            "kostnad": round(k, 2),
            "lopp": lopp_info,
        })
    
    return jsonify({
        "kuponger": resultat,
        "total_rader": total_rader,
        "total_kostnad": round(total_kostnad, 2),
        "budget": budget,
        "pris": pris,
        "n_kupong": n_kupong,
    })

if __name__ == "__main__":
    print("\n  V85 Statistik · http://localhost:5000\n")
    app.run(debug=True, port=5000)
