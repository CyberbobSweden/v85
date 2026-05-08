"""
startup.py — Körs automatiskt när appen startar på Railway.
Hämtar de senaste V85-omgångarna om databasen är tom.
"""
import os, sys, logging
from pathlib import Path

log = logging.getLogger(__name__)

def init_db_if_empty():
    try:
        from fetch import get_db, hamta_all_historik, DB_PATH
        conn = get_db()
        count = conn.execute("SELECT COUNT(*) FROM omgangar").fetchone()[0]
        conn.close()

        if count == 0:
            log.info("Databasen är tom — hämtar V85-historik...")
            hamta_all_historik()
            log.info("Klar!")
        else:
            log.info(f"Databasen har redan {count} omgångar.")
    except Exception as e:
        log.error(f"startup fel: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    init_db_if_empty()
