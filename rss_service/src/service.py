from fastapi import FastAPI, HTTPException
import os

import db as db_handler
import updater


db = db_handler.DB(
    os.environ["DBHOST"],
    os.environ["DBPORT"],
    os.environ["DBUSER"],
    os.environ["DBPASSWORD"],
    create=True,
)

app = FastAPI()


@app.get("/healthcheck")
def healthcheck():
    """Check that the service is up and running"""
    return {"message": "ok"}


@app.post("/add_user")
def add_user(username: str):
    """Add new user

    Return codes: 200 on success, 400 when user already exists
    """
    try:
        db.add_user(username)
    except db_handler.UserAlreadyExists:
        raise HTTPException(status_code=400, detail="User already exists")
    return {"message": "User added successfully"}


@app.post("/follow")
def follow_feed(username: str, feed_url: str):
    """Follow a feed
    
    Following the same feed more than once has no effect
    Return code: 200 on success, 500 when user is not found
    """
    try:
        new_follow, new_feed = db.follow_feed(username, feed_url)
        updater.start_updating_feed(feed_url)
    except db_handler.UserNotFound as e:
        # User management is out of scope of this service so missing user is some kind
        # internal logic error or a race condition
        raise HTTPException(status_code=500, detail="User not found")
    if new_follow:
        return {"message": "Feed followed successfully"}
    else:
        return {"message": "Feed already followed"}


@app.post("/unfollow")
def unfollow_feed(username: str, feed_url: str):
    """Unfollow a feed

    Return code: 200 on success, 500 when user not found, 400 when feed not followed
    """
    try:
        unfollowed = db.unfollow_feed(username, feed_url)
    except db_handler.UserNotFound:
        raise HTTPException(status_code=500, detail="User not found")
    if not unfollowed:
        raise HTTPException(status_code=400, detail="No such feed for a user")
    return {"message": "Feed unfollowed"}


@app.get("/feeds")
async def list_feeds(username: str):
    """List user's feeds
    
    Return code: 200 on success, 500 when user not found
    Return content: {"feeds": [feed_url]}
    """
    try:
        feeds = db.list_feeds(username)
    except db_handler.UserNotFound:
        raise HTTPException(status_code=500, detail="User not found")
    return {"feeds": feeds}


@app.get("/feed_items")
async def list_feed_items(username: str, feed_url: str, unread_only: bool = False):
    """List user's items filtered by feed, possibly unread only

    Return code: 200 on success, 500 when user not found, 400 when feed not followed
    Return content: {"items": [{"id": id, "content": content}], "failed": bool}.
                    Item content is json encoded entry object from feedparser.
    """
    try:
        items = db.get_feed_items(username, feed_url, unread_only)
    except db_handler.UserNotFound:
        raise HTTPException(status_code=500, detail="User not found")
    except db_handler.FeedNotFound:
        raise HTTPException(status_code=400, detail="Feed not found")
    return {"items": items["items"], "failed": items.get("failed")}


@app.get("/all_items")
async def list_all_items(username: str, unread_only: bool = False):
    """List user's items from all feeds, possibly unread only

    Return code: 200 on success, 500 when user not found
    Return content: {"items": [{"id": id, "content": content}], "failed": [failed_feed_url]}.
                    Item content is json encoded entry object from feedparser.
    """
    try:
        items = db.get_all_items(username, unread_only)
    except db_handler.UserNotFound:
        raise HTTPException(status_code=500, detail="User not found")
    return {"items": items["items"], "failed": items.get("failed")}


@app.post("/mark_read")
async def mark_as_read(username: str, feed_url: str, item_id: int):
    """Mark items up to @item_id as read

    Return code: 200 on success, 500 when user not found, 400 when feed not found
    """
    try:
        db.mark_as_read(username, feed_url, item_id)
    except db_handler.UserNotFound:
        raise HTTPException(status_code=500, detail="User not found")
    except db_handler.FeedNotFound:
        raise HTTPException(status_code=400, detail="Feed not found")
    return {"message": "Marked as read"}


@app.post("/update_feed")
async def update_feed(feed_url: str):
    """Force update failed feed

    Calling this method for a not failed feed has no effect
    Return code: 200 on success, 400 when feed not found
    """
    try:
        need_update = db.request_feed_update(feed_url)
    except db_handler.FeedNotFound:
        raise HTTPException(status_code=400, detail="Feed not found")
    if need_update:
        updater.start_updating_feed(feed_url)
        return {"message": "Update requested"}
    return {"message": "Update not needed"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RSS reader service")

    parser.add_argument(
        "--dbhost",
        type=str,
        help="Postgres server hostname or IP address",
        required=True,
    )
    parser.add_argument(
        "--dbport", type=int, help="Postgres server port", required=True
    )
    parser.add_argument("--dbuser", type=str, help="Postgres user", required=True)
    parser.add_argument(
        "--dbpassword", type=str, help="Postgres password", required=True
    )

    args = parser.parse_args()
