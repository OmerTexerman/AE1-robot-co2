import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path("data/transcripts.db")


def get_db_path() -> Path:
    return Path(__file__).resolve().parent / DEFAULT_DB_PATH


def init_db(db_path: Path | None = None) -> None:
    database_path = db_path or get_db_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                script TEXT NOT NULL,
                font_family TEXT NOT NULL,
                provider TEXT NOT NULL,
                language TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(transcripts)").fetchall()
        }
        if "language" not in columns:
            connection.execute(
                "ALTER TABLE transcripts ADD COLUMN language TEXT NOT NULL DEFAULT ''"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS paired_robot (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                base_url TEXT NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL,
                device_name TEXT NOT NULL,
                device_id TEXT NOT NULL,
                client_name TEXT NOT NULL,
                pair_token TEXT NOT NULL,
                paired_at TEXT NOT NULL
            )
            """
        )
        connection.commit()


def save_transcript(
    text: str,
    script: str,
    font_family: str,
    provider: str,
    language: str,
    created_at: str,
    db_path: Path | None = None,
) -> int:
    database_path = db_path or get_db_path()

    with sqlite3.connect(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO transcripts (text, script, font_family, provider, language, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (text, script, font_family, provider, language, created_at),
        )
        connection.commit()
        return int(cursor.lastrowid)


def list_transcripts(limit: int = 12, db_path: Path | None = None) -> list[dict[str, str | int]]:
    database_path = db_path or get_db_path()

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT id, text, script, font_family, provider, language, created_at
            FROM transcripts
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]
