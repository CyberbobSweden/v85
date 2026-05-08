"""
fetch.py — Hämtar V85-data från ATG:s horse-betting-info API och sparar i SQLite.

Verifierade endpoints:
  Alla resultat:  GET /results/V85?limit=200
  Per datum:      GET /results/V85?date=YYYY-MM-DD
  Omgångsdetalj: GET /games/{gameId}          (t.ex. V85_2026-05-02_27_5)
  Loppdetalj:    GET /races/{raceId}           (t.ex. 2026-05-02_27_5) — inkl. startfält
"""

import os
import sqlite3
import requests
import json
import time
import logging
from datetime import date, datetime
from pathlib import Path

# ── Konfiguration ─────────────────────────────────────────
BASE_URL  = "https://horse-betting-info.prod.c1.atg.cloud/api-public/v0"
V85_START = date(2025, 10, 4)   # Börja leta från detta datum
DB_PATH   = Path(os.environ.get("DB_PATH", str(Path(__file__).parent / "v85.db")))
SLEEP_SEC = 0.5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Origin": "https://www.atg.se",
    "Referer": "https://www.atg.se/spel/V85",
}

def api_get_url(url, retries=3):
    """Hämtar en godtycklig URL (används för kalender-API:et)."""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            if e.response.status_code in (404, 400):
                return None
            time.sleep(2 ** attempt)
        except Exception as e:
            log.warning(f"api_get_url fel: {e}")
            time.sleep(2 ** attempt)
    return None

# ── Databasschema ─────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS omgangar (
    id           TEXT PRIMARY KEY,        -- "V85_2026-05-02_27_5"
    datum        TEXT NOT NULL,           -- "2026-05-02"
    vecka        INTEGER,
    bana         TEXT,
    bana_id      INTEGER,
    status       TEXT,
    omsattning   REAL,                    -- öre → kr dividerat med 100
    utdelning_8  REAL,                    -- kr per rätt rad, 8 rätt
    utdelning_7  REAL,
    utdelning_6  REAL,
    utdelning_5  REAL,
    vinnare_8    INTEGER,
    vinnare_7    INTEGER,
    vinnare_6    INTEGER,
    jackpot_5    INTEGER DEFAULT 0,       -- 1 om 5 rätt var jackpot
    system_count INTEGER,
    raw_json     TEXT
);

CREATE TABLE IF NOT EXISTS lopp (
    id           TEXT PRIMARY KEY,        -- "2026-05-02_27_5"
    omgang_id    TEXT REFERENCES omgangar(id),
    nummer       INTEGER,
    v85_leg      INTEGER,                 -- V85-loppets ordning 1-8
    namn         TEXT,
    distans      INTEGER,
    starttid     TEXT,
    startmetod   TEXT,
    status       TEXT,
    vinnare_nr   INTEGER,
    vinnare_namn TEXT,
    vinnare_kusk TEXT,
    struktna     TEXT                     -- JSON-lista med struktna startnummer
);

CREATE TABLE IF NOT EXISTS hastar (
    id           TEXT PRIMARY KEY,
    lopp_id      TEXT REFERENCES lopp(id),
    startnr      INTEGER,
    namn         TEXT,
    alder        INTEGER,
    kon          TEXT,
    kusk_id      INTEGER,
    kusk         TEXT,
    tranare      TEXT,
    v85_vinnare  INTEGER DEFAULT 0,
    struken      INTEGER DEFAULT 0,
    distans      INTEGER,
    rekord       TEXT,
    odds         REAL,
    spelprocent  REAL,
    placering    INTEGER,
    v85_rank     INTEGER
);

