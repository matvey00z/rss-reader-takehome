#!/bin/sh

cd ..
sudo docker compose up --build --force-recreate -d
sudo docker compose logs --follow > test/logs.txt &

cd -
sudo docker compose up --build --force-recreate

cd ..
sudo docker compose down

wait