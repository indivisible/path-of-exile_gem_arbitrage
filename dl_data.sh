#! /bin/sh

LEAGUE="Ancestor"

set -e

[ -d "data" ] || mkdir "data"

wget -O "data/poedb_quality.html" "https://poedb.tw/us/Quality"
wget -O "data/gem_prices.json" "https://poe.ninja/api/data/itemoverview?league=$LEAGUE&type=SkillGem"
wget -O "data/currency.json" "https://poe.ninja/api/data/CurrencyOverview?league=$LEAGUE&type=Currency&language=en"
