#!/usr/bin/env python3

from collections import defaultdict
from pathlib import Path
import json
from dataclasses import dataclass

import lxml.html

rare_gems = set([
    'Empower Support',
    'Enlighten Support',
    'Enhance Support',
    'Elemental Penetration Support',
    'Block Chance Reduction Support',
    'Portal',
])


def get_file_data(path: Path):
    with path.open() as fp:
        html = lxml.html.parse(fp).getroot()

    div = html.get_element_by_id('GrantedEffectQualityStatsQualityGem')
    table = div.find('.//table')
    body = table.find('./tbody')
    gem_sums = defaultdict(int)
    gem_weights = defaultdict(dict)
    for row in body.iterfind('.//tr'):
        cells = [i.text_content() for i in row.findall('.//td')]
        name = cells[0].strip()
        quality = cells[1].strip()
        weight = int(cells[3])
        if quality != 'Superior':
            gem_sums[name] += weight
            gem_weights[name][quality] = weight
    gem_chances = {}
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
    price_ex: float
    count: int


def parse_gems(prices) -> list[Gem]:
    results = []
    qualities = ('Superior', 'Anomalous', 'Divergent', 'Phantasmal')
    for gem in prices['lines']:
        name = gem['name']
        quality_type = qualities[0]
        for q in qualities:
            if name.startswith(q):
                quality_type = q
                name = name.split(' ', 1)[-1]
                break
        is_vaal = False
        if name.startswith('Vaal'):
            is_vaal = True
            name = name.split(' ', 1)[-1]
        corrupted = bool(gem.get('corrupted'))
        level = gem.get('gemLevel', 1)
        quality = gem.get('gemQuality', 0)
        res = Gem(name, quality_type, is_vaal, corrupted, level, quality,
                  gem.get('chaosValue', 0.0), gem.get('exaltedValue', 0.0),
                  gem.get('count', 0))
        results.append(res)
    return results


def find_price(prices: list[Gem],
               name: str,
               quality_type: str,
               maxed: bool = False,
               min_amount: int = 10):
    results = []
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
    results.sort(key=lambda g: g.price_ex)
    return results[0].price_ex


def find_best_options(all_chances, prices: list[Gem], maxed: bool,
                      guaranteed_only: bool, min_amount: int,
                      primary_regrading_lens: float,
                      secondary_regrading_lens: float):
    # 2021-11-12, prime regrading lens: 0.5ex, secondary: 0.6
    good: list[tuple[str, bool, float, list]] = []
    for name, chances in all_chances.items():
        if name in rare_gems:
            continue
        profits = []
        for quality_type, chance in chances.items():
            price = find_price(prices, name, quality_type, maxed, min_amount)
            profits.append((chance, price, quality_type))
        if name.endswith(' Support'):
            cost = secondary_regrading_lens
        else:
            cost = primary_regrading_lens
        if maxed:
            cost += find_price(prices, name, 'Superior', True)
        guaranteed = all(price > cost for _, price, _ in profits)
        profit = sum(chance * price for chance, price, _ in profits) - cost
        if guaranteed_only and not guaranteed:
            continue
        if profit <= 0:
            continue
        good.append((name, guaranteed, profit, profits))

    good.sort(key=lambda i: i[2], reverse=True)

    return good


def best_simple_gems(prices: list[Gem], count, min_amount):
    ok = []
    for gem in prices:
        if gem.quality_type != 'Superior':
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
        print(f'  {gem.name}: {gem.price_chaos:.1f} c')


def print_profits(all_chances, prices: list[Gem], maxed: bool,
                  guaranteed_only: bool, min_count: int, count: int,
                  primary_regrading_lens: float,
                  secondary_regrading_lens: float):
    best = find_best_options(all_chances,
                             prices,
                             guaranteed_only=guaranteed_only,
                             maxed=maxed,
                             min_amount=min_count,
                             primary_regrading_lens=primary_regrading_lens,
                             secondary_regrading_lens=secondary_regrading_lens)
    for n, item in enumerate(best):
        if n > count:
            break
        name, guaranteed, profit, breakdown = item
        marker = '!!! ' if guaranteed else ''
        details = ', '.join(f'{chance:.0%} {q} {price:.1f} ex'
                            for chance, price, q in breakdown)
        print(f'  {marker}{name}: {profit:.2f} ex ({details})')


def main():
    import argparse

    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--min-amount',
                        type=int,
                        default=10,
                        help='amount for sale to consider viable')
    parser.add_argument('--count',
                        type=int,
                        default=10,
                        help='show this up to this many results')
    parser.add_argument('--guaranteed',
                        action='store_true',
                        help='only show gems that never result in a loss')
    parser.add_argument('--gems-html',
                        type=Path,
                        default='data/poedb_quality.html')
    parser.add_argument('--prices-json',
                        type=Path,
                        default='data/gem_prices.json')
    parser.add_argument('--currency-json',
                        type=Path,
                        default='data/currency.json')

    args = parser.parse_args()

    chances = get_file_data(args.gems_html)
    with args.prices_json.open() as fp:
        prices = parse_gems(json.load(fp))

    buy_rates = {}
    with args.currency_json.open() as fp:
        raw = json.load(fp)
        for line in raw['lines']:
            if 'chaosEquivalent' not in line:
                continue
            buy_rates[line['currencyTypeName']] = line['chaosEquivalent']

    exalt = buy_rates['Exalted Orb']
    prime_c = buy_rates['Prime Regrading Lens']
    prime = prime_c / exalt
    secondary_c = buy_rates['Secondary Regrading Lens']
    secondary = secondary_c / exalt
    print('Currency prices:')
    print(f'  Exalt: {exalt:.1f} c')
    print(f'  Primary: {prime:.1f} ex ({prime_c:.1f} c)')
    print(f'  Secondary: {secondary:.1f} ex ({secondary_c:.1f} c)')
    print()

    print('Regrading level 1 gems:')
    print_profits(chances,
                  prices,
                  maxed=False,
                  guaranteed_only=args.guaranteed,
                  min_count=args.min_amount,
                  count=args.count,
                  primary_regrading_lens=prime,
                  secondary_regrading_lens=secondary)
    print()

    print('Regrading level 20/20 gems:')
    print_profits(chances,
                  prices,
                  maxed=True,
                  guaranteed_only=args.guaranteed,
                  min_count=args.min_amount,
                  count=args.count,
                  primary_regrading_lens=prime,
                  secondary_regrading_lens=secondary)
    print()

    print('Leveling gems to 20/20:')
    best_simple_gems(prices, count=args.count, min_amount=args.min_amount)

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
