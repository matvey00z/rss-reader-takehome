import pytest
import requests
from requests.exceptions import ConnectionError
import time

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
        follow_url = "/".join([HOST, "follow"])
        feed_url = feed
        params = {"username": user, "feed_url": feed}
        requests.post(follow_url, params=params)
    assert sorted(get_feeds(user)) == sorted(test_feeds)


def test_real_feeds(app):
    user = test_users[1]
    assert get_feeds(user) == []
    item_count = 0
    for feed in real_feeds:
        requests.post(
            "/".join([HOST, "follow"]), params={"username": user, "feed_url": feed}
        ).raise_for_status()
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
    requests.post(
        "/".join([HOST, "follow"]), params={"username": user, "feed_url": feed}
    ).raise_for_status()
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


def get_feeds(username):
    url = "/".join([HOST, "feeds"])
    resp = requests.get(url, params={"username": username})
    resp.raise_for_status()
    return resp.json()["feeds"]


def get_items(user, feed, unread_only):
    resp = requests.get(
        "/".join([HOST, "feed_items"]),
        params={"username": user, "feed_url": feed, "unread_only": unread_only},
    )
    resp.raise_for_status()
    return resp.json()["items"]


def mark_as_read(user, feed, item_id):
    requests.post(
        "/".join([HOST, "mark_read"]),
        params={"username": user, "feed_url": feed, "item_id": item_id},
    ).raise_for_status()
