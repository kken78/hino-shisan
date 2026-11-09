# 固定資産台帳 町の資産（日野町データポータル・非公式）

滋賀県日野町が公開している固定資産台帳（令和6年度末時点）の資産の行9,896行を、種類・行政の目的・取得の時期ごとにまとめ、全行の一覧と、財務書類の附属明細書との照合を示すページです。日野町の公式のサイトではありません。

- ページ：https://kken78.github.io/hino-shisan/
- 設計の決定：[DESIGN.md](DESIGN.md)（ADR-1 に、節・数字の定義・単位・1円の行の区分の見せ方・検算・使わないもの）
- ポータル全体の決まり：hino-portal の DESIGN.md

## 出典

| 資料 | 形式 | 使うところ |
|---|---|---|
| 日野町「固定資産台帳（令和6年度末時点）」 | Excel | 資産の行のすべて |
| 日野町「統一的な基準に基づく令和6年度財務書類4表（一般会計・全体・連結）」 | PDF | 附属明細書①有形固定資産の明細・②有形固定資産の行政目的別明細（PDF 10ページ）との照合 |
| 日野町「統一的な基準に基づく令和6年度財務書類4表の概要」 | PDF | 有形固定資産減価償却率（21ページ）の比べる相手と検算 |

掲載ページは https://www.town.shiga-hino.lg.jp/0000002444.html 。資料の URL・バイト数・sha256・取得日は hino-town-docs の台帳 `data/sources.tsv`（id は `zaisei-r6-kotei`・`zaisei-r6-zaimu`・`zaisei-r6-zaimu-gaiyou`）にあります。

このリポジトリは原典を直接読みません。hino-town-docs が原典から作り、検収した次の材料を読みます（`inputs.lock.json` に commit・パス・sha256）。

- `data/struct/kotei-shisan.tsv`：資産の行の値（DOCS_SCHEMA.md §13.14）
- `data/struct/audit/kotei.tsv`：その検収の台帳（§13.10。9,896行とも段1 で ✓）
- `data/struct/issues/zaisei-r6-kotei.tsv`：財務書類との照合の差を記録した原典の誤りの記録
- `data/text_raw/zaisei-r6-zaimu.txt`・`data/text_raw/zaisei-r6-zaimu-gaiyou.txt`：財務書類4表とその概要の原典の文字
- `data/text/zaisei-r6-kotei/01.tsv`：台帳の原典の文字（1行目の作成日だけを読む）
- `data/sources.tsv`：資料の台帳

## ファイル

| ファイル | 中身 |
|---|---|
| index.html | ページ（共通の部品は hino-portal の `shared/` の写し） |
| data.js | 画面が読むデータ。`tools/build_data.py` が材料から作る。直接編集しない |
| tools/build_data.py | 材料を検算し、data.js を作る（標準ライブラリのみ） |
| inputs.lock.json | 材料の版（リポジトリ・commit・パス・sha256） |
| .github/workflows/check.yml | 検算・data.js の一致・hino-portal の共通の検査 |

## 作り直し方

1. このリポジトリと同じフォルダに hino-town-docs を置き、`inputs.lock.json` の commit の版にする（`git -C ../hino-town-docs checkout <commit>`）。別の場所に置いたときは、`--src <hino-town-docs を置いたフォルダ>` を付けるか、環境変数 `HINO_SRC` にそのフォルダを入れる。
2. `python3 tools/build_data.py` を実行する。次の検算がすべて合ったときだけ `data.js` が書き出される。合わなければ、合わない行を表示して終了コード 1 で止まる。
   - 材料の sha256 が `inputs.lock.json` と一致し、hino-town-docs の材料が1つの commit にそろう
   - 資産の行が9,896行で、財産番号と財産枝番の組が重ならない。列の見出しが §13.14 の表と同じ。金額の列が整数で、取得年度の読み替えが和暦の字と同じ
   - すべての行が検収の台帳に同じ照合キーであり、✓
   - 1円の行の区分を4つの列から付け直した値が kubun_1en と同じで、どの行もちょうど1つの区分に当たる
   - 期首簿価＋当期取得額−当期減価償却額−当期除売却＋当期評価増減等＝期末簿価 が全行で成り立つ
   - 種類・目的・5区分ごとの和の計が全行の計と同じ。取得の時期の棒の和と棒に入れなかった行の和が、工作物・建物の全行の和と同じ
   - 財務書類との照合：一般会計の行（ソフトウェアを除く）の和と附属明細書①②の額の差が、原典の誤りの記録の額とちょうど同じ（hino-town-docs の `tools/kotei.py zaimu` と同じ規則）。明細の中の検算（D＝A＋B−C、G＝D−E、区分の和）も行う
   - 一般会計の行から計算した有形固定資産減価償却率（小数1桁）が、概要の令和6年度の値と同じ
   - 資料の台帳に3つの資料の行がある。data.js が 16MB 以下
3. 実行すると、行の数・5区分ごとの額・種類と目的ごとの値・率・取得の時期・令和6年度の動き・照合の結果を表示する。
4. 画面を変えたら、hino-portal の検査を通す。

```sh
python3 ../hino-portal/shared/check.py --fonts --hyoki index.html
PLAYWRIGHT_MODULE=<playwright の index.mjs> node ../hino-portal/shared/check_mobile.mjs index.html
```

## 更新のしかた

- hino-town-docs の材料が変わったとき（検収や原典の誤りの記録の status の変更など）：hino-town-docs を `git pull` し、`inputs.lock.json` の各ファイルの commit（`git -C ../hino-town-docs rev-parse HEAD`）と sha256（`sha256sum <ファイル>`）を書き換えてから、`python3 tools/build_data.py` を実行する。`inputs.lock.json` と `data.js` は同じコミットで直す。
- 次の年度の固定資産台帳が公表されたとき：hino-town-docs で新しい資料の id（`zaisei-r7-kotei` など）として取り込み、検収と財務書類との照合が済んでから、このリポジトリの `tools/build_data.py` の資料の id・年度・行の数（`DOC`・`ZDOC`・`GDOC`・`FY`・`EXPECTED_ROWS`）と `inputs.lock.json` を改める。年度の比べ方を足すときは、先に DESIGN.md に ADR を足す。
- ページの上の「資料の時点」とフッターの日付は index.html に書いてあるので、材料を変えたら合わせて直す。
- 共通の部品は hino-portal の `shared/apply.py index.html` で写し直す。

## ライセンス

コードは MIT License（[LICENSE](LICENSE)）。`data.js` の構造は CC BY 4.0（表示は https://github.com/kken78/hino-shisan ）。転記した文字と数字は日野町の公表資料によるもので、このリポジトリのライセンスの対象外です。
