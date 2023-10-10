#!/usr/bin/env python3

from collections import defaultdict
from pathlib import Path
import json
from dataclasses import dataclass
from typing import Dict, List, Tuple
import time

import lxml.html
import httpx

rare_gems = set(
    [
        "Empower Support",
        "Enlighten Support",
        "Enhance Support",
        "Elemental Penetration Support",
        "Block Chance Reduction Support",
        "Portal",
    ]
)


def get_cached(url: str, path: Path, max_age_hours: float) -> Path:
    if path.is_file():
        mtime = path.stat().st_mtime
        diff_hours = (time.time() - mtime) / (60 * 60)
        if diff_hours < max_age_hours:
            return path

    print(f"Updating {path}...")
    resp = httpx.get(url)
    resp.raise_for_status()
    with path.open("wt") as fp:
        fp.write(resp.text)

    return path


GemChances = Dict[str, Dict[str, float]]


def parse_poedb_gem_data(path: Path) -> GemChances:
    with path.open() as fp:
        html = lxml.html.parse(fp).getroot()

    div = html.get_element_by_id("UnusualGemsQuality")
    table = div.find(".//table")
    body = table.find("./tbody")
    gem_sums: Dict[str, int] = defaultdict(int)
    gem_weights: Dict[str, Dict[str, int]] = defaultdict(dict)
    for row in body.iterfind(".//tr"):
        cells = [i.text_content() for i in row.findall(".//td")]
        name = cells[0].strip()
        quality = cells[1].strip()
        weight = int(cells[3])
        if quality != "Superior":
            gem_sums[name] += weight
            gem_weights[name][quality] = weight
    gem_chances: GemChances = {}
    for name, weights in gem_weights.items():
        gem_chances[name] = {}
        for quality, weight in weights.items():
            gem_chances[name][quality] = weight / gem_sums[name]
    return gem_chances


@dataclass
class Gem:
    name: str
    quality_type: str
    is_vaal: bool
    is_corrupted: bool
    level: int
    quality: int
    price_chaos: float
    price_div: float
    count: int


def parse_gems(prices) -> List[Gem]:
    results = []
    qualities = ("Superior", "Anomalous", "Divergent", "Phantasmal")
    for gem in prices["lines"]:
        name = gem["name"]
        quality_type = qualities[0]
        for q in qualities:
            if name.startswith(q):
                quality_type = q
                name = name.split(" ", 1)[-1]
                break
        is_vaal = False
        if name.startswith("Vaal"):
            is_vaal = True
            name = name.split(" ", 1)[-1]
        corrupted = bool(gem.get("corrupted"))
        level = gem.get("gemLevel", 1)
        quality = gem.get("gemQuality", 0)
        res = Gem(
            name,
            quality_type,
            is_vaal,
            corrupted,
            level,
            quality,
            gem.get("chaosValue", 0.0),
            gem.get("divineValue", 0.0),
            gem.get("count", 0),
        )
        results.append(res)
    return results


def find_price(
    prices: List[Gem],
    name: str,
    quality_type: str,
    maxed: bool = False,
    min_amount: int = 10,
) -> float:
    results: List[Gem] = []
    for gem in prices:
        if gem.name != name or gem.quality_type != quality_type:
            continue
        if gem.is_corrupted:
            continue
        if maxed:
            if gem.level < 20:
                continue
            if gem.quality < 20:
                continue
        if gem.count < min_amount:
            continue
        results.append(gem)
    if not results:
        return 0
    results.sort(key=lambda g: g.price_div)
    return results[0].price_div


def find_best_options(
    all_chances,
    prices: List[Gem],
    maxed: bool,
    guaranteed_only: bool,
    min_amount: int,
    primary_regrading_lens: float,
    secondary_regrading_lens: float,
):
    good: List[Tuple[str, bool, float, list]] = []
    for name, chances in all_chances.items():
        if name in rare_gems:
            continue
        profits = []
        for quality_type, chance in chances.items():
            price = find_price(prices, name, quality_type, maxed, min_amount)
            profits.append((chance, price, quality_type))
        if name.endswith(" Support"):
            cost = secondary_regrading_lens
        else:
            cost = primary_regrading_lens
        if maxed:
            cost += find_price(prices, name, "Superior", maxed=True, min_amount=0)
        guaranteed = all(price > cost for _, price, _ in profits)
        profit = sum(chance * price for chance, price, _ in profits) - cost
        if guaranteed_only and not guaranteed:
            continue
        if profit <= 0:
            continue
        good.append((name, guaranteed, profit, profits))

    good.sort(key=lambda i: i[2], reverse=True)

    return good


