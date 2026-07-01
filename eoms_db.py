import sqlite3
from datetime import datetime


class EOMSDatabase:
    def __init__(self, db_name="eoms.db"):
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()
        self.create_table()

    def create_table(self):
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS bols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bol_id TEXT UNIQUE,
            raw_data TEXT,
            created_at TEXT
        )
        """)
        self.conn.commit()

    def insert_bols(self, bols):
        for bol in bols:
            try:
                self.cursor.execute("""
                INSERT OR IGNORE INTO bols (bol_id, raw_data, created_at)
                VALUES (?, ?, ?)
                """, (
                    str(bol.get("id")),
                    str(bol),
                    datetime.now().isoformat()
                ))
            except Exception as e:
                print("DB Insert Error:", e)

        self.conn.commit()

    def fetch_all(self):
        self.cursor.execute("SELECT * FROM bols")
        return self.cursor.fetchall()