import sqlite3

from history_store import get_db_path


def load_robot() -> dict | None:
    with sqlite3.connect(get_db_path()) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT base_url, host, port, device_name, device_id, client_name, pair_token, paired_at
            FROM paired_robot
            WHERE singleton = 1
            """
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def save_robot(config: dict) -> None:
    with sqlite3.connect(get_db_path()) as connection:
        connection.execute(
            """
            INSERT INTO paired_robot (
                singleton,
                base_url,
                host,
                port,
                device_name,
                device_id,
                client_name,
                pair_token,
                paired_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(singleton) DO UPDATE SET
                base_url = excluded.base_url,
                host = excluded.host,
                port = excluded.port,
                device_name = excluded.device_name,
                device_id = excluded.device_id,
                client_name = excluded.client_name,
                pair_token = excluded.pair_token,
                paired_at = excluded.paired_at
            """,
            (
                1,
                config["base_url"],
                config["host"],
                config["port"],
                config["device_name"],
                config["device_id"],
                config["client_name"],
                config["pair_token"],
                config["paired_at"],
            ),
        )
        connection.commit()


def clear_robot() -> None:
    with sqlite3.connect(get_db_path()) as connection:
        connection.execute("DELETE FROM paired_robot WHERE singleton = 1")
        connection.commit()
