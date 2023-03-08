import psycopg2
from psycopg2 import pool
from psycopg2.extras import execute_values
import logging
from dataclasses import dataclass
from typing import List, Optional

DBNAME = "rss_db"
POOL_MIN_CONNECTIONS = 1
POOL_MAX_CONNECTIONS = 10

MAX_ENTRY_SIZE = 64 * 1024

logging.basicConfig(level=logging.DEBUG)


class UserNotFound(Exception):
    def __init__(self, username):
        self.username = username
        super().__init__(f"No user found: {username}")


class UserAlreadyExists(Exception):
    def __init__(self, username):
        super().__init__(f"User already exists: {username}")


class FeedNotFound(Exception):
    def __init__(self, feed_url):
        self.feed_url = feed_url
        super().__init__(f"No feed found: {feed_url}")


class ConnectionManager(object):
    def __init__(self, pool):
        self.pool = pool

    def __enter__(self):
        self.conn = self.pool.getconn()
        return self.conn

    def __exit__(self, *args):
        self.conn.commit()
        self.pool.putconn(self.conn)


class DB:
    def __init__(self, host, port, user, password, create=False):
        self.pool = psycopg2.pool.SimpleConnectionPool(
            POOL_MIN_CONNECTIONS,
            POOL_MAX_CONNECTIONS,
            host=host,
            port=port,
            database=DBNAME,
            user=user,
            password=password,
        )
        if create:
            with self.conn() as conn:
                with conn.cursor() as cursor:
                    self.create_feeds_table(cursor)
                    self.create_feed_items_table(cursor)
                    self.create_users_table(cursor)
                    self.create_user_feeds_table(cursor)

    def conn(self):
        return ConnectionManager(self.pool)

    def create_feeds_table(self, cursor):
        table = "Feeds"
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                feed_id SERIAL PRIMARY KEY,
                feed_url VARCHAR(255) UNIQUE,
                etag VARCHAR(255),
                modified VARCHAR(255),
                failed BOOLEAN DEFAULT false
            );
        """
        )
        if cursor.rowcount > 0:
            logging.info(f"Created table {table}")
        else:
            logging.info(f"Table {table} already exists")

    def create_feed_items_table(self, cursor):
        table = "FeedItems"
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                item_id SERIAL PRIMARY KEY,
                feed_id INTEGER,
                published INTEGER,
                entry VARCHAR({MAX_ENTRY_SIZE}),
                FOREIGN KEY (feed_id) REFERENCES Feeds (feed_id),
                UNIQUE(feed_id, published, entry)
            );
        """
        )
        if cursor.rowcount > 0:
            logging.info(f"Created table {table}")
        else:
            logging.info(f"Table {table} already exists")

    def create_users_table(self, cursor):
        table = "Users"
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                user_id SERIAL PRIMARY KEY,
                username VARCHAR(255) UNIQUE
            );
        """
        )
        if cursor.rowcount > 0:
            logging.info(f"Created table {table}")
        else:
            logging.info(f"Table {table} already exists")

    def create_user_feeds_table(self, cursor):
        table = "UserFeeds"
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                user_feed_id SERIAL PRIMARY KEY,
                user_id INTEGER,
                feed_id INTEGER,
                last_read_item_id INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES Users (user_id),
                FOREIGN KEY (feed_id) REFERENCES Feeds (feed_id),
                UNIQUE(user_id, feed_id)
            );
        """
        )
        if cursor.rowcount > 0:
            logging.info(f"Created table {table}")
        else:
            logging.info(f"Table {table} already exists")

    def add_user(self, username: str):
        with self.conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO Users (username) VALUES(%s)
                       ON CONFLICT DO NOTHING
                       RETURNING user_id""",
                    (username,),
                )
                result = cursor.fetchone()
                if not result:
                    raise UserAlreadyExists(username)

    def get_user_id(self, cursor, username: str):
        cursor.execute("SELECT user_id FROM users WHERE username = %s", (username,))
        result = cursor.fetchone()
        if not result:
            raise UserNotFound(username)
        return result[0]

    def get_feed_id(self, cursor, feed_url):
        cursor.execute("SELECT feed_id FROM feeds WHERE feed_url = %s", (feed_url,))
        result = cursor.fetchone()
        if not result:
            raise FeedNotFound(feed_url)
        return result[0]

    def get_or_put_feed(self, cursor, url: str):
        cursor.execute("SELECT feed_id FROM feeds WHERE feed_url = %s", (url,))
        result = cursor.fetchone()
        if result:
            return result[0], False
        cursor.execute(
            "INSERT INTO feeds (feed_url) VALUES(%s) RETURNING feed_id", (url,)
        )
        return cursor.fetchone()[0], True

    def follow_feed(self, username: str, url: str):
        with self.conn() as conn:
            with conn.cursor() as cursor:
                user_id = self.get_user_id(cursor, username)
                feed_id, feed_created = self.get_or_put_feed(cursor, url)
                cursor.execute(
                    """INSERT INTO UserFeeds (user_id, feed_id) VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING user_feed_id""",
                    (user_id, feed_id),
                )
                return cursor.fetchone() is not None, feed_created

    def unfollow_feed(self, username: str, feed_url: str):
        """
        After this call the feed is no longer followed.
        Return True if it existed beforehand, False otherwise
        """
        with self.conn() as conn:
            with conn.cursor() as cursor:
                user_id = self.get_user_id(cursor, username)
                feed_id = self.get_feed_id(cursor, feed_url)
                cursor.execute(
                    "DELETE FROM UserFeeds WHERE user_id = %s AND feed_id = %s",
                    (user_id, feed_id),
                )
                success = cursor.rowcount != 0
                return success

    def list_feeds(self, username: str):
        with self.conn() as conn:
            with conn.cursor() as cursor:
                user_id = self.get_user_id(cursor, username)
                cursor.execute(
                    """SELECT Feeds.feed_url FROM Feeds
                       JOIN UserFeeds ON Feeds.feed_id = UserFeeds.feed_id
                       WHERE UserFeeds.user_id = %s""",
                    (user_id,),
                )
                return [res[0] for res in cursor.fetchall()]

    def get_feed_last_updated(self, feed_url: str):
        with self.conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """SELECT etag, modified FROM Feeds WHERE feed_url = %s""",
                    (feed_url,),
                )
                result = cursor.fetchone()
                if result is None:
                    return None
                else:
                    return {"etag": result[0], "modified": result[1]}

    def put_updates(
        self,
        feed_url: str,
        etag: Optional[str],
        modified: Optional[str],
        entries: List[str],
    ):
        entries = sorted(entries, key=lambda entry: entry["published"])
        with self.conn() as conn:
            with conn.cursor() as cursor:
                feed_id = self.get_feed_id(cursor, feed_url)
                query = """INSERT INTO FeedItems (feed_id, published, entry) VALUES %s
                ON CONFLICT DO NOTHING"""
                execute_values(
                    cursor,
                    query,
                    [
                        (feed_id, entry["published"], entry["content"])
                        for entry in entries
                    ],
                )
                if etag is not None or modified is not None:
                    etag_query = "etag = %s , " if etag is not None else ""
                    modified_query = "modified = %s , " if modified is not None else ""
                    values = tuple(
                        (x for x in (etag, modified, feed_id) if x is not None)
                    )
                    query = f"""UPDATE Feeds SET {etag_query} {modified_query} failed = false
                                WHERE feed_id = %s"""
                    cursor.execute(query, values)

    def set_failed(self, feed_url):
        with self.conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""UPDATE Feeds SET failed = true""")

    def list_all_feeds(self):
        with self.conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT feed_url FROM Feeds")
                return [res[0] for res in cursor.fetchall()]

    def get_feed_items(self, username: str, feed_url: str, unread_only: bool):
        with self.conn() as conn:
            with conn.cursor() as cursor:
                user_id = self.get_user_id(cursor, username)
                feed_id = self.get_feed_id(cursor, feed_url)
                cursor.execute(
                    """SELECT last_read_item_id FROM UserFeeds
                                  WHERE user_id = %s AND feed_id = %s""",
                    (user_id, feed_id),
                )
                last_read = cursor.fetchone()
                if last_read is None:
                    # Feed not found for particular user
                    raise FeedNotFound(feed_url)
                last_read = last_read[0]
                last_read_query = "AND item_id > %s" if unread_only else ""
                if unread_only:
                    last_read_query = "AND item_id > %s"
                else:
                    last_read_query = ""
                    last_read = None
                values = tuple((x for x in (feed_id, last_read) if x is not None))
                cursor.execute(
                    f"""SELECT item_id, entry FROM FeedItems
                    WHERE feed_id = %s {last_read_query}
                    ORDER BY published""",
                    values,
                )
                items = [{"id": res[0], "content": res[1]} for res in cursor.fetchall()]
                cursor.execute(
                    "SELECT failed FROM Feeds WHERE feed_id = %s", (feed_id,)
                )
                failed = cursor.fetchone()[0]
                return {"items": items, "failed": failed}

    def get_all_items(self, username: str, unread_only: bool):
        with self.conn() as conn:
            with conn.cursor() as cursor:
                user_id = self.get_user_id(cursor, username)
                unread_query = (
                    "AND items.item_id > feeds.last_read_item_id" if unread_only else ""
                )
                cursor.execute(
                    f"""
                    SELECT items.item_id, items.entry
                    FROM UserFeeds feeds
                    JOIN FeedItems items ON feeds.feed_id = items.feed_id
                    WHERE feeds.user_id = %s
                    {unread_query}
                    ORDER BY items.published
                """,
                    (user_id,),
                )
                items = [{"id": res[0], "content": res[1]} for res in cursor.fetchall()]
                cursor.execute(
                    """
                    SELECT Feeds.feed_url
                    FROM Feeds
                    JOIN UserFeeds ON Feeds.feed_id = UserFeeds.feed_id
                    WHERE UserFeeds.user_id = %s AND Feeds.failed = true""",
                    (user_id,),
                )
                failed_ids = [res[0] for res in cursor.fetchall()]
                return {"items": items, "failed": failed_ids}

    def mark_as_read(self, username: str, feed_url: str, item_id: int):
        with self.conn() as conn:
            with conn.cursor() as cursor:
                user_id = self.get_user_id(cursor, username)
                feed_id = self.get_feed_id(cursor, feed_url)
                cursor.execute(
                    """UPDATE UserFeeds SET last_read_item_id = %s
                    WHERE user_id = %s AND feed_id = %s""",
                    (item_id, user_id, feed_id),
                )

    def request_feed_update(self, feed_url: str):
        with self.conn() as conn:
            with conn.cursor() as cursor:
                feed_id = self.get_feed_id(cursor, feed_url)
                cursor.execute(
                    """UPDATE Feeds SET failed = false
                    WHERE feed_id = %s AND failed = true
                    RETURNING failed""",
                    (feed_id,),
                )
                was_failed = cursor.fetchone() is not None
                return was_failed