def best_simple_gems(prices: List[Gem], count: int, min_amount: int) -> None:
    ok = []
    for gem in prices:
        if gem.quality_type != "Superior":
            continue
        if gem.name in rare_gems:
            continue
        if gem.is_corrupted:
            continue
        if gem.quality < 20:
            continue
        if gem.level < 20:
            continue
        if gem.count < min_amount:
            continue
        ok.append(gem)
    ok.sort(key=lambda g: g.price_chaos, reverse=True)

    for gem in ok[:count]:
        print(f"  {gem.name}: {gem.price_chaos:.1f} c")


def print_profits(
    all_chances: GemChances,
    prices: List[Gem],
    maxed: bool,
    guaranteed_only: bool,
    min_count: int,
    count: int,
    primary_regrading_lens: float,
    secondary_regrading_lens: float,
) -> None:
    best = find_best_options(
        all_chances,
        prices,
        guaranteed_only=guaranteed_only,
        maxed=maxed,
        min_amount=min_count,
        primary_regrading_lens=primary_regrading_lens,
        secondary_regrading_lens=secondary_regrading_lens,
    )
    for n, item in enumerate(best):
        if n > count:
            break
        name, guaranteed, profit, breakdown = item
        marker = "!!! " if guaranteed else ""
        details = ", ".join(
            f"{chance:.0%} {q} {price:.1f} div" for chance, price, q in breakdown
        )
        print(f"  {marker}{name}: {profit:.2f} div ({details})")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--min-amount", type=int, default=10, help="amount for sale to consider viable"
    )
    parser.add_argument(
        "--count", type=int, default=10, help="show this up to this many results"
    )
    parser.add_argument(
        "--guaranteed",
        action="store_true",
        help="only show gems that never result in a loss",
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=Path("data"), help="directory for caches"
    )
    parser.add_argument(
        "--gem-data-max-age-hours",
        type=float,
        default=168,
        help="maximum age of gem data from poedb (in hours)",
    )
    parser.add_argument(
        "--gem-prices-max-age-hours",
        type=float,
        default=12,
        help="maximum age of cached gem price data (in hours)",
    )
    parser.add_argument(
        "--exchange-rates-max-age-hours",
        type=float,
        default=12,
        help="maximum age of cached currency exchange rates (in hours)",
    )
    parser.add_argument("league")

    args = parser.parse_args()

    cache_dir: Path = args.cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)

    league = args.league

    gems_html_path = get_cached(
        "https://poedb.tw/us/Quality",
        cache_dir / "poedb_quality.html",
        args.gem_data_max_age_hours,
    )
    gem_prices_json_path = get_cached(
        f"https://poe.ninja/api/data/itemoverview?league={league}&type=SkillGem",
        cache_dir / f"gem_prices.{league}.json",
        args.gem_prices_max_age_hours,
    )
    currency_json_path = get_cached(
        f"https://poe.ninja/api/data/CurrencyOverview?league={league}&type=Currency&language=en",
        cache_dir / f"currency.{league}.json",
        args.exchange_rates_max_age_hours,
    )

    chances = parse_poedb_gem_data(gems_html_path)
    with gem_prices_json_path.open() as fp:
        prices = parse_gems(json.load(fp))

    buy_rates = {}
    with currency_json_path.open() as fp:
        raw = json.load(fp)
        for line in raw["lines"]:
            if "chaosEquivalent" not in line:
                continue
            buy_rates[line["currencyTypeName"]] = line["chaosEquivalent"]

    divine = buy_rates["Divine Orb"]
    prime_c = buy_rates["Prime Regrading Lens"]
    prime = prime_c / divine
    secondary_c = buy_rates["Secondary Regrading Lens"]
    secondary = secondary_c / divine
    print("Currency prices:")
    print(f"  Divine: {divine:.1f} c")
    print(f"  Primary: {prime:.1f} div ({prime_c:.1f} c)")
    print(f"  Secondary: {secondary:.1f} div ({secondary_c:.1f} c)")
    print()

    print("Regrading level 1 gems:")
    print_profits(
        chances,
        prices,
        maxed=False,
        guaranteed_only=args.guaranteed,
        min_count=args.min_amount,
        count=args.count,
        primary_regrading_lens=prime,
        secondary_regrading_lens=secondary,
    )
    print()

    print("Regrading level 20/20 gems:")
    print_profits(
        chances,
        prices,
        maxed=True,
        guaranteed_only=args.guaranteed,
        min_count=args.min_amount,
        count=args.count,
        primary_regrading_lens=prime,
        secondary_regrading_lens=secondary,
    )
    print()

    print("Leveling gems to 20/20:")
    best_simple_gems(prices, count=args.count, min_amount=args.min_amount)

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
