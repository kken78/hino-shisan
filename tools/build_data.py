#!/usr/bin/env python3
"""固定資産台帳（令和6年度末時点）の材料を検算し、画面が読む data.js を作る（標準ライブラリのみ）。

材料（inputs.lock.json に、リポジトリ・コミット・パス・sha256 を記録）:
  hino-town-docs  data/struct/kotei-shisan.tsv              固定資産台帳の資産の行の値（DOCS_SCHEMA.md §13.14）
                  data/struct/audit/kotei.tsv               資産の行の値の検収の台帳（§13.10）
                  data/struct/issues/zaisei-r6-kotei.tsv    原典の誤りの記録（§13.11。財務書類との照合の差）
                  data/text_raw/zaisei-r6-zaimu.txt         財務書類4表の原典の文字（附属明細書①②を読む）
                  data/text_raw/zaisei-r6-zaimu-gaiyou.txt  財務書類4表の概要の原典の文字（有形固定資産減価償却率を読む）
                  data/text/zaisei-r6-kotei/01.tsv          台帳の原典の文字（1行目の作成日だけを読む）
                  data/sources.tsv                          町の公開資料の台帳（3つの資料の題・url・bytes・sha256）

材料は、このリポジトリと同じフォルダにある hino-town-docs（../hino-town-docs）から読む。
別の場所にあるときは --src <フォルダ> か環境変数 HINO_SRC で、hino-town-docs を置いたフォルダを指定する。

検算（DESIGN.md ADR-1）:
  1. inputs.lock.json の sha256 と、いまのファイルが一致する。hino-town-docs の材料が1つの commit にそろう
  2. kotei-shisan.tsv の列の見出しが §13.14 の表と同じ。行が EXPECTED_ROWS で、財産番号と財産枝番の組が重ならない。
     金額の列が整数、取得年度の西暦の読み替えが和暦の字と同じ、財産番号の頭の字が種類の表にある
  3. すべての行が、検収の台帳に同じ照合キー（table・row・cols・value・unit・source。§13.10）であり、checked が ✓
  4. 1円の行の区分を4つの列から付け直し、kubun_1en と同じ。どの行もちょうど1つの区分に当たる。5区分の行の合計＝全行
  5. 期首簿価＋当期取得額−当期減価償却額−当期除売却＋当期評価増減等＝期末簿価 が全行で成り立つ
  6. 種類ごと・目的ごと・5区分ごとの和（行・取得価額・減価償却累計額・期末簿価）の計＝全行の計。
     5年ごとの棒の和＋棒に入れなかった行の和＝工作物・建物の全行の和
  7. 財務書類との照合（§13.14「A 財務書類との照合」。hino-town-docs の tools/kotei.py zaimu と同じ規則をここで書き直した）:
     一般会計の行（ソフトウェアを除く）を補助科目名称と目的別資産区分でまとめ、附属明細書①②の額と比べる。
     差が、原典の誤りの記録（status が 未判断 か 原典のまま持つ）の where に書いた額とちょうど同じ。
     記録に無い差、記録にあって差の無い区分があれば止める。明細の中の検算（D＝A＋B−C、G＝D−E、区分の和）も行う
  8. 一般会計の償却する有形固定資産の行から計算した有形固定資産減価償却率を小数1桁にした値が、
     財務書類4表の概要の「有形固定資産減価償却率」の行の令和6年度の値と同じ
  9. 資料の台帳に zaisei-r6-kotei・zaisei-r6-zaimu・zaisei-r6-zaimu-gaiyou の行があり、url・bytes・sha256 がある
 10. data.js の大きさが 16MB 以下
どれかが合わなければ data.js を書かずに終了コード 1 で止まる。
"""
import argparse, collections, csv, hashlib, io, json, os, pathlib, re, sys, unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
TD = 'hino-town-docs'
DOC = 'zaisei-r6-kotei'                 # 固定資産台帳（令和6年度末時点）
ZDOC = 'zaisei-r6-zaimu'                # 同じ年度の財務書類4表
GDOC = 'zaisei-r6-zaimu-gaiyou'         # 財務書類4表の概要
FY = 2024                               # 台帳の時点の年度（令和6年度）
FY_LABEL = '令和6年度'
EXPECTED_ROWS = 9896
P = {
    'shisan': 'data/struct/kotei-shisan.tsv',
    'audit': 'data/struct/audit/kotei.tsv',
    'issues': f'data/struct/issues/{DOC}.tsv',
    'zaimu': f'data/text_raw/{ZDOC}.txt',
    'gaiyou': f'data/text_raw/{GDOC}.txt',
    'raw': f'data/text/{DOC}/01.tsv',
    'sources': 'data/sources.tsv',
}
MAX_BYTES = 16 * 1024 * 1024

# ---- DOCS_SCHEMA §13.14 の表（hino-town-docs tools/kotei.py の SHISAN と同じ列の順） ----
SHISAN_COLS = ['doc', 'page', 'row', 'zaisan_no', 'edaban', 'name', 'kaikei_name', 'shukan', 'shozai', 'hojo',
               'mokuteki', 'toroku', 'shokyaku', 'biboh', 'yoto', 'kozo', 'kaisu', 'taiyo', 'suryo', 'tani', 'menseki',
               'shutoku_nendo', 'shutoku_nendo_y', 'shutoku_date', 'shutoku_kagaku', 'kishu', 'gensho_ruikei',
               'toki_shutoku', 'toki_gensho', 'toki_jobaikyaku', 'toki_hyoka', 'kimatsu', 'jobaikyaku_nendo',
               'jobaikyaku_date', 'kubun_1en', 'unit', 'note']
