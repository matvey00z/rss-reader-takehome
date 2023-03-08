#!/bin/sh

cd ..
docker compose up --build --force-recreate -d
docker compose logs --follow > test/logs.txt &

cd -
docker compose up --build --force-recreate

cd ..
docker compose down

wait