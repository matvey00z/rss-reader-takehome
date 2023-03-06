import feedparser
import time
import threading
import dramatiq
from dramatiq.brokers.rabbitmq import RabbitmqBroker
import json
import os

import db as db_handler

UPDATE_INTERVAL_SEC = 2
MAX_FAIL_COUNT = 3

dramatiq_broker = RabbitmqBroker(parameters=[
    dict(host='mq'),
])
dramatiq.set_broker(dramatiq_broker)

db = db_handler.DB(
    os.environ['DBHOST'],
    os.environ['DBPORT'],
    os.environ['DBUSER'],
    os.environ['DBPASSWORD'],
)

def get_feed_updates(url, etag = None, modified = None):
    headers = {}
    if etag:
        headers['If-None-Match'] = etag
    if modified:
        headers['If-Modified-Since'] = modified
    feed = feedparser.parse(url, etag=etag, modified=modified, request_headers=headers)
    if feed.status == 304:
        entries = []
    else:
        entries = feed.entries
    return {
        'etag': feed.etag,
        'modified': feed.modified,
        'entries': entries,
    }


@dramatiq.actor
def update_feed(url, fail_count = 0):
    start_time = time.monotonic()
    if fail_count >= MAX_FAIL_COUNT:
        db.set_failed(url)

    try:
        last_updated = db.get_feed_last_updated(url)
        if last_updated is None:
            # The feed does not exist in the table any more
            return
        updates = get_feed_updates(url, last_updated['etag'], last_updated['modified'])
        db.put_updates(url, updates['etag'], updates['modified'],
            [{
                'published': int(time.mktime(update.published_parsed)),
                'content': json.dumps(update)
            } for update in updates['entries']])

        fail_count = 0
    except:
        fail_count += 1

    to_sleep = start_time + UPDATE_INTERVAL_SEC * (10 ** fail_count) - time.monotonic()
    if to_sleep > 0:
        time.sleep(to_sleep)
    update_feed.send(url, fail_count)


if __name__ == '__main__':
    for feed in db.list_all_feeds():
        update_feed.send(feed)