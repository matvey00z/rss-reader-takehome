#!/bin/sh

sudo docker compose up --build --force-recreate -d
sudo docker compose logs --follow > test/logs.txt &

python -m pytest test/

sudo docker compose down

wait