CREATE INDEX IF NOT EXISTS idx_omgangar_datum ON omgangar(datum);
CREATE INDEX IF NOT EXISTS idx_lopp_omgang    ON lopp(omgang_id);
CREATE INDEX IF NOT EXISTS idx_hastar_lopp    ON hastar(lopp_id);
"""

# ── Databas ───────────────────────────────────────────────
def get_db(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    # Bakåtkompatibilitet: lägg till kolumner om de saknas
    existing_lopp = {r[1] for r in conn.execute("PRAGMA table_info(lopp)")}
    for col, typ in [("v85_leg","INTEGER"), ("vinnare_namn","TEXT"), ("vinnare_kusk","TEXT")]:
        if col not in existing_lopp:
            try:
                conn.execute(f"ALTER TABLE lopp ADD COLUMN {col} {typ}")
            except Exception:
                pass
    existing_hastar = {r[1] for r in conn.execute("PRAGMA table_info(hastar)")}
    for col, typ in [("odds","REAL"),("spelprocent","REAL"),("placering","INTEGER"),("v85_rank","INTEGER")]:
        if col not in existing_hastar:
            try:
                conn.execute(f"ALTER TABLE hastar ADD COLUMN {col} {typ}")
            except Exception:
                pass
    conn.commit()
    return conn

# ── API ───────────────────────────────────────────────────
def api_get(path, retries=3):
    url = BASE_URL + path
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            if e.response.status_code in (404, 400):
                return None
            log.warning(f"HTTP {e.response.status_code} ({attempt+1}/{retries}): {url}")
            time.sleep(2 ** attempt)
        except Exception as e:
            log.warning(f"Fel ({attempt+1}/{retries}): {e}")
            time.sleep(2 ** attempt)
    return None


# ── Spara omgång + lopp ───────────────────────────────────
def spara_omgang(conn, game: dict):
    """Sparar en omgång från /games/{id}-svaret."""
    gid    = game["id"]
    datum  = gid.split("_")[1]           # "2026-05-02"
    status = game.get("status", "")

    # Bana från första loppet
    bana = ""
    bana_id = None
    races = game.get("races", [])
    if races:
        t = races[0].get("track", {})
        bana    = t.get("name", "")
        bana_id = t.get("id")

    # Omsättning och utdelning finns i results/V85-svaret, inte i games-svaret.
    # Vi sparar det separat via spara_resultat().
    conn.execute("""
        INSERT OR REPLACE INTO omgangar
            (id, datum, vecka, bana, bana_id, status, raw_json)
        VALUES (?,?,?,?,?,?,?)
    """, (gid, datum, veckonummer(datum), bana, bana_id, status,
          json.dumps(game, ensure_ascii=False)))

    # Lopp
    for leg, race in enumerate(races, 1):
        rid     = race.get("id")
        if not rid:
            continue
        nummer  = race.get("number")
        namn    = race.get("name", "")
        distans = race.get("distance")
        tid     = str(race.get("scheduledStartTime", race.get("startTime", "")))[:16].replace("T"," ")
        metod   = race.get("startMethod", "")
        rstatus = race.get("status", "")
        v85_leg = leg  # V85-loppets ordning 1-8

        # V85-vinnare i detta lopp
        vinnare_nr   = None
        vinnare_namn = None
        vinnare_kusk = None
        pool = race.get("pools", {}).get("V85", {})
        v85_result = pool.get("result", {})
        v85_winners = v85_result.get("winners", [])
        if v85_winners:
            vinnare_nr = v85_winners[0]

        struktna = json.dumps(race.get("result", {}).get("scratchings", []))

        conn.execute("""
            INSERT OR REPLACE INTO lopp
                (id, omgang_id, nummer, v85_leg, namn, distans, starttid, startmetod,
                 status, vinnare_nr, vinnare_namn, vinnare_kusk, struktna)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (rid, gid, nummer, v85_leg, namn, distans, tid, metod, rstatus,
              vinnare_nr, vinnare_namn, vinnare_kusk, struktna))

    conn.commit()

