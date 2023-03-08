import pytest
import requests
from requests.exceptions import ConnectionError
import time
import http.server
import threading

HOST = "http://localhost:8000"
START_TIMEOUT_SEC = 3

test_users = ["user1", "user2", "xyz", "abc"]
test_feeds = [
    "http://abcd.com/rss",
    "http://xyza.com/rss",
]
real_feeds = [
    "http://www.nu.nl/rss/Algemeen",
    "https://feeds.feedburner.com/tweakers/mixed",
]


def assert_once(req):
    assert req().status_code == 200
    assert req().status_code != 200
    assert req().status_code != 200


def assert_multiple(req, first_message, next_message):
    for message in [first_message, next_message, next_message]:
        resp = req()
        resp.raise_for_status()
        assert resp.json()["message"] == message


@pytest.fixture(scope="session")
def app():
    url = "/".join([HOST, "healthcheck"])
    start_time = time.monotonic()
    while time.monotonic() - start_time < START_TIMEOUT_SEC:
        try:
            resp = requests.get(url)
            resp.raise_for_status()
            break
        except ConnectionError:
            time.sleep(1)
    else:
        pytest.exit("App failed to start")
    yield
    # Any cleanup


def test_healthcheck(app):
    url = "/".join([HOST, "healthcheck"])
    resp = requests.get(url)
    assert resp.status_code == 200
    assert resp.json() == {"message": "ok"}


def test_add_user(app):
    url = "/".join([HOST, "add_user"])
    # Check we can add a user only once
    for user in test_users:
        params = {"username": user}
        assert_once(lambda: requests.post(url, params=params))
    # Check we still cannot add the same user
    for user in test_users:
        params = {"username": user}
        assert requests.post(url, params=params).status_code != 200


def test_follow_unfollow(app):
    follow_url = "/".join([HOST, "follow"])
    unfollow_url = "/".join([HOST, "unfollow"])
    for user in test_users:
        for feed in test_feeds:
            params = {
                "username": user,
                "feed_url": feed,
            }
            assert_multiple(
                lambda: requests.post(follow_url, params=params),
                "Feed followed successfully",
                "Feed already followed",
            )
            params = {
                "username": user,
                "feed_url": feed,
            }
            assert_once(lambda: requests.post(unfollow_url, params=params))


def test_list_feeds(app):
    user = test_users[0]
    assert get_feeds(user) == []
    for feed in test_feeds:
        follow(user, feed)
    assert sorted(get_feeds(user)) == sorted(test_feeds)


def test_real_feeds(app):
    user = test_users[1]
    assert get_feeds(user) == []
    item_count = 0
    for feed in real_feeds:
        follow(user, feed)
        time.sleep(5)
        resp = requests.get(
            "/".join([HOST, "feed_items"]),
            params={"username": user, "feed_url": feed},
        )
        resp.raise_for_status()
        resp = resp.json()
        assert len(resp["items"]) > 0
        item_count += len(resp["items"])
    assert sorted(get_feeds(user)) == sorted(real_feeds)
    resp = requests.get("/".join([HOST, "all_items"]), params={"username": user})
    resp.raise_for_status()
    resp = resp.json()
    assert len(resp["items"]) == item_count


def test_updates(app):
    user = test_users[2]
    feed = "http://host.docker.internal:5000/feed?unit=second"
    follow(user, feed)
    time.sleep(5)
    total_items_value = get_items(user, feed, False)
    total_items = len(total_items_value)
    assert total_items > 0
    mark_as_read(user, feed, total_items_value[-1]["id"])
    for _ in range(5):
        time.sleep(2)
        current_items = len(get_items(user, feed, False))
        unread_items_value = get_items(user, feed, True)
        unread_items = len(unread_items_value)
        assert unread_items > 0
        assert unread_items < 4
        assert current_items > total_items
        assert total_items + unread_items <= current_items + 1
        total_items = current_items
        mark_as_read(user, feed, unread_items_value[-1]["id"])


def test_linkdown(app):
    class ProxyServer:
        class ProxyHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                # Can use rssgen instead of localhost here but it fail if run outside of docker compose
                url = "http://localhost:5000/feed?unit=second"
                resp = requests.get(url, headers=dict(self.headers))
                self.send_response(resp.status_code)
                for header in resp.headers.items():
                    self.send_header(*header)
                self.end_headers()
                self.wfile.write(resp.content)

        def __init__(self):
            self.server = http.server.HTTPServer(("", 5001), ProxyServer.ProxyHandler)

        def __enter__(self):
            self.thread = threading.Thread(target=self.server.serve_forever)
            self.thread.start()

        def __exit__(self, *args):
            self.server.shutdown()
            self.thread.join()

    user = test_users[3]
    feed = "http://host.docker.internal:5001"

    def check_updates(expect_fail, expect_items, read):
        update = get_updates(user, feed, True)
        assert update.get("failed", False) == expect_fail
        has_items = len(update["items"]) > 0
        assert has_items == expect_items
        if read:
            mark_as_read(user, feed, update["items"][-1]["id"])

    # 1. Get new items while proxy is on
    # 2. Get into failed state and no new items when proxy is off
    # 3. Stay in failed state and no new items when proxy is back on
    # 4. Get out of failed state and get new items after force update
    with ProxyServer():
        follow(user, feed)
        assert get_feeds(user) == [feed]
        time.sleep(3)
        check_updates(expect_fail=False, expect_items=True, read=False)
    time.sleep(5)
    check_updates(expect_fail=True, expect_items=True, read=True)
    check_updates(expect_fail=True, expect_items=False, read=False)
    with ProxyServer():
        time.sleep(5)
        check_updates(expect_fail=True, expect_items=False, read=False)
        resp = requests.post("/".join([HOST, "update_feed"]), params={"feed_url": feed})
        resp.raise_for_status()
        assert resp.json()["message"] == "Update requested"
        time.sleep(3)
        check_updates(expect_fail=False, expect_items=True, read=True)
        time.sleep(3)
        check_updates(expect_fail=False, expect_items=True, read=True)


def get_feeds(username):
    url = "/".join([HOST, "feeds"])
    resp = requests.get(url, params={"username": username})
    resp.raise_for_status()
    return resp.json()["feeds"]


def get_updates(user, feed, unread_only):
    resp = requests.get(
        "/".join([HOST, "feed_items"]),
        params={"username": user, "feed_url": feed, "unread_only": unread_only},
    )
    resp.raise_for_status()
    return resp.json()


def get_items(user, feed, unread_only):
    return get_updates(user, feed, unread_only)["items"]


def mark_as_read(user, feed, item_id):
    requests.post(
        "/".join([HOST, "mark_read"]),
        params={"username": user, "feed_url": feed, "item_id": item_id},
    ).raise_for_status()


def follow(user, feed):
    requests.post(
        "/".join([HOST, "follow"]), params={"username": user, "feed_url": feed}
    ).raise_for_status()