AUDIT_VALUE_COLS = [c for c in SHISAN_COLS if c not in ('doc', 'page', 'row', 'zaisan_no', 'edaban', 'unit', 'note')]
AUDIT_COLS = ['key', 'table', 'row', 'cols', 'value', 'unit', 'source', 'checked', 'reviewer', 'date', 'note']
ISSUE_COLS = ['no', 'kind', 'page', 'where', 'issue', 'evidence', 'confidence', 'status', 'action']
MONEY = ['shutoku_kagaku', 'kishu', 'gensho_ruikei', 'toki_shutoku', 'toki_gensho', 'toki_jobaikyaku', 'toki_hyoka', 'kimatsu']
NUM_RE = re.compile(r'^-?[0-9]+(\.[0-9]+)?$')
INT_RE = re.compile(r'^-?[0-9]+$')
ZAISAN_RE = re.compile(r'^(.+)_([0-9]{7})_([0-9]{1,4})$')
NENDO_RE = re.compile(r'^(明治|大正|昭和|平成|令和)(元|[0-9]+)年度$')
ERA = {'明治': 1867, '大正': 1911, '昭和': 1925, '平成': 1988, '令和': 2018}

# 1円の行の区分（§13.14 の表の順）
KUBUN = ['価額のある資産', '償却を終えて1円を残した資産', '価額が0の資産', '1円で載せた土地', '1円で載せた償却資産']

# 種類：財産番号の頭の字 → 画面の種類（DESIGN.md ADR-1。問5 案A）
KIND_OF_ATAMA = {'土地': '土地', '建物': '建物', '工作物': '工作物', '物品': '物品',
                 '建仮': '建設仮勘定', '建仮_工作物': '建設仮勘定', 'ソフト': 'ソフトウェア'}
KINDS = ['土地', '建物', '工作物', '物品', '建設仮勘定', 'ソフトウェア']
# 頭の字の種類と、補助科目名称の対応（分け方の違う行を数えて注に書くため）
HOJO_OF_KIND = {'土地': {'土地', 'その他（公共土地）', '道路（公共土地）', '公園（公共土地）'},
                '建物': {'建物', 'その他（公共建物）'}, '工作物': {'工作物', 'その他（公共工作物）'},
                '物品': {'物品'}, '建設仮勘定': {'建設仮勘定', '公共用財産建設仮勘定'}, 'ソフトウェア': {'ソフトウェア'}}
AGE_KINDS = ['工作物', '建物']           # 取得の時期の棒（問8）
AGE_FIRST_TO = 1964                      # 1964年度以前を1本
AGE_STEP = 5

# ---- 財務書類との照合（§13.14 A。hino-town-docs tools/kotei.py と同じ規則） ----
HOJO = {
    '土地': ('事業用資産', '土地'), '建物': ('事業用資産', '建物'), '工作物': ('事業用資産', '工作物'),
    '建設仮勘定': ('事業用資産', '建設仮勘定'),
    'その他（公共土地）': ('インフラ資産', '土地'), '道路（公共土地）': ('インフラ資産', '土地'),
    '公園（公共土地）': ('インフラ資産', '土地'), 'その他（公共建物）': ('インフラ資産', '建物'),
    'その他（公共工作物）': ('インフラ資産', '工作物'), '公共用財産建設仮勘定': ('インフラ資産', '建設仮勘定'),
    '物品': ('物品', ''),
}
NOT_TANGIBLE = ('ソフトウェア',)
MEISAI_ROWS = [('事業用資産', ''), ('事業用資産', '土地'), ('事業用資産', '立木竹'), ('事業用資産', '建物'),
               ('事業用資産', '工作物'), ('事業用資産', '船舶'), ('事業用資産', '浮標等'), ('事業用資産', '航空機'),
               ('事業用資産', 'その他'), ('事業用資産', '建設仮勘定'), ('インフラ資産', ''), ('インフラ資産', '土地'),
               ('インフラ資産', '建物'), ('インフラ資産', '工作物'), ('インフラ資産', 'その他'), ('インフラ資産', '建設仮勘定'),
               ('物品', ''), ('合計', '')]
NON_DEPR = ('土地', '立木竹', '建設仮勘定')
SEC_TITLE = {'附属明細書': '一般会計等', '全体附属明細書': '全体', '連結附属明細書': '連結'}
TOK_RE = re.compile(r'^(-|[0-9]{1,3}(?:,[0-9]{3})*)$')
KAIKEI = '一般会計'
MEISAI = '一般会計等'
SONOTA = 'その他'
ISSUE_HEAD = 'A 財務書類との照合 '
ISSUE_STATUS = ('未判断', '原典のまま持つ')
COL1 = ('取得価額', '減価償却累計額', '期末簿価')
ISSUE_ITEM_RE = re.compile(r'^(①|②)(.+?) 差 (-?[0-9][0-9,]*)$')
RATE_LABEL = '有形固定資産減価償却率'

ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
ap.add_argument('--src', default=os.environ.get('HINO_SRC') or str(ROOT.parent),
                help='hino-town-docs を置いたフォルダ（既定は環境変数 HINO_SRC、無ければこのリポジトリの親）')
args = ap.parse_args()
SRC = pathlib.Path(args.src).resolve()

errors = []


def fail_now():
    print('\n'.join(errors[:200]))
    if len(errors) > 200:
        print(f'…ほか {len(errors) - 200}件')
    print(f'検算 NG（{len(errors)}件）。data.js は書き出していません。')
    sys.exit(1)


def read_tsv(text, name, columns=None):
    if text.startswith('﻿') or '\r' in text:
        errors.append(f'{name}: BOM か CR がある')
        return []
    lines = text.splitlines()
    head = lines[0].split('\t') if lines else []
    if columns is not None and head != columns:
        errors.append(f'{name}: 列の見出しが決まった形でない（{head[:6]}…）')
        return []
    return list(csv.DictReader(io.StringIO(text), delimiter='\t'))


def row_key(*a):  # DOCS_SCHEMA §13.10（hino-town-docs tools/kozo.py の row_key と同じ作り方）
    return hashlib.sha256('\x1f'.join(a).encode('utf-8')).hexdigest()[:16]


def nendo_y(s):
    m = NENDO_RE.match(s)
    if not m:
        return None
    return ERA[m.group(1)] + (1 if m.group(2) == '元' else int(m.group(2)))


