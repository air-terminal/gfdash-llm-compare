"""
同じ月・同じ種類のレポートを、モデルごとに並べた Markdown にする（目視で読むため）。
    python3 scripts/render_side_by_side.py

出力: reading/<engine>_<YYYY-MM>.md。staged は段ごとの出力も付ける。
"""
import csv
import json
import os
from collections import defaultdict

W = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
raw = open(f'{W}/data/export.json', encoding='utf-8').read()
data = json.loads(raw)
rounds = {}
for row in csv.DictReader(open(f'{W}/data/times.tsv', encoding='utf-8'), delimiter='\t'):
    if row['run_id'] not in ('', '-'):
        rounds[int(row['run_id'])] = row['round']

groups = defaultdict(list)
for run in data['runs']:
    if run['status'] != 'done':
        continue
    engine = run['prompt_version'].split('/')[0]
    month = run['reports'][0]['month'][:7]
    groups[(engine, month)].append(run)

os.makedirs(f'{W}/data/side_by_side', exist_ok=True)
for (engine, month), runs in sorted(groups.items()):
    out = [f'# {engine} {month}\n']
    for run in runs:
        out.append(f'\n\n## {run["model"]} (run {run["run_id"]}, round {rounds.get(run["run_id"], "?")})\n')
        by_cls = {r['cls']: r['text'] for r in run['reports']}
        main = 'forecast_1m' if engine == 'forecast' else 'review'
        out.append(by_cls[main])
        for k in ('review:attendance', 'review:weather', 'review:factors'):
            if k in by_cls:
                out.append(f'\n\n<details><summary>{k}</summary>\n\n{by_cls[k]}\n\n</details>')
    with open(f'{W}/data/side_by_side/{engine}_{month}.md', 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
print(len(groups), 'files')
