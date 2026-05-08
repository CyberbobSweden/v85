"""
startup.py — Körs vid start. Väntar tills DB är redo innan Flask tar emot requests.
"""
import logging
log = logging.getLogger(__name__)

def init_db_if_empty():
    try:
        from fetch import get_db, hamta_all_historik, DB_PATH
        conn = get_db()
        count = conn.execute("SELECT COUNT(*) FROM omgangar").fetchone()[0]
        conn.close()

        if count == 0:
            log.info("Databasen är tom — hämtar V85-historik...")
            # Kör SYNKRONT (inte i bakgrundstråd) så DB är klar när Flask startar
            hamta_all_historik()
            log.info("Historik klar!")
        else:
            log.info(f"Databasen har redan {count} omgångar.")
    except Exception as e:
        log.error(f"startup fel: {e}")