def wareki(y):
    """西暦の年度を和暦の年度の字にする（画面の表の補い。「元」は1）。"""
    for era, base in (('令和', 2018), ('平成', 1988), ('昭和', 1925), ('大正', 1911), ('明治', 1867)):
        if y > base:
            n = y - base
            return era, ('元' if n == 1 else str(n))
    return None


def kubun_hits(r):
    sk, bb, a, k = r['shokyaku'], r['biboh'], int(r['shutoku_kagaku']), int(r['kimatsu'])
    out = []
    if sk == '償却対象でない' and a == 1:
        out.append('1円で載せた土地')
    if sk == '償却対象' and a == 1:
        out.append('1円で載せた償却資産')
    if sk == '償却対象' and bb == '1円残しする' and a > 1 and k == 1:
        out.append('償却を終えて1円を残した資産')
    if a > 1 and k > 1:
        out.append('価額のある資産')
    if a == 0 or k == 0:
        out.append('価額が0の資産')
    return out


# 1. lock --------------------------------------------------------------------
lock = json.loads((ROOT / 'inputs.lock.json').read_text(encoding='utf-8'))
files = {}
commits = set()
for ent in lock['inputs']:
    repo_dir = ent['repo'].split('/')[-1]
    p = SRC / repo_dir / ent['path']
    tag = f"{repo_dir}/{ent['path']}"
    if repo_dir == TD:
        commits.add(ent['commit'])
    if not p.is_file():
        errors.append(f'lock: {tag} がない（{p}）')
        continue
    b = p.read_bytes()
    h = hashlib.sha256(b).hexdigest()
    if h != ent['sha256']:
        errors.append(f"lock: {tag} の sha256 が違う（lock {ent['sha256'][:12]}… / いま {h[:12]}…。"
                      f"lock の commit は {ent['commit'][:7]}）")
    files[ent['path']] = b.decode('utf-8')
if len(commits) != 1:
    errors.append(f'lock: hino-town-docs の commit が1つでない（{sorted(commits)}）')
for k, path in P.items():
    if path not in files and not any(e.startswith(f'lock: {TD}/{path}') for e in errors):
        errors.append(f'lock: {TD}/{path} が inputs.lock.json に載っていない')
if errors:
    fail_now()
COMMIT = commits.pop()

# 9. 資料の台帳 ------------------------------------------------------------------
srows = {r['id']: r for r in read_tsv(files[P['sources']], 'sources.tsv')}
SRC_DOCS = {}
for d in (DOC, ZDOC, GDOC):
    r = srows.get(d)
    if r is None:
        errors.append(f'資料の台帳: {d} の行が無い')
        continue
    if not r['url'].startswith('https://') or not r['bytes'].isdigit() or not re.fullmatch(r'[0-9a-f]{64}', r['sha256']):
        errors.append(f'資料の台帳: {d} の url・bytes・sha256 のどれかが無い')
        continue
    SRC_DOCS[d] = {'id': d, 'title': r['title'], 'url': r['url'], 'page_url': r['page_url'], 'format': r['format'],
                   'bytes': int(r['bytes']), 'fetched': r['fetched']}
if errors:
    fail_now()

# 台帳の作成日（原典の文字の1行目） -------------------------------------------------
first = files[P['raw']].split('\n', 1)[0].split('\t')
if len(first) < 5 or first[0] != '固定資産一覧表' or first[3] != '作成日:' or not re.fullmatch(r'[0-9]{4}/[0-9]{2}/[0-9]{2}', first[4]):
    errors.append(f'台帳の原典の文字: 1行目が「固定資産一覧表 … 作成日: YYYY/MM/DD」の形でない（{first[:5]}）')
    fail_now()
SAKUSEI = first[4]

# 2. 資産の行 ------------------------------------------------------------------
rows = read_tsv(files[P['shisan']], 'kotei-shisan.tsv', SHISAN_COLS)
if errors:
    fail_now()
if len(rows) != EXPECTED_ROWS:
    errors.append(f'資産の行: {len(rows)}行（{EXPECTED_ROWS}行でない）')
seen = set()
for r in rows:
    k = (r['zaisan_no'], r['edaban'])
    tag = f"{r['zaisan_no']}/{r['edaban']}"
    if r['doc'] != DOC or r['page'] != '01':
        errors.append(f'資産の行 {tag}: doc・page が {DOC}・01 でない')
    if k in seen:
        errors.append(f'資産の行 {tag}: 財産番号と財産枝番の組が重なる')
    seen.add(k)
    for c in MONEY:
        if not INT_RE.match(r[c]):
            errors.append(f'資産の行 {tag}: {c} が整数でない（{r[c]!r}）')
    for c in ('kaisu', 'taiyo', 'suryo', 'menseki'):
        if r[c] and not NUM_RE.match(r[c]):
            errors.append(f'資産の行 {tag}: {c} が数でない（{r[c]!r}）')
    m = ZAISAN_RE.match(r['zaisan_no'])
    if not m or m.group(1) not in KIND_OF_ATAMA:
        errors.append(f'資産の行 {tag}: 財産番号の頭の字が種類の表に無い')
    if not r['shutoku_nendo_y'].isdigit() or nendo_y(r['shutoku_nendo']) != int(r['shutoku_nendo_y']):
        errors.append(f"資産の行 {tag}: 取得年度の読み替えが和暦の字と合わない（{r['shutoku_nendo']} / {r['shutoku_nendo_y']}）")
if errors:
    fail_now()
for r in rows:
    for c in MONEY:
        r[c] = int(r[c])
    r['y'] = int(r['shutoku_nendo_y'])
    r['kind'] = KIND_OF_ATAMA[ZAISAN_RE.match(r['zaisan_no']).group(1)]
    r['rid'] = f"{r['doc']}/{r['zaisan_no']}/{r['edaban']}"

