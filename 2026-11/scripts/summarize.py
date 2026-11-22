import os
"""
モデル比較 2026-11: 所要時間と自動の検査をモデル別に集計する。
    python3 scripts/summarize.py

出力: summary_speed.csv / summary_checks.csv（と標準出力に Markdown の表）
"""
import csv
import statistics
from collections import defaultdict

W = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 最後の2つは追加の測定（thinking OFF）。IQ3_S の thinking OFF はモデル名が同じなので、段階（phase）で分けて名前に印を付ける
IQ_OFF = 'qwen3.8-flash-next-iq3_s [thinking OFF]'
ORDER = ['gemma-4-12b-it-qat', 'gemma-4-31b-it-qat', 'qwen3.8-27b-ud-q4_k_m', 'llm-jp-4.1-33b-thinking', 'qwen3.8-flash-next-iq3_s',
         'qwen3.8-flash-next-unsloth-ud-q4_k_xl', IQ_OFF]
SERVER = {m: 'llama.cpp' for m in ORDER[:4]}
for m in ORDER[4:]:
    SERVER[m] = 'Strata'


def label(model, phase):
    return IQ_OFF if phase.startswith('strataiq') else model


times = list(csv.DictReader(open(f'{W}/data/times.tsv', encoding='utf-8'), delimiter='\t'))
phase_of = {int(t['run_id']): t['phase'] for t in times if t['run_id'] not in ('', '-')}
speed = defaultdict(list)
warm = defaultdict(list)
for t in times:
    m = label(t['model'], t['phase'])
    if t['kind'] == 'warmup':
        warm[m].append(float(t['sec']))
        continue
    kind = 'forecast' if t['kind'] == 'forecast_1m' else f"review {t['engine']}"
    speed[(kind, m)].append(float(t['sec']))

rows = []
print('| 種類 | モデル | 推論サーバ | 件数 | 中央値 | 最小〜最大 |\n|---|---|---|---|---|---|')
for kind in ('forecast', 'review staged', 'review single'):
    for m in ORDER:
        v = speed.get((kind, m))
        if not v:
            continue
        row = {'kind': kind, 'model': m, 'server': SERVER[m], 'n': len(v),
               'median': round(statistics.median(v)), 'min': round(min(v)), 'max': round(max(v))}
        rows.append(row)
        print(f"| {kind} | {m} | {SERVER[m]} | {row['n']} | {row['median']} | {row['min']}〜{row['max']} |")
with open(f'{W}/results/summary_speed.csv', 'w', encoding='utf-8', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

print('\nウォームアップ（読み込み）:', {m: warm[m] for m in ORDER})

checks = list(csv.DictReader(open(f'{W}/results/checks.csv', encoding='utf-8')))
keys = ['chars', 'num_derived', 'num_ungrounded', 'head_missing', 'head_decorated', 'head_extra', 'own_tables',
        'broken_tables', 'advice', 'causal', 'negative_cond', 'instruction_copy', 'leak', 'simplified_zh',
        'english_runs', 'summary_missing', 'sections_over3_numbers', 'unseen_weather_group', 'headline_table_verbatim']
agg = []
for engine in ('forecast', 'staged', 'single'):
    for m in ORDER:
        rs = [r for r in checks if r['engine'] == engine
              and label(r['model'], phase_of.get(int(r['run_id']), '')) == m]
        if not rs:
            continue
        row = {'engine': engine, 'model': m, 'n': len(rs)}
        for k in keys:
            vals = [float(r[k]) for r in rs if r.get(k) not in (None, '')]
            if not vals:
                continue
            row[k] = round(statistics.median(vals)) if k == 'chars' else int(sum(vals))
        agg.append(row)
allk = []
for r in agg:
    for k in r:
        if k not in allk:
            allk.append(k)
with open(f'{W}/results/summary_checks.csv', 'w', encoding='utf-8', newline='') as f:
    w = csv.DictWriter(f, fieldnames=allk)
    w.writeheader()
    w.writerows(agg)
print()
for r in agg:
    print(r)
