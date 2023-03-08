#!/bin/sh

sudo docker compose up --build --force-recreate -d
sudo docker compose logs --follow > test/logs.txt &

python -m pytest -v --html=test/report.html --self-contained-html test/

sudo docker compose down

wait