# 3. 検収の台帳 -------------------------------------------------------------------
ledger = read_tsv(files[P['audit']], 'audit/kotei.tsv', AUDIT_COLS)
if errors:
    fail_now()
by_key = {}
for a in ledger:
    if a['table'] == 'kotei-shisan':
        by_key[a['key']] = a
reviewers = collections.Counter()
audit_last = ''
for r in rows:
    vals = [str(r[c]) for c in AUDIT_VALUE_COLS]
    k = row_key('kotei-shisan', r['rid'], ','.join(AUDIT_VALUE_COLS), '|'.join(vals), '', f"{DOC} 01!R{r['row']}")
    a = by_key.get(k)
    if a is None:
        errors.append(f"検収の台帳: {r['rid']} の行が台帳に無い（値か出典が台帳と違う。key {k}）")
        continue
    if a['row'] != r['rid'] or a['checked'] != '✓':
        errors.append(f"検収の台帳: {r['rid']} が検収済みでない（checked={a['checked']!r}）")
        continue
    reviewers[a['reviewer']] += 1
    audit_last = max(audit_last, a['date'])
if len(by_key) != len(rows):
    errors.append(f'検収の台帳: kotei-shisan の行が {len(by_key)}（資産の行 {len(rows)} と違う）')
if errors:
    fail_now()

# 4. 1円の行の区分 / 5. 期首から期末 ----------------------------------------------------
for r in rows:
    hits = kubun_hits(r)
    if len(hits) != 1 or hits[0] != r['kubun_1en']:
        errors.append(f"1円の行の区分: {r['rid']} が {hits} に当たる（kubun_1en は {r['kubun_1en']!r}）")
    if r['kishu'] + r['toki_shutoku'] - r['toki_gensho'] - r['toki_jobaikyaku'] + r['toki_hyoka'] != r['kimatsu']:
        errors.append(f"期首から期末: {r['rid']} で 期首簿価＋当期取得額−当期減価償却額−当期除売却＋当期評価増減等＝期末簿価 が合わない")
if errors:
    fail_now()
KI = {k: i for i, k in enumerate(KUBUN)}


def zero():
    return {'n': 0, 'acq': 0, 'ruikei': 0, 'kimatsu': 0}


def add(s, r):
    s['n'] += 1
    s['acq'] += r['shutoku_kagaku']
    s['ruikei'] += r['gensho_ruikei']
    s['kimatsu'] += r['kimatsu']


def with_kubun(rs):
    """行の和と、5区分ごとの和（区分の順。行の無い区分も 0 で持つ）。"""
    s = zero()
    kb = [zero() for _ in KUBUN]
    for r in rs:
        add(s, r)
        add(kb[KI[r['kubun_1en']]], r)
    s['kubun'] = [[x['n'], x['acq'], x['ruikei'], x['kimatsu']] for x in kb]
    return s


def sums_match(name, parts, whole):
    for c in ('n', 'acq', 'ruikei', 'kimatsu'):
        if sum(p[c] for p in parts) != whole[c]:
            errors.append(f'検算: {name} の {c} の計 {sum(p[c] for p in parts):,} が全体 {whole[c]:,} と違う')


# 6. 集計 ---------------------------------------------------------------------
total = with_kubun(rows)
sums_match('5区分', [{'n': x[0], 'acq': x[1], 'ruikei': x[2], 'kimatsu': x[3]} for x in total['kubun']], total)

kinds = []
for kd in KINDS:
    rs = [r for r in rows if r['kind'] == kd]
    s = with_kubun(rs)
    s['name'] = kd
    s['n1en'] = sum(1 for r in rs if r['shutoku_kagaku'] == 1)
    kinds.append(s)
sums_match('種類', kinds, total)
kinds.sort(key=lambda s: -s['acq'])
mismatch = collections.Counter((r['kind'], r['hojo']) for r in rows if r['hojo'] not in HOJO_OF_KIND[r['kind']])
kind_hojo = [{'kind': k, 'hojo': h, 'n': n} for (k, h), n in sorted(mismatch.items(), key=lambda x: -x[1])]

# 目的ごと（一般会計の有形固定資産。枝番の読み替えは §13.14 A と同じ。問4・問6）
base0 = {(r['doc'], r['zaisan_no']): r for r in rows if r['edaban'] == '0'}


def mokuteki_of(r):
    m = r['mokuteki']
    if m == '' and r['edaban'] != '0':
        b = base0.get((r['doc'], r['zaisan_no']))
        if b is not None:
            m = b['mokuteki']
    return m


gen = [r for r in rows if r['kaikei_name'] == KAIKEI]
tang = [r for r in gen if r['hojo'] not in NOT_TANGIBLE]
moved = [r['rid'] for r in tang if r['mokuteki'] == '' and mokuteki_of(r) != '']
pur = collections.defaultdict(list)
for r in tang:
    pur[mokuteki_of(r)].append(r)
depr = lambda rs: [r for r in rs if r['shokyaku'] == '償却対象']


def rate_of(rs):
    d = depr(rs)
    ru, ki = sum(r['gensho_ruikei'] for r in d), sum(r['kimatsu'] for r in d)
    return len(d), ru, ki


# 7. 財務書類との照合 ---------------------------------------------------------------
def tok_num(t):
    return 0 if t == '-' else int(t.replace(',', ''))


def num_line(ln, n):
    toks = ln.split()
    if len(toks) == n and all(TOK_RE.match(x) for x in toks):
        return toks
    return None


def label(k):
    return k[0] + (' ' + k[1] if k[1] else '')


