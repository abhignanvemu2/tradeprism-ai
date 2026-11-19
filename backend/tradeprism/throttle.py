"""Cross-process pacing; one Upstox REST request per 1.1 seconds (~1637/30m).
SQLite BEGIN IMMEDIATE prevents the collector and worker reserving the same slot.
"""
import sqlite3
import time
from .db import DATA


def pace():
    with sqlite3.connect(DATA/'upstox-rate.db',timeout=30) as c:
        c.execute('CREATE TABLE IF NOT EXISTS pacing (id INTEGER PRIMARY KEY, next REAL)')
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT next FROM pacing WHERE id=1').fetchone()
        stamp=time.time(); slot=max(stamp,row[0] if row else stamp)
        c.execute('INSERT OR REPLACE INTO pacing VALUES (1, ?)',(slot+1.1,))
    time.sleep(max(0,slot-time.time()))
