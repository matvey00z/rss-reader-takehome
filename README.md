# RSS reader (take home assignment)

See the task description in RSS_reader.pdf

## Running

To run use docker-compose.yml, for example, run in the top directory:
```
docker compose up
```
Now the service is available on http://localhost:8000, with the docs at http://127.0.0.1:8000/docs#/.
The openapi docs is in `openapi.json`

## Testing

To run tests, go into `test/` directory and run `bash test.sh` . Test report will appear in test/report/report.html.

## Overview

There are a few components here.

- For the storage PostgreSQL is used
- The main service uses FastAPI (see `rss_service/src/service.py`)
- The main service also runs the feed updates in the background via dramatiq (see `rss_service/src/updater.py`)
- The updaters one time initialization is also in `rss_service/src/updater.py`


## Motivation and points for improvement

- User auth and management is not a part of this service; the assumption is that it is handled by some external service. Hence no checks are made, and if a user is not found a code 500 is given.
- The service is relatively small so I went with just API testing and no unit tests (unit testing here would be tricky and require some mocking and other things, and API testing gives a reasonable coverage)
- The updating service needs some persistance and checks: asynchronous service restarts might break things as for now
- Database and requests need some optimization: there are places with multiple requests instead of one which gives worse performance and possible race conditions (which are not fatal at those places although not a good thing anyway); also it is worth to make the DB requests async (e.g. with asyncpg) as it will give us the FastAPI async power
- Metrics, benchmarking, load testing are always a nice thing to have