def read_meisai(text):
    lines = [x.strip() for x in text.replace('\f', '\n').split('\n')]
    out = {'①': {}, '②': None}
    sec = None
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln in SEC_TITLE:
            sec = SEC_TITLE[ln]
        if ln.startswith('①有形固定資産の明細') and '（単位：円）' in ln and sec != '連結':
            j = i + 1
            while j < len(lines) and num_line(lines[j], 7) is None:
                j += 1
            vals = []
            while j < len(lines) and len(vals) < len(MEISAI_ROWS):
                t = num_line(lines[j], 7)
                if t is None:
                    break
                vals.append([tok_num(x) for x in t])
                j += 1
            if sec is None or len(vals) != len(MEISAI_ROWS):
                errors.append(f'財務書類: {i + 1}行目の①有形固定資産の明細の数の行が {len(vals)}（{len(MEISAI_ROWS)} でない）')
                return out
            out['①'][sec] = dict(zip(MEISAI_ROWS, vals))
            i = j
            continue
        if ln.startswith('②有形固定資産の行政目的別明細') and '（単位：円）' in ln:
            if sec != MEISAI:
                errors.append(f'財務書類: {i + 1}行目の②行政目的別明細が一般会計等の附属明細書の中に無い')
                return out
            j, head = i + 1, []
            while j < len(lines) and not any(TOK_RE.match(x) for x in lines[j].split()[:1]):
                head.append(lines[j])
                j += 1
            cols = ' '.join(head).replace('・ ', '・').split()
            vals = []
            while j < len(lines) and len(vals) < len(MEISAI_ROWS):
                t = num_line(lines[j], len(cols))
                if t is None:
                    break
                vals.append([tok_num(x) for x in t])
                j += 1
            if not cols or cols[-1] != '合計' or len(vals) != len(MEISAI_ROWS):
                errors.append(f'財務書類: {i + 1}行目の②行政目的別明細の列の見出しか数の行が読めない')
                return out
            out['②'] = {'cols': cols, 'rows': dict(zip(MEISAI_ROWS, vals))}
            i = j
            continue
        i += 1
    return out


m = read_meisai(files[P['zaimu']])
if errors:
    fail_now()
if MEISAI not in m['①'] or not m['②']:
    errors.append('財務書類: 一般会計等の①有形固定資産の明細か②行政目的別明細が無い')
    fail_now()
for sec, rs in m['①'].items():
    for k, v in rs.items():
        a, b, c, d, e, f, g = v
        if a + b - c != d or d - e != g:
            errors.append(f'財務書類: {sec} {label(k)} の D＝A＋B−C か G＝D−E が合わない')
        if k[1] in NON_DEPR and (e or f):
            errors.append(f'財務書類: {sec} {label(k)} は減価償却しない区分なのに E か F が 0 でない')
    for parent in ('事業用資産', 'インフラ資産'):
        sub = [v for k, v in rs.items() if k[0] == parent and k[1]]
        if [sum(x) for x in zip(*sub)] != rs[(parent, '')]:
            errors.append(f'財務書類: {sec} {parent} の内訳の和が合わない')
    if [x + y + z for x, y, z in zip(rs[('事業用資産', '')], rs[('インフラ資産', '')], rs[('物品', '')])] != rs[('合計', '')]:
        errors.append(f'財務書類: {sec} 合計が 事業用資産＋インフラ資産＋物品 と合わない')
g1 = m['①'][MEISAI]
for k, v in m['②']['rows'].items():
    if g1[k][6] != v[-1]:
        errors.append(f'財務書類: ② {label(k)} の合計が①の差引本年度末残高（G）と合わない')
unknown = sorted({r['hojo'] for r in gen if r['hojo'] not in HOJO and r['hojo'] not in NOT_TANGIBLE})
if unknown:
    errors.append(f'財務書類との照合: 補助科目名称 {unknown} の明細の区分が §13.14 の表に無い')
if errors:
    fail_now()

# 原典の誤りの記録
issues = read_tsv(files[P['issues']], f'issues/{DOC}.tsv', ISSUE_COLS)
if errors:
    fail_now()
rids = {r['rid'] for r in rows}
allow = collections.defaultdict(list)
issue_out = []
for it in issues:
    issue_out.append({'no': it['no'], 'kind': it['kind'], 'page': it['page'], 'where': it['where'],
                      'issue': it['issue'], 'status': it['status']})
    if it['status'] not in ISSUE_STATUS or not it['where'].startswith(ISSUE_HEAD):
        continue
    body, _, tail = it['where'][len(ISSUE_HEAD):].partition('。')
    mm = re.fullmatch(r'kotei-shisan (\S+)', tail.strip())
    if not mm or mm.group(1) not in rids:
        errors.append(f"原典の誤りの記録 no.{it['no']}: where の「。」のあとの kotei-shisan の row が台帳に無い")
    for item in body.split('、'):
        x = ISSUE_ITEM_RE.match(item.strip())
        if not x:
            errors.append(f"原典の誤りの記録 no.{it['no']}: 「{item}」が「<区分> 差 <額>」の形でない")
            continue
        if x.group(1) == '①':
            lab, _, col = x.group(2).rpartition(' ')
            if col not in COL1 or not any(label(k) == lab and k[1] for k in MEISAI_ROWS):
                errors.append(f"原典の誤りの記録 no.{it['no']}: 「{item}」の①の区分が明細の内訳の行と列でない")
                continue
        allow[x.group(1) + x.group(2)].append((it['no'], int(x.group(3).replace(',', ''))))
if errors:
    fail_now()


def allowed(cell):
    return sum(v for _, v in allow.get(cell, []))


def allowed_nos(cell):
    return [n for n, _ in allow.get(cell, [])]


def allowed1(k, ci):
    if k[1]:
        return allowed(f'①{label(k)} {COL1[ci]}')
    kids = [x for x in MEISAI_ROWS if x[1] and (k[0] == '合計' or x[0] == k[0])]
    return sum(allowed(f'①{label(x)} {COL1[ci]}') for x in kids)


def allowed1_nos(k, ci):
    if k[1]:
        return allowed_nos(f'①{label(k)} {COL1[ci]}')
    kids = [x for x in MEISAI_ROWS if x[1] and (k[0] == '合計' or x[0] == k[0])]
    return sorted({n for x in kids for n in allowed_nos(f'①{label(x)} {COL1[ci]}')})


agg = collections.defaultdict(zero)
for r in tang:
    k = HOJO[r['hojo']]
    add(agg[k], r)
    if k[1]:
        add(agg[(k[0], '')], r)
    add(agg[('合計', '')], r)
used = set()
one = []
for k, v in g1.items():
    s = agg.get(k, zero())
    dd = (s['acq'] - v[3], s['ruikei'] - v[4], s['kimatsu'] - v[6])
    al = tuple(allowed1(k, ci) for ci in range(3))
    if k[1]:
        used.update(f'①{label(k)} {c}' for c in COL1)
    if s['n'] == 0 and not any(v) and not any(al):
        continue
    if dd != al:
        errors.append(f'財務書類との照合: ①{label(k)} の差 {dd} が原典の誤りの記録の額 {al} と違う')
    one.append({'group': k[0], 'name': k[1], 'n': s['n'],
                'daicho': [s['acq'], s['ruikei'], s['kimatsu']], 'meisai': [v[3], v[4], v[6]],
                'issues': [allowed1_nos(k, ci) for ci in range(3)]})
cols2 = m['②']['cols']
tot2 = m['②']['rows'][('合計', '')]
mk = collections.defaultdict(lambda: [0, 0])
for r in tang:
    g = mokuteki_of(r) or SONOTA
    mk[g][0] += 1
    mk[g][1] += r['kimatsu']
two = []
for c in list(cols2[:-1]) + sorted(x for x in mk if x not in cols2):
    n, s = mk.get(c, [0, 0])
    v = tot2[cols2.index(c)] if c in cols2 else None
    al = allowed('②' + c)
    used.add('②' + c)
    if s - (v or 0) != al:
        errors.append(f'財務書類との照合: ②{c} の差 {s - (v or 0):,} が原典の誤りの記録の額 {al:,} と違う')
    two.append({'name': c, 'n': n, 'daicho': s, 'meisai': v, 'issues': allowed_nos('②' + c)})
s_all = sum(x[1] for x in mk.values())
if s_all - tot2[-1] != allowed1(('合計', ''), 2):
    errors.append(f'財務書類との照合: ②合計の差 {s_all - tot2[-1]:,} が原典の誤りの記録の額と違う')
two.append({'name': '合計', 'n': sum(x[0] for x in mk.values()), 'daicho': s_all, 'meisai': tot2[-1],
            'issues': allowed1_nos(('合計', ''), 2)})
for cell in sorted(set(allow) - used):
    errors.append(f'財務書類との照合: 記録の区分「{cell}」が明細の区分と目的に無い')
naibu = []   # ②の明細の中の食い違い（目的の列の和と合計の列）
for k, v in m['②']['rows'].items():
    if sum(v[:-1]) != v[-1]:
        naibu.append({'name': label(k), 'sum': sum(v[:-1]), 'total': v[-1]})
if errors:
    fail_now()

# 目的ごとの表（節3）。並びは取得価額の多い順。明細②に列の無い目的（空欄・警察など）は最後に原典の字のまま
purposes = []
for g, rs in pur.items():
    s = with_kubun(rs)
    dn, ru, ki = rate_of(rs)
    s.update({'name': g, 'in_meisai': g in cols2[:-1], 'dn': dn, 'druikei': ru, 'dkimatsu': ki,
              'issues': allowed_nos('②' + g) if g else []})
    purposes.append(s)
sums_match('目的（一般会計の有形固定資産）', purposes, with_kubun(tang))
purposes.sort(key=lambda s: (not s['in_meisai'], -s['acq']))

# 8. 有形固定資産減価償却率 ------------------------------------------------------------
dn, ru, ki = rate_of(tang)
rate_x10 = (ru * 1000 * 2 + (ru + ki)) // (2 * (ru + ki))   # 小数1桁に四捨五入（整数で計算）
gl = [unicodedata.normalize('NFKC', x).strip() for x in files[P['gaiyou']].replace('\f', '\n').split('\n')]
gaiyou = None
for i, ln in enumerate(gl):
    if ln.startswith(RATE_LABEL + ' '):
        vals = ln[len(RATE_LABEL):].split()
        head = re.findall(r'令和(元|[0-9]+)年度', gl[i - 1]) if i else []
        if len(head) == len(vals) and all(re.fullmatch(r'[0-9]+\.[0-9]', v) for v in vals):
            gaiyou = {('令和' + h + '年度'): v for h, v in zip(head, vals)}
            break
if not gaiyou or FY_LABEL not in gaiyou:
    errors.append(f'財務書類の概要: 「{RATE_LABEL}」の行と年度の見出しが読めない')
    fail_now()
# 概要の「有形固定資産の行政目的別割合」の総務の値（画面の注に使う。この指標は画面に載せない。DESIGN.md ADR-1）
somu = None
for i, ln in enumerate(gl):
    if '有形固定資産の行政目的別割合' in ln:
        for ln2 in gl[i + 1:i + 40]:
            if ln2.startswith('総務 '):
                somu = ln2.split()[-1]
                break
        break
if somu is None or not re.fullmatch(r'[0-9]+(\.[0-9]+)?', somu):
    errors.append('財務書類の概要: 「有形固定資産の行政目的別割合」の総務の行が読めない')
    fail_now()
page_of = [p for p in files[P['gaiyou']].split('\f')]
g_pdf = next(i + 1 for i, p in enumerate(page_of) if RATE_LABEL + ' ' in unicodedata.normalize('NFKC', p))
g_printed = unicodedata.normalize('NFKC', page_of[g_pdf - 1]).strip().split('\n', 1)[0].strip()
w_pdf = next(i + 1 for i, p in enumerate(page_of) if '有形固定資産の行政目的別割合' in p)
w_printed = unicodedata.normalize('NFKC', page_of[w_pdf - 1]).strip().split('\n', 1)[0].strip()
if not (g_printed.isdigit() and w_printed.isdigit()):
    errors.append(f'財務書類の概要: ページの番号が読めない（{g_printed!r}・{w_printed!r}）')
    fail_now()
