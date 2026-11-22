"""
モデル比較 2026-11: レポートの機械的な検査。

入力: work_export.json（export_runs.py の出力）、times.tsv（batch_verify.sh の記録）
出力: checks.csv（1レポート1行の集計）、findings.jsonl（引っかかった箇所の詳細。目視の確認用）
    python3 scripts/check_reports.py

検査は「疑わしい箇所を拾う」ためのもので、拾った箇所は本文を読んで確かめる（誤検出を除く）。
"""
import csv
import json
import os
import re
from collections import defaultdict
from itertools import permutations

W = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STAGED_HEADINGS = ['予測と実績・前年比較', '時間帯別の動向', '天候の影響考察', '運営上の出来事', '総括']
SINGLE_HEADINGS = ['予測と実績・前年比較', '時間帯別の動向', '天候の影響考察']
FORECAST_HEADINGS = ['予測と前年同期間の比較・トレンド分析', 'カレンダー（曜日配列）の影響', '天候シミュレーションとリスク評価']
WEATHER_GROUPS = ['強風', '猛暑日', '冬日', '雪']

NEGATIVE_COND = re.compile(r'該当しません|該当しなかった|該当せず|当てはまりません|当てはまらな|重なりませんでした|重なっていない|成立しません|成立しなかった')
ADVICE = re.compile(r'検討|推奨|おすすめ|お勧め|すべき|しましょう|が望まれ|が望ましい|必要があります|必要です|求められ|提案|施策|取り組|強化|見直|対策|促進|誘致|集客策|PR|告知|ことが重要')
CAUSAL = re.compile(r'(?:雨|天候|気象|気温|猛暑|強風|風|雪)[^。]{0,20}?(?:のため|が要因|が原因|によって|により|だから|で減|で増|影響した|影響し[、て]|寄与|せいで|押し下げ|押し上げ)')
FOOTER = re.compile(r'\n-{3,}\n\* \*\*Model\*\*.*\Z', re.S)
LEAK = re.compile(r'<think>|</think>|<\|[a-z_]+\|>|<channel\|>|\bassistantfinal\b|\banalysis\b')
# 日本語の字体と違う簡体字だけ（会・気 のように日本語でも使う字は入れない）
SIMPLIFIED = set('这们说时对过没发经现还样开关动气测据预计实际较长东车门问间题')
INSTRUCTION_COPY = re.compile(r'…|冒頭に上の数値表|1つ目の段落|2つ目の段落|【出力の形】|【作業】|見出しの文言|（###）|材料に「')
DATE_LIKE = re.compile(
    r'\d{4}\s*年(?:\s*\d{1,2}\s*月)?|\d{4}/\d{1,2}(?:/\d{1,2})?|\d{4}-\d{2}(?:-\d{2})?|\d{1,2}/\d{1,2}'
    r'|\d{1,2}\s*月\s*\d{1,2}\s*日|\d{1,2}\s*月|第\s*\d+|過去\s*\d+\s*年|\d+\s*年')
NUM = re.compile(r'\d+(?:\.\d+)?')


def load():
    raw = open(f'{W}/data/export.json', encoding='utf-8').read()
    data = json.loads(raw)
    rounds = {}
    for row in csv.DictReader(open(f'{W}/data/times.tsv', encoding='utf-8'), delimiter='\t'):
        if row['run_id'] not in ('', '-'):
            rounds[int(row['run_id'])] = row['round']
    return data, rounds


def norm(text):
    text = text.translate(str.maketrans('０１２３４５６７８９．，＋－−％', '0123456789.,+--%'))
    return re.sub(r'(?<=\d),(?=\d{3})', '', text)


def numbers(text):
    """日付らしいものを除いた数値（絶対値）"""
    text = DATE_LIKE.sub(' ', norm(text))
    return [m.group() for m in NUM.finditer(text)]


def source_values(texts):
    vals = set()
    for t in texts:
        for n in numbers(t):
            vals.add(float(n))
    return vals


def derived_values(vals):
    """差・比（%）・前年比の増減（%）。計算してよい種類のレポートで使う"""
    big = sorted(v for v in vals if v >= 10)
    out = set()
    for a, b in permutations(big, 2):
        out.add(abs(a - b))
        if b:
            out.add(a / b * 100)
            out.add(abs(a / b - 1) * 100)
    return out


def match(token, vals):
    x = float(token)
    decimals = len(token.split('.')[1]) if '.' in token else 0
    tol = 0.5 * 10 ** -decimals + 1e-9
    if x in vals:
        return 'exact'
    if any(abs(x - v) <= tol for v in vals):
        return 'rounded'
    return None


def split_tables(text):
    """表の塊（連続する | 行）と、それ以外の行に分ける"""
    blocks, other, cur = [], [], []
    for line in text.splitlines():
        if line.lstrip().startswith('|'):
            cur.append(line.strip())
        else:
            if cur:
                blocks.append(cur)
                cur = []
            other.append(line)
    if cur:
        blocks.append(cur)
    return blocks, other


def table_broken(block):
    cols = [len(line.strip().strip('|').split('|')) for line in block]
    has_sep = len(block) >= 2 and re.fullmatch(r'\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?', block[1]) is not None
    return (len(set(cols)) > 1) or not has_sep


def sections(lines):
    """見出しごとの本文の行"""
    out, name = defaultdict(list), '(前置き)'
    for line in lines:
        if re.match(r'^#{1,6}\s', line):
            name = line
            continue
        out[name].append(line)
    return out


def check_headings(lines, expected):
    heads = [l for l in lines if re.match(r'^#{1,6}\s', l)]
    res = {'missing': [], 'decorated': [], 'level': [], 'extra': []}
    used = set()
    for e in expected:
        hit = [h for h in heads if e in h]
        if not hit:
            res['missing'].append(e)
            continue
        h = hit[0]
        used.add(h)
        title = re.sub(r'^#{1,6}\s*', '', h).strip()
        title = re.sub(r'^\*\*(.*)\*\*$', r'\1', title).strip('「」 ')
        if title != e:
            res['decorated'].append(h)
        if not h.startswith('### '):
            res['level'].append(h)
    res['extra'] = [h for h in heads if h not in used]
    return res


def main():
    data, rounds = load()
    ctx = {(c['engine'], c['month']): c for c in data['contexts']}
    rows, findings = [], []

    for run in data['runs']:
        if run['status'] != 'done':
            continue
        engine = run['prompt_version'].split('/')[0]
        by_cls = {r['cls']: r['text'] for r in run['reports']}
        main_cls = 'forecast_1m' if engine == 'forecast' else 'review'
        # 末尾の版の表記（コードが付ける）は検査から外す
        text = FOOTER.sub('', by_cls[main_cls])
        month = run['reports'][0]['month']
        c = ctx[(engine, month)]
        prompts = {p['name']: p['text'] for p in c['prompts']}
        stage_out = {k.split(':')[1]: v for k, v in by_cls.items() if ':' in k}

        blocks, other = split_tables(text)
        known_tables = []
        if c.get('headline_table'):
            known_tables.append(c['headline_table'])
        known_tables += [t for _h, t in (c.get('section_tables') or [])]
        # 見出しの下の表は、説明の1行（*…*）と表でできている。表の行だけで突き合わせ、説明の行は本文から外す
        known_blocks = [[l.strip() for l in t.splitlines() if l.lstrip().startswith('|')] for t in known_tables]
        captions = {l.strip() for t in known_tables for l in t.splitlines()
                    if l.strip() and not l.lstrip().startswith('|')}
        own_tables = [b for b in blocks if b not in known_blocks]
        broken = [b for b in blocks if table_broken(b)]
        other = [l for l in other if l.strip() not in captions]

        narrative = [l for l in other if not re.match(r'^#{1,6}\s', l)]
        body_text = '\n'.join(narrative)
        n_chars = len(re.sub(r'\s', '', body_text))

        expected = {'staged': STAGED_HEADINGS, 'single': SINGLE_HEADINGS, 'forecast': FORECAST_HEADINGS}[engine]
        head = check_headings(other, expected)

        # 数値の根拠
        src_texts = list(prompts.values()) + list(stage_out.values())
        vals = source_values(src_texts)
        der = derived_values(vals) if engine in ('forecast', 'single') else derived_values(vals)
        num_stats = defaultdict(int)
        for line in narrative:
            for tok in numbers(line):
                kind = match(tok, vals) or ('derived' if match(tok, der) else 'ungrounded')
                num_stats[kind] += 1
                if kind in ('ungrounded', 'derived'):
                    findings.append({'run_id': run['run_id'], 'check': f'number_{kind}', 'value': tok,
                                     'line': line.strip()[:200]})

        row = {
            'run_id': run['run_id'], 'round': rounds.get(run['run_id'], ''), 'model': run['model'],
            'engine': engine, 'month': month[:7], 'chars': n_chars,
            'num_exact': num_stats['exact'], 'num_rounded': num_stats['rounded'],
            'num_derived': num_stats['derived'], 'num_ungrounded': num_stats['ungrounded'],
            'head_missing': len(head['missing']), 'head_decorated': len(head['decorated']),
            'head_level': len(head['level']), 'head_extra': len(head['extra']),
            'tables': len(blocks), 'own_tables': len(own_tables), 'broken_tables': len(broken),
        }
        for h in head['decorated'] + head['level'] + head['extra']:
            findings.append({'run_id': run['run_id'], 'check': 'heading', 'line': h})
        for e in head['missing']:
            findings.append({'run_id': run['run_id'], 'check': 'heading_missing', 'line': e})
        for b in own_tables:
            findings.append({'run_id': run['run_id'], 'check': 'own_table', 'line': ' / '.join(b[:3])})
        for b in broken:
            findings.append({'run_id': run['run_id'], 'check': 'broken_table', 'line': ' / '.join(b[:3])})

        # 指示を守ったか
        def flag(name, regex, scope_lines):
            hits = [l.strip() for l in scope_lines if regex.search(l)]
            for l in hits:
                findings.append({'run_id': run['run_id'], 'check': name, 'line': l[:200]})
            return len(hits)

        row['advice'] = flag('advice', ADVICE, narrative)
        row['causal'] = flag('causal', CAUSAL, narrative)
        row['negative_cond'] = flag('negative_cond', NEGATIVE_COND, narrative)
        row['instruction_copy'] = flag('instruction_copy', INSTRUCTION_COPY, other)
        row['leak'] = flag('leak', LEAK, other)
        simp = [ch for ch in text if ch in SIMPLIFIED]
        row['simplified_zh'] = len(simp)
        if simp:
            findings.append({'run_id': run['run_id'], 'check': 'simplified_zh', 'line': ''.join(simp)})
        en = re.findall(r'[A-Za-z][A-Za-z ,\'-]{24,}', body_text)
        row['english_runs'] = len(en)
        for e in en:
            findings.append({'run_id': run['run_id'], 'check': 'english', 'line': e[:120]})

        if engine == 'staged':
            secs = sections(other)
            row['headline_table_verbatim'] = int(c['headline_table'] in text)
            # 見出しごとの【分析総括】と引用数
            missing_summary, over3 = 0, 0
            for e in STAGED_HEADINGS[:4]:
                key = next((k for k in secs if e in k), None)
                if key is None:
                    continue
                sec_text = '\n'.join(secs[key])
                if e == '運営上の出来事' and not c['has_remark']:
                    ok = sec_text.strip() == '所見の登録はありません。'
                    row['no_remark_ok'] = int(ok)
                    if not ok:
                        findings.append({'run_id': run['run_id'], 'check': 'no_remark_text', 'line': sec_text.strip()[:200]})
                    continue
                if '【分析総括】' not in sec_text:
                    missing_summary += 1
                    findings.append({'run_id': run['run_id'], 'check': 'summary_missing', 'line': key})
                n = sum(len(numbers(l)) for l in secs[key])
                if n > 3:
                    over3 += 1
            row['summary_missing'] = missing_summary
            row['sections_over3_numbers'] = over3
            # 観察に無い天候の群
            wprompt = prompts.get('weather', '')
            shown = [g for g in WEATHER_GROUPS if re.search(g + r'[・の]', wprompt.split('【出力の形】')[-1])]
            wkey = next((k for k in secs if '天候の影響考察' in k), None)
            unseen = []
            if wkey:
                wtext = '\n'.join(secs[wkey])
                for g in WEATHER_GROUPS:
                    if g not in shown and re.search(g, wtext.replace('真冬日', '')):
                        unseen.append(g)
            row['unseen_weather_group'] = len(unseen)
            for g in unseen:
                findings.append({'run_id': run['run_id'], 'check': 'unseen_weather_group', 'line': g,
                                 'shown': shown})
            row['member_notice'] = int('■ 客層の注意' in prompts['summary'])
            row['member_line'] = int('会員台帳' in text)

        if engine == 'forecast':
            p = prompts['main']
            fc = int(re.search(r'メイン予測値.*?: (\d+)人', p).group(1))
            prev = int(re.search(r'前年同期間の実績: (\d+)人', p).group(1))
            row['forecast_below_prev'] = int(fc < prev)

        rows.append(row)

    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(f'{W}/results/checks.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    with open(f'{W}/results/findings.jsonl', 'w', encoding='utf-8') as f:
        for x in findings:
            f.write(json.dumps(x, ensure_ascii=False) + '\n')
    print(len(rows), 'reports,', len(findings), 'findings')


main()
