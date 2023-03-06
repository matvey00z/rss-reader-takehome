# RSS reader (take home assignment)

See the task description in RSS_reader.pdf

## Running

To run use docker-compose.yml, for example, run in the top directory:
```
docker compose up
```
Now the service is available on http://localhost:8000

## Testing

To run tests, run `bash test/test.sh` 

## Overview

There are a few components here.

- For the storage PostgreSQL is used
- The main service uses FastAPI (see `rss_service/src/service.py`)
- The main service also runs the feed updates in the background via dramatiq (see `rss_service/src/updater.py`)
- The updaters one time initialization is also in `rss_service/src/updater.py`