if f'{rate_x10 // 10}.{rate_x10 % 10}' != gaiyou[FY_LABEL]:
    errors.append(f"減価償却率: 台帳から計算した {rate_x10 // 10}.{rate_x10 % 10} が概要の {FY_LABEL} の値 {gaiyou[FY_LABEL]} と違う")
    fail_now()
z_pdf = next(i + 1 for i, p in enumerate(files[P['zaimu']].split('\f')) if '②有形固定資産の行政目的別明細' in p)

# 取得の時期（節4） ----------------------------------------------------------------
bins = [{'from': None, 'to': AGE_FIRST_TO}]
y = AGE_FIRST_TO + 1
while y <= FY:
    bins.append({'from': y, 'to': min(y + AGE_STEP - 1, FY)})
    y += AGE_STEP
for b in bins:
    e2 = wareki(b['to'])
    if b['from'] is None:
        b['label'] = f"{b['to']}以前"
        b['wareki'] = f'{e2[0]}{e2[1]}年度以前'
    else:
        e1 = wareki(b['from'])
        b['label'] = f"{b['from']}〜{str(b['to'])[2:]}"
        b['wareki'] = f'{e1[0]}{e1[1]}〜' + ('' if e1[0] == e2[0] else e2[0]) + f'{e2[1]}年度'
ages = {'bins': bins, 'kinds': [], 'min_y': min(r['y'] for r in rows)}
for kd in AGE_KINDS:
    rs = [r for r in rows if r['kind'] == kd]
    inc = [r for r in rs if r['kubun_1en'] != '1円で載せた償却資産']
    exc = [r for r in rs if r['kubun_1en'] == '1円で載せた償却資産']
    vals = []
    for b in bins:
        sel = [r for r in inc if (b['from'] is None or r['y'] >= b['from']) and r['y'] <= b['to']]
        vals.append([len(sel), sum(r['shutoku_kagaku'] for r in sel)])
    if sum(v[0] for v in vals) != len(inc) or sum(v[1] for v in vals) + sum(r['shutoku_kagaku'] for r in exc) != sum(r['shutoku_kagaku'] for r in rs):
        errors.append(f'検算: 取得の時期の棒（{kd}）の和と、棒に入れなかった行の和が、{kd}の全行の和と合わない')
    oldest = min(r['y'] for r in rs)
    o = [r for r in rs if r['y'] == oldest]      # 最も古い年度の行（1円で載せた償却資産の行も含む）
    o1 = [r for r in o if r['kubun_1en'] == '1円で載せた償却資産']
    ages['kinds'].append({
        'name': kd, 'vals': vals, 'exc_n': len(exc), 'exc_acq': sum(r['shutoku_kagaku'] for r in exc),
        'oldest': {'y': oldest, 'nendo': sorted({r['shutoku_nendo'] for r in o}), 'n': len(o),
                   'acq': sum(r['shutoku_kagaku'] for r in o), 'n1en': len(o1),
                   'dates': sorted({r['shutoku_date'] for r in o}),
                   'toroku': sorted({r['toroku'] for r in o}), 'hojo': sorted({r['hojo'] for r in o})},
    })
if errors:
    fail_now()

# 令和6年度の動き（節5） --------------------------------------------------------------
idx = {r['rid']: i for i, r in enumerate(rows)}
moves = {}
for col in ('toki_shutoku', 'toki_jobaikyaku', 'toki_hyoka'):
    rs = [r for r in rows if r[col] != 0]
    rs.sort(key=lambda r: (-abs(r[col]), r['zaisan_no'], int(r['edaban'])))
    moves[col] = {'rows': [idx[r['rid']] for r in rs], 'n': len(rs), 'sum': sum(r[col] for r in rs),
                  'kaikei': collections.Counter(r['kaikei_name'] for r in rs).most_common(),
                  'jobai_nendo': collections.Counter(r['jobaikyaku_nendo'] for r in rs).most_common(),
                  'kimatsu0': sum(1 for r in rs if r['kimatsu'] == 0)}
fy_rows = [r for r in rows if r['y'] == FY]
fy_no_shutoku = [{'zaisan_no': r['zaisan_no'], 'edaban': r['edaban'], 'name': r['name'], 'toki_hyoka': r['toki_hyoka']}
                 for r in fy_rows if r['toki_shutoku'] == 0]
moves['fy'] = {'n': len(fy_rows), 'no_shutoku': fy_no_shutoku}

# 一覧（節6）。繰り返しの多い字は番号の表にする ----------------------------------------------
CODE_COLS = ['kind', 'kaikei_name', 'shukan', 'mokuteki', 'kubun_1en', 'tani', 'hojo']
codes = {c: [] for c in CODE_COLS}
codes['kind'] = list(KINDS)
codes['kubun_1en'] = list(KUBUN)
cidx = {c: {v: i for i, v in enumerate(codes[c])} for c in CODE_COLS}


def code(c, v):
    if v not in cidx[c]:
        cidx[c][v] = len(codes[c])
        codes[c].append(v)
    return cidx[c][v]


ROW_FIELDS = ['zaisan_no', 'edaban', 'name', 'kind', 'kaikei_name', 'shukan', 'mokuteki', 'hojo', 'shozai',
              'shutoku_nendo', 'y', 'shutoku_date', 'taiyo', 'suryo', 'tani', 'shutoku_kagaku', 'gensho_ruikei',
              'kimatsu', 'kubun_1en', 'toki_shutoku', 'toki_jobaikyaku', 'toki_hyoka', 'jobaikyaku_nendo', 'jobaikyaku_date']
out_rows = []
for r in rows:
    out_rows.append([code(f, r[f]) if f in cidx else r[f] for f in ROW_FIELDS])

# data.js ---------------------------------------------------------------------
meta = {
    'commit': COMMIT, 'doc': DOC, 'fy': FY, 'fy_label': FY_LABEL, 'sakusei': SAKUSEI,
    'sources': SRC_DOCS,
    'audit': {'n': sum(reviewers.values()), 'reviewers': dict(reviewers), 'last': audit_last},
    'kubun': KUBUN,
    'total': total,
    'rate': {'x10': rate_x10, 'n': dn, 'ruikei': ru, 'kimatsu': ki, 'gaiyou': gaiyou, 'gaiyou_page': g_printed,
             'gaiyou_pdf': g_pdf, 'gaiyou_somu': somu, 'gaiyou_wari_page': w_printed, 'shokyaku_n': sum(1 for r in rows if r['shokyaku'] == '償却対象'),
             'owari_n': total['kubun'][KI['償却を終えて1円を残した資産']][0]},
    'kinds': kinds, 'kind_hojo': kind_hojo,
    'purposes': purposes, 'moved': moved, 'gen_n': len(gen), 'tang_n': len(tang),
    'kaikei': collections.Counter(r['kaikei_name'] for r in rows).most_common(),
    'ages': ages, 'moves': moves,
    'meisai': {'one': one, 'two': two, 'naibu': naibu, 'pdf_page': z_pdf, 'soft_n': len(gen) - len(tang),
               'other_n': len(rows) - len(gen)},
    'issues': issue_out,
    'empty_cols': {c: sum(1 for r in rows if r[c] == '') for c in ('mokuteki', 'shozai', 'jobaikyaku_nendo')},
    'codes': codes, 'fields': ROW_FIELDS,
}
js = ['/* tools/build_data.py で生成。直接編集しない。材料と版は inputs.lock.json にある。 */',
      'const SHISAN = ' + json.dumps(meta, ensure_ascii=False, separators=(',', ':'))[:-1] + ',"rows":[']
js += [json.dumps(o, ensure_ascii=False, separators=(',', ':')) + (',' if i < len(out_rows) - 1 else '')
       for i, o in enumerate(out_rows)]
js += [']};', '']
text = '\n'.join(js)
size = len(text.encode('utf-8'))
if size > MAX_BYTES:
    errors.append(f'data.js の大きさ {size:,} バイトが 16MB を超える')
    fail_now()
(ROOT / 'data.js').write_text(text, encoding='utf-8')

# 報告 ---------------------------------------------------------------------------
f = lambda n: f'{n:,}'
print(f'材料: {len(lock["inputs"])}ファイルとも sha256 が inputs.lock.json と一致（hino-town-docs {COMMIT[:7]}）')
print(f'台帳: {DOC}（作成日 {SAKUSEI}）資産の行 {f(len(rows))}行。検収の台帳 {f(meta["audit"]["n"])}行が ✓（'
      + '・'.join(f'{k} {f(v)}' for k, v in reviewers.items()) + f'。最終 {audit_last}）')
print(f"全行: 取得価額 {f(total['acq'])}円・減価償却累計額 {f(total['ruikei'])}円・期末簿価 {f(total['kimatsu'])}円")
for i, k in enumerate(KUBUN):
    x = total['kubun'][i]
    print(f'  {k}: {f(x[0])}行・取得価額 {f(x[1])}円・期末簿価 {f(x[3])}円')
print('種類（財産番号の頭の字。取得価額の多い順）: ' + '、'.join(f"{s['name']} {f(s['n'])}行（1円 {s['n1en']}）{f(s['acq'])}円" for s in kinds))
print('  頭の字と補助科目名称の分け方が違う行: ' + '、'.join(f"{x['kind']}・{x['hojo']} {x['n']}" for x in kind_hojo))
print(f"目的（一般会計の有形固定資産 {f(len(tang))}行。枝番の読み替え {len(moved)}行）: "
      + '、'.join(f"{s['name'] or '空'} {f(s['n'])}行 率 {s['druikei'] / (s['druikei'] + s['dkimatsu']) * 100 if s['druikei'] + s['dkimatsu'] else 0:.1f}%" for s in purposes))
print(f"有形固定資産減価償却率: {rate_x10 // 10}.{rate_x10 % 10}%（償却する行 {f(dn)}、累計 {f(ru)}、期末簿価 {f(ki)}）。"
      f"概要（{g_printed}ページ・PDF {g_pdf}ページ）の値 " + '・'.join(f'{k} {v}' for k, v in gaiyou.items()))
for k in ages['kinds']:
    print(f"取得の時期（{k['name']}。1円で載せた償却資産 {k['exc_n']}行を除く）: " + '・'.join(
        f"{b['label']} {f(v[1])}" for b, v in zip(bins, k['vals'])))
    print(f"  最も古い年度 {k['oldest']['y']}: {k['oldest']['n']}行（うち1円で載せた償却資産 {k['oldest']['n1en']}）・{f(k['oldest']['acq'])}円・取得日 {k['oldest']['dates'][:3]}"
          f"・登録種別 {k['oldest']['toroku']}・補助科目 {k['oldest']['hojo']}")
for col, lab in (('toki_shutoku', '当期取得額'), ('toki_jobaikyaku', '当期除売却'), ('toki_hyoka', '当期評価増減等')):
    x = moves[col]
    print(f"{lab}: {x['n']}行・{f(x['sum'])}円（" + '・'.join(f'{a} {b}' for a, b in x['kaikei']) + '）')
print(f"取得年度が{FY_LABEL}の行 {moves['fy']['n']}（うち当期取得額が0 {len(fy_no_shutoku)}）")
print(f"財務書類との照合: 一般会計 {f(len(tang))}行（ソフトウェア {len(gen) - len(tang)}行・ほかの会計 {len(rows) - len(gen)}行を除く）と "
      f"{ZDOC} PDF {z_pdf}ページの①②。差は原典の誤りの記録の額だけ（" + '、'.join(f"{c} {f(sum(v for _, v in xs))}" for c, xs in sorted(allow.items())) + '）')
print(f'data.js: {f(size)}バイト')
print('検算 OK。data.js を書き出しました。')
