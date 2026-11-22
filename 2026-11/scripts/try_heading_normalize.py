"""
改良案: まとめの段の見出しを、決まった文言に置き換える後処理（report_review_staged の sub_find_heading の延長）。
保存済みの本文に当てて、何件が変わり、変えてはいけない行を変えていないかを確かめる（推論はしない）。
    python3 scripts/try_heading_normalize.py
"""
import json
import os
import re

HEADINGS = ['予測と実績・前年比較', '時間帯別の動向', '天候の影響考察', '運営上の出来事', '総括']

W = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def normalize(text):
    out, changed = [], []
    for line in text.splitlines():
        if line.startswith('#'):
            title = re.sub(r'^#+\s*', '', line).strip()
            for h in HEADINGS:
                # 見出しの文言で始まり、後ろに飾り（…、空白、記号）が付いただけの行に限る
                if title.startswith(h) and re.fullmatch(re.escape(h) + r'[\s…:：。.、\-－—*]*', title):
                    new = '### ' + h
                    if new != line:
                        changed.append((line, new))
                    line = new
                    break
        out.append(line)
    return '\n'.join(out), changed


raw = open(os.path.join(W, 'data', 'export.json'), encoding='utf-8').read()
data = json.loads(raw)
n_reports = n_changed = 0
for run in data['runs']:
    if not run['prompt_version'].startswith('staged/'):
        continue
    text = next(r['text'] for r in run['reports'] if r['cls'] == 'review')
    n_reports += 1
    _new, changed = normalize(text)
    if changed:
        n_changed += 1
        for old, new in changed:
            print(run['run_id'], repr(old), '->', repr(new))
print(f'staged {n_reports} 件のうち、見出しが変わったのは {n_changed} 件')