def spara_resultat(conn, result: dict):
    """Uppdaterar omgång med utdelnings- och omsättningsdata från /results/V85."""
    gid  = result["id"]
    omst = result.get("turnover", 0)
    omst_kr = omst / 100 if omst else None   # ATG returnerar öre

    payouts = result.get("payouts", {})
    def payout(key):
        p = payouts.get(str(key), {})
        amt = p.get("payout")
        return amt / 100 if amt else None
    def winners(key):
        return payouts.get(str(key), {}).get("systems")

    jackpot_5 = 1 if payouts.get("5", {}).get("jackpot") else 0

    # Vinnarhästnamn från races
    for race_res in result.get("races", []):
        rid = race_res.get("id")
        for w in race_res.get("winners", []):
            conn.execute("""
                UPDATE lopp SET vinnare_namn=?, vinnare_kusk=?, vinnare_nr=?
                WHERE id=?
            """, (w.get("horseName"), w.get("driverName"), w.get("startNumber"), rid))

    conn.execute("""
        UPDATE omgangar SET
            omsattning=?, utdelning_8=?, utdelning_7=?, utdelning_6=?, utdelning_5=?,
            vinnare_8=?, vinnare_7=?, vinnare_6=?, jackpot_5=?,
            system_count=?
        WHERE id=?
    """, (omst_kr, payout(8), payout(7), payout(6), payout(5),
          winners(8), winners(7), winners(6), jackpot_5,
          result.get("systemCount"), gid))
    conn.commit()

