"""
所見の解析の追加の測定（probe_remark_parse.py → remark_parse.jsonl）をモデル別に集計する。
    python3 scripts/summarize_remark_parse.py

見る点:
  - sample: 公開版の bench_remark_parse の期待値に合った件数（5件中）
  - demo:   期間（開始・終了）と種類がすべて正解と一致した件数（9件中）
            係数を出した件数と、そのうち向きが正解と合った件数。
            デモの所見の文章には来場者数の数量が書かれていない（2025-06 は料金、2025-09 は打席数の割合）。
            係数を出した件は、文章に無い数量をモデルが置いたことになる
  - 「要確認」: 画面と同じ根拠の検査（com_check_grounding）が出した注意の件数
"""
import csv
import json
import os
import statistics
from collections import defaultdict

W = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORDER = ['gemma-4-12b-it-qat', 'gemma-4-31b-it-qat', 'qwen3.8-27b-ud-q4_k_m', 'llm-jp-4.1-33b-thinking',
         'qwen3.8-flash-next-iq3_s', 'qwen3.8-flash-next-unsloth-ud-q4_k_xl',
         'gpt-oss-20b-mxfp4', 'gemma-4-26b-a4b-it-qat', 'qwen3.6-27b-q4_k_m']

rows = [json.loads(l) for l in open(f'{W}/results/remark_parse.jsonl', encoding='utf-8')]
by = defaultdict(list)
for r in rows:
    by[r['model']].append(r)

out = []
print('| モデル | サンプルの期待一致 | デモの期間・種類の一致 | 係数を出した（向きが合った） | 要確認 | 応答失敗 | 1件の秒（中央値） | 読み込み（秒） |')
print('|---|---|---|---|---|---|---|---|')
for m in ORDER:
    rs = by.get(m, [])
    if not rs:
        continue
    samples = [r for r in rs if r['set'] == 'sample']
    demos = [r for r in rs if r['set'] == 'demo']
    warm = [r['seconds'] for r in rs if r['set'] == 'warmup']
    s_ok = sum(1 for r in samples if r.get('ok'))
    d_ok = sum(1 for r in demos if all(r.get(k) for k in ('n_events_ok', 'type_ok', 'start_ok', 'end_ok')))
    f_given = sum(1 for r in demos if r.get('factor_given'))
    f_dir = sum(1 for r in demos if r.get('direction_ok'))
    grounding = sum(len(r.get('grounding') or []) for r in samples + demos)
    failed = sum(1 for r in samples + demos if r.get('error'))
    secs = [r['seconds'] for r in samples + demos if 'error' not in r]
    row = {'model': m, 'sample_ok': f'{s_ok}/{len(samples)}', 'demo_period_ok': f'{d_ok}/{len(demos)}',
           'demo_factor_given': f_given, 'demo_direction_ok': f_dir, 'grounding_notes': grounding,
           'failed': failed, 'median_seconds': round(statistics.median(secs), 1) if secs else '',
           'load_seconds': warm[0] if warm else ''}
    out.append(row)
    print(f"| {m} | {row['sample_ok']} | {row['demo_period_ok']} | {f_given}（{f_dir}） | {grounding} | {failed} | "
          f"{row['median_seconds']} | {row['load_seconds'] or '—'} |")

with open(f'{W}/results/summary_remark_parse.csv', 'w', encoding='utf-8', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(out[0]))
    w.writeheader()
    w.writerows(out)

print('\n外れた件:')
for r in rows:
    if r['set'] == 'sample' and not r.get('ok'):
        print(' ', r['model'], r['key'], r.get('error') or '; '.join(r.get('reasons', [])))
    if r['set'] == 'demo' and not all(r.get(k) for k in ('n_events_ok', 'type_ok', 'start_ok', 'end_ok')):
        ev = [(e['type'], e['start_date'], e['end_date']) for e in r.get('events', [])]
        print(' ', r['model'], r['key'], r.get('error') or ev, '正解', r.get('truth'))
