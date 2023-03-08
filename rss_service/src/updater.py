import feedparser
import time
import threading
import dramatiq
from dramatiq.brokers.rabbitmq import RabbitmqBroker
import json
import os
import logging
import sys
import socket

import db as db_handler

UPDATE_INTERVAL_SEC = 1
UPDATE_INTERVAL_INCREASE = 1
MAX_FAIL_COUNT = 3


dramatiq_broker = RabbitmqBroker(
    host=socket.gethostbyname(
        "mq"
    )  # Workaround dramatiq somehow failing to resolve the hostname
)
dramatiq.set_broker(dramatiq_broker)


db = db_handler.DB(
    os.environ["DBHOST"],
    os.environ["DBPORT"],
    os.environ["DBUSER"],
    os.environ["DBPASSWORD"],
)

logging.basicConfig(level=logging.DEBUG)


def get_feed_updates(url, etag=None, modified=None):
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if modified:
        headers["If-Modified-Since"] = modified
    feed = feedparser.parse(url, etag=etag, modified=modified, request_headers=headers)
    if feed.status == 304:
        entries = []
    else:
        entries = feed.entries
    logging.debug(f"Feed {url}: status {feed.status}, entries: {len(entries)}")
    return {
        "etag": feed.get("etag"),
        "modified": feed.get("modified"),
        "entries": entries,
    }


@dramatiq.actor
def update_feed(url, fail_count):
    logging.debug(f"Updating feed for {url}, fail count: {fail_count}")
    start_time = time.monotonic()
    if fail_count >= MAX_FAIL_COUNT:
        db.set_failed(url)
        return

    try:
        last_updated = db.get_feed_last_updated(url)
        if last_updated is None:
            logging.info(f"Feed is not followed any more: {url}")
            return
        updates = get_feed_updates(url, last_updated["etag"], last_updated["modified"])
        db.put_updates(
            feed_url=url,
            etag=updates["etag"],
            modified=updates["modified"],
            entries=[
                {
                    "published": int(time.mktime(update.published_parsed)),
                    "content": json.dumps(update),
                }
                for update in updates["entries"]
            ],
        )
        logging.debug("Successfully stored updates in DB")

        fail_count = 0
    except Exception as e:
        logging.error(f"Exception while trying to update feed {url}: {e}")
        fail_count += 1

    to_sleep = (
        start_time
        + UPDATE_INTERVAL_SEC * (UPDATE_INTERVAL_INCREASE**fail_count)
        - time.monotonic()
    )
    logging.debug(f"Sleep {to_sleep} sec before updating {url} next time")
    if to_sleep > 0:
        time.sleep(to_sleep)

    update_feed.send(url, fail_count)


def start_updating_feed(url):
    logging.info(f"Starting feed updates for {url}")
    update_feed.send(url, 0)


if __name__ == "__main__":
    for feed in db.list_all_feeds():
        start_updating_feed(feed)