def spara_startfalt(conn, race_data: dict, omgang_id: str):
    """Sparar hästar från /races/{id}-svaret."""
    rid = race_data.get("id")
    struktna_set = set(race_data.get("result", {}).get("scratchings", []))

    # Uppdatera loppnamn om vi nu har det
    namn = race_data.get("name", "")
    if namn:
        conn.execute("UPDATE lopp SET namn=? WHERE id=?", (namn, rid))

    for start in race_data.get("starts", []):
        hid    = start.get("id", f"{rid}_{start.get('number','?')}")
        horse  = start.get("horse", {}) or {}
        driver = start.get("driver", {}) or {}
        trainer = horse.get("trainer", {}) or {}

        nr      = start.get("number")
        struken = 1 if nr in struktna_set else 0

        kusk = (driver.get("firstName","") + " " + driver.get("lastName","")).strip()
        if not kusk:
            kusk = driver.get("shortName","")

        tranare = (trainer.get("firstName","") + " " + trainer.get("lastName","")).strip()

        # Rekord
        rec = horse.get("record", {}) or {}
        rekord_str = ""
        if rec.get("time"):
            t = rec["time"]
            rekord_str = f"{t.get('minutes',0)}:{str(t.get('seconds',0)).zfill(2)},{t.get('tenths',0)}"

        # Kontrollera om denna häst vann V85-loppet
        lopp_row = conn.execute("SELECT vinnare_nr FROM lopp WHERE id=?", (rid,)).fetchone()
        v85_vinnare = 1 if (lopp_row and lopp_row["vinnare_nr"] == nr) else 0

        conn.execute("""
            INSERT OR REPLACE INTO hastar
                (id, lopp_id, startnr, namn, alder, kon, kusk_id, kusk,
                 tranare, v85_vinnare, struken, distans, rekord)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (hid, rid, nr,
              horse.get("name",""),
              horse.get("age"),
              horse.get("sex",""),
              driver.get("id"),
              kusk, tranare,
              v85_vinnare, struken,
              start.get("distance"),
              rekord_str))

    conn.commit()

# ── Hämta all historik ────────────────────────────────────
# ── Alla lördagar sedan premiären ────────────────────────
def alla_lordagar(fran=None, till=None):
    from datetime import date, timedelta
    fran = fran or V85_START
    till = till or date.today()
    dag = fran
    while dag.weekday() != 5:
        dag += timedelta(days=1)
    dagar = []
    while dag <= till:
        dagar.append(dag)
        dag += timedelta(weeks=1)
    return dagar

def veckonummer(d):
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return d.isocalendar()[1]

def hitta_game_id(datum, conn):
    """
    Hämtar kalender för datumet, provar sedan V85_{datum}_{trackId}_{loppNr}
    mot games-API:et tills vi hittar ett träff. Returnerar game-dict eller None.
    """
    CAL = "https://www.atg.se/services/racinginfo/v1/api"
    kal = api_get_url(f"{CAL}/calendar/day/{datum}")
    if not kal or not isinstance(kal, dict):
        return None

    tracks = kal.get("tracks", [])
    # V85 startar alltid på lopp 5 (verifierat på alla kända omgångar).
    # Vi provar bara lopp 4-6 för att vara säkra, skippar utländska banor.
    UTLANDSKA = {54, 78, 91, 92, 93, 94, 95, 96, 97, 98, 99}  # Bjerke, Åby Norge m.fl.
    for lnr in [5, 4, 6, 3, 7]:
        for track in tracks:
            tid = track.get("id")
            if not tid or tid in UTLANDSKA:
                continue
            gid = f"V85_{datum}_{tid}_{lnr}"
            game = api_get(f"/games/{gid}")
            time.sleep(0.2)
            if game and isinstance(game, dict) and game.get("id"):
                log.info(f"  Hittade: {gid} ({track.get('name')}, lopp {lnr})")
                return game
    return None

def hamta_all_historik(force=False, limit=200):
    """
    Loopar igenom alla lördagar sedan premiären.
    Hämtar kalender för varje dag och konstruerar game-ID:n manuellt
    eftersom ATG:s results-API ignorerar date-parametern.
    """
    conn = get_db()
    dagar = alla_lordagar()
    log.info(f"Kollar {len(dagar)} lördagar sedan V85-premiären…")

    ny = 0
    for i, dag in enumerate(dagar, 1):
        dag_str = str(dag)
        log.info(f"[{i}/{len(dagar)}] {dag_str}")

        if not force:
            row = conn.execute(
                "SELECT id FROM omgangar WHERE datum=? AND status='results'", (dag_str,)
            ).fetchone()
            if row:
                log.info(f"  Redan klar ({row['id']}), hoppar över")
                continue

        # Strategi 1: results-API (funkar för de 5 senaste)
        svar = api_get(f"/results/V85?date={dag_str}")
        time.sleep(SLEEP_SEC)
        res_map = {}
        if svar and svar.get("gameResults"):
            for res in svar["gameResults"]:
                d = res["id"].split("_")[1]
                if d == dag_str:
                    res_map[res["id"]] = res
                    log.info(f"  Hittade via results-API: {res['id']}")

        # Strategi 2: konstruera game-ID från kalender
        game = None
        if not res_map:
            game = hitta_game_id(dag_str, conn)
            if not game:
                log.info(f"  Ingen V85 denna dag")
                continue
            gid = game["id"]
        else:
            gid = list(res_map.keys())[0]

        # Hämta/spara game-detaljer
        if not game:
            game = api_get(f"/games/{gid}")
            time.sleep(SLEEP_SEC)

        if game:
            spara_omgang(conn, game)
        else:
            bana = "?"
            conn.execute(
                "INSERT OR REPLACE INTO omgangar (id, datum, vecka, bana, status) VALUES (?,?,?,?,'results')",
                (gid, dag_str, veckonummer(dag_str), bana)
            )
            conn.commit()

        # Utdelning från results-API om tillgängligt
        if gid in res_map:
            spara_resultat(conn, res_map[gid])
        else:
            # Försök hämta utdelning ändå
            svar2 = api_get(f"/results/V85?date={dag_str}")
            time.sleep(SLEEP_SEC)
            if svar2:
                for res in svar2.get("gameResults", []):
                    if res["id"] == gid:
                        spara_resultat(conn, res)

        # Startfält per lopp
        if game:
            race_ids = [r["id"] for r in game.get("races", [])]
            for j, rid in enumerate(race_ids):
                log.info(f"  Lopp {j+1}/{len(race_ids)}: {rid}")
                race_data = api_get(f"/races/{rid}")
                time.sleep(SLEEP_SEC)
                if race_data:
                    spara_startfalt(conn, race_data, gid)

        ny += 1
        log.info(f"  ✓ {gid} sparat")

    conn.close()
    log.info(f"\nKlart! {ny} nya omgångar hämtade.")

# ── Hämta ett specifikt datum ─────────────────────────────
def hamta_datum(dag_str: str, conn=None, force=False):
    close_after = conn is None
    if conn is None:
        conn = get_db()

    svar = api_get(f"/results/V85?date={dag_str}")
    time.sleep(SLEEP_SEC)
    if not svar or not svar.get("gameResults"):
        log.info(f"Ingen V85-omgång för {dag_str}")
        if close_after:
            conn.close()
        return False

    for res in svar["gameResults"]:
        gid = res["id"]
        if not force:
            row = conn.execute(
                "SELECT status FROM omgangar WHERE id=?", (gid,)
            ).fetchone()
            if row and row["status"] == "results":
                log.info(f"{gid} redan i databasen")
                if close_after:
                    conn.close()
                return False

        game = api_get(f"/games/{gid}")
        time.sleep(SLEEP_SEC)
        if game:
            spara_omgang(conn, game)
        else:
            datum = gid.split("_")[1]
            bana  = res.get("trackNames", ["?"])[0]
            conn.execute("""
                INSERT OR REPLACE INTO omgangar (id, datum, vecka, bana, status)
                VALUES (?,?,?,?,'results')
            """, (gid, datum, veckonummer(datum), bana))
            conn.commit()

        spara_resultat(conn, res)

        for race_res in res.get("races", []):
            rid = race_res.get("id")
            race_data = api_get(f"/races/{rid}")
            time.sleep(SLEEP_SEC)
            if race_data:
                spara_startfalt(conn, race_data, gid)

        log.info(f"✓ {gid} sparat")

    if close_after:
        conn.close()
    return True

# ── Terminal-statistik ────────────────────────────────────
def visa_statistik():
    conn = get_db()
    print("\n" + "═"*58)
    print("  V85 STATISTIK — ATG live data")
    print("═"*58)

    total = conn.execute("SELECT COUNT(*) FROM omgangar").fetchone()[0]
    row   = conn.execute("""
        SELECT COUNT(*) as n,
               AVG(utdelning_8) as snitt,
               MAX(utdelning_8) as max,
               MIN(utdelning_8) as min,
               SUM(jackpot_5)   as jp
        FROM omgangar WHERE utdelning_8 IS NOT NULL
    """).fetchone()

    print(f"\n  Omgångar i databasen : {total}")
    print(f"  Avslutade            : {row['n']}")
    if row['n']:
        print(f"  Snitt-utdelning 8/8  : {row['snitt']:>14,.0f} kr")
        print(f"  Högst               : {row['max']:>14,.0f} kr")
        print(f"  Lägst               : {row['min']:>14,.0f} kr")
        print(f"  Jackpottar (5 rätt) : {row['jp'] or 0}")

    print("\n  ── Senaste 8 omgångar ──────────────────────────────")
    rows = conn.execute("""
        SELECT datum, bana, omsattning, utdelning_8, vinnare_8, jackpot_5
        FROM omgangar ORDER BY datum DESC LIMIT 8
    """).fetchall()
    for r in rows:
        utd = f"{r['utdelning_8']:>12,.0f} kr" if r['utdelning_8'] else "      (ej klar)"
        omst = f"Oms: {r['omsattning']/1000000:.1f}Mkr" if r['omsattning'] else ""
        jp  = " ★ JACKPOT" if r['jackpot_5'] else ""
        print(f"  {r['datum']}  {(r['bana'] or '—'):<14} {utd}  {r['vinnare_8'] or 0} vinnare  {omst}{jp}")

    print("\n  ── Vanligaste vinnarnummer ─────────────────────────")
    rows = conn.execute("""
        SELECT startnr, COUNT(*) as n FROM hastar
        WHERE v85_vinnare=1 GROUP BY startnr ORDER BY n DESC LIMIT 10
    """).fetchall()
    for r in rows:
        bar = "█" * r['n']
        print(f"  Nr {r['startnr']:>2}   {bar}  {r['n']}×")

    print("\n  ── Vanligaste V85-kuskar ────────────────────────────")
    rows = conn.execute("""
        SELECT kusk, COUNT(*) as n FROM hastar
        WHERE v85_vinnare=1 AND kusk != ''
        GROUP BY kusk ORDER BY n DESC LIMIT 8
    """).fetchall()
    for r in rows:
        print(f"  {r['kusk']:<25}  {r['n']} segrar")

    print("\n" + "═"*58 + "\n")
    conn.close()


def hamta_utdelningar():
    """
    Hämtar utdelning för alla omgångar som saknar det.
    Results-API:et returnerar alltid de 5 senaste — vi matchar mot vad vi har i DB.
    """
    conn = get_db()
    
    # Hämta de 5 senaste från results-API
    svar = api_get("/results/V85")
    if not svar:
        conn.close()
        return
    
    for res in svar.get("gameResults", []):
        gid = res["id"]
        row = conn.execute(
            "SELECT utdelning_8 FROM omgangar WHERE id=?", (gid,)
        ).fetchone()
        if row and row["utdelning_8"] is None:
            log.info(f"  Uppdaterar utdelning för {gid}")
            spara_resultat(conn, res)
    
    # Kolla också om vi kan hämta utdelning från game-svaret för äldre
    saknar = conn.execute(
        "SELECT id FROM omgangar WHERE utdelning_8 IS NULL AND status='results'"
    ).fetchall()
    
    for row in saknar:
        gid = row["id"]
        log.info(f"  Försöker hämta utdelning för {gid}…")
        game = api_get(f"/games/{gid}")
        time.sleep(SLEEP_SEC)
        if not game:
            continue
        
        # Extrahera omsättning och utdelning från game-svaret
        turnover = game.get("turnover")
        omst_kr = turnover / 100 if turnover else None
        
        # Leta efter V85-utdelning i race pools
        payouts = {}
        for race in game.get("races", []):
            pools = race.get("pools", {})
            v85pool = pools.get("V85", {})
            result = v85pool.get("result", {})
            if result and "value" in result:
                # Summera utdelning per korrekt antal
                correct = result.get("correctCount", result.get("correct"))
                amount = result.get("value", {}).get("amount")
                systems = result.get("systems", result.get("numberOfWinners"))
                if correct and amount:
                    payouts[str(correct)] = {"payout": amount * 100, "systems": systems}
        
        if omst_kr or payouts:
            def payout(key):
                p = payouts.get(str(key), {})
                amt = p.get("payout")
                return amt / 100 if amt else None
            def winners(key):
                return payouts.get(str(key), {}).get("systems")
            
            conn.execute("""
                UPDATE omgangar SET 
                    omsattning=COALESCE(omsattning, ?),
                    utdelning_8=COALESCE(utdelning_8, ?),
                    utdelning_7=COALESCE(utdelning_7, ?),
                    utdelning_6=COALESCE(utdelning_6, ?),
                    vinnare_8=COALESCE(vinnare_8, ?),
                    vinnare_7=COALESCE(vinnare_7, ?)
                WHERE id=?
            """, (omst_kr, payout(8), payout(7), payout(6),
                  winners(8), winners(7), gid))
            conn.commit()
            log.info(f"  Uppdaterade {gid}: oms={omst_kr}")
    
    conn.close()
    log.info("Utdelningar uppdaterade!")

if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    hamta_all_historik(force=force)
    log.info("Hämtar utdelningar för alla omgångar...")
    hamta_utdelningar()
    visa_statistik()
