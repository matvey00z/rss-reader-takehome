#!/bin/sh

cd ..
docker compose up --build --force-recreate -d
docker compose logs --follow > test/logs.txt &

cd -
timeout 60 docker compose up --build --force-recreate --abort-on-container-exit

cd ..
docker compose down

wait