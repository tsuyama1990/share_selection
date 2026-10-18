# L1 全体アーキテクチャ

作成：2026-10-14 ／ 状態：**承認・QA 完了**（C9 Tailwind Watch は受け入れ待ち）。進め方は `docs/architecture/process.md`

手法の名前（2026-10-18）：本書が設計するのは **Value Turn（割安改善スクリーン）**、月 1 回、割安で下値が安全なまま決算に営業利益の改善が出た会社を拾う手法（エミン・ユルマズ氏の考え方をもとに、閾値と二次調査は独自）。**Tailwind Watch（追い風ウォッチ）** は、人が指定した PEST の流れについて、引用つきの調査メモで判断を支え、判断を記録して答え合わせする仕組み（C9、R8〜R12、N7。方針と根拠は `docs/tailwind_watch_design.md`）。

設計の階層（V 字モデル）：

| 階層 | 文書 | 対応するテスト |
|---|---|---|
| 要件 | 本書 1 章 | 受け入れ（6 か月後・1 年後の答え合わせ：`docs/record_design.md`） |
| **L1 全体アーキテクチャ** | **本書** | **E2E テスト**（本書 7 章） |
| L2 詳細設計 | `docs/architecture/L2_*.md`（コンポーネントごと、次の工程） | 結合テスト |
| L3 クラス設計 | `docs/architecture/L3_*.md`（次々の工程） | 単体テスト |

変更は上から下へ：設計書 → テスト → コードの順に直す。設計にないコードは作らない。

凡例：✅ 実装済み（main）／🆕 未実装（目標）

## 1. 要件

### 1.1 機能要件

| ID | 要件 | 根拠 |
|---|---|---|
| R1 | 全上場銘柄から、下値が盤石な銘柄（一次の足切り）を選ぶ | `docs/selection_flow.md` 段階 1 |
| R2 | 改善の兆しを判定し、改善の大きさで順位を付ける | 同 段階 2、`docs/selection_tuning.md` |
| R3 | 改善が明るみに出る時期（次回決算日）を付ける | 同 段階 4 |
| R4 | 改善の質の疑い（一時的な損益）に旗を立て、二次候補から外す | 同 段階 5、`docs/selection_tuning.md` 3.9 |
| R5 | 二次候補を、一次情報と Web 検索をもとに LLM で調査し、根拠付きの調査メモと採否の提案を作る | `docs/architecture/L2_C4_stage2_research.md` |
| R6 | 実行ごとに全銘柄の判定と指標を記録し、6 か月後・1 年後の結果を答え合わせする | `docs/record_design.md` |
| R7 | 別の設定ファイルで、過去の記録を使った実験ができる | 同 6 章、`--config` |
| R8 | 人が指定した流れ（名前・需要の説明・任意の出典 URL）について、根拠の文書（Web 検索・指定の URL）を集め、5 つの軸（規模・強制と裾野・持続・注目の広がり・織り込み度）と終わりの手がかりを引用つきで抜き出す。点数は付けない | `docs/tailwind_watch_design.md` 4 章 |
| R9 | 流れの恩恵を受ける会社を、全上場企業の有価証券報告書の「事業の内容」から引用つきで特定する（何次の供給元か、売上に占める割合） | 同 4 章 |
| R10 | 地図の会社ごとに、Value Turn の判定（通過・落ちた条件・改善区分）、PBR・PER・PSR と業種の中央値、直近 3 か月の上昇の地図の中の位置を並べた調査メモを出す | 同 4 章 |
| R11 | 人の判断（買う／見送る、理由、金額の上限）を記録する | 同 4 章 |
| R12 | 判断の 6・12 か月後の超過リターンを、同じ業種のまだ上がっていない割安株（機械の合図）と比べて答え合わせする | 同 4 章 |
| R13 | 二次調査の業種の比較と調査メモに、候補の 33 業種の直近 3 か月の超過リターン（全業種の中の順位）と、候補の業種の中の位置を、事実として載せる。選ぶ条件には使わない | `docs/tailwind_watch_design.md` 3 章 |

### 1.2 非機能要件

| ID | 要件 |
|---|---|
| N1 | 再現性：結果は、設定・データ取得日・コードの版とともに記録する |
| N2 | 秘密情報（API キー）は `.env` と環境変数だけに置き、リポジトリ・ログ・出力に書かない |
| N3 | LLM の主張は、取得した文書の引用で機械的に照合し、照合できないものは使わない |
| N4 | 費用：無料枠を優先し、有料（DeepSeek）は最後のフォールバック。1 回の実行の呼び出し数に上限を置く |
| N5 | 追跡可能性：調整値はすべて `config.yaml`、コード量は予算で管理、設計とモジュールは一対一 |
| N6 | 外部サービスが落ちても、その銘柄・その段階だけを「取得失敗」として記録し、全体は止めない |
| N7 | 情報源は公式で、利用条件上取ってよいもの（robots.txt が断っていない）だけ |

## 2. システムの境界と外部システム

```
                         ┌──────────── 利用者 ────────────┐
                         │ 実行（CLI）・二次の最終判断・売買 │
                         └───────────────┬───────────────┘
                                         │
   JPX（銘柄一覧・決算発表予定日）──┐      ▼
   Yahoo Finance（株価・財務）──────┤  ┌──────────────────────┐
   EDINET（有価証券報告書）🆕───────┼─▶│  share_selection     │──▶ 結果 CSV・調査メモ
   Web（Gemini 検索の出典・決算短信）🆕┤  │  （本リポジトリ）       │──▶ 記録（DuckDB＋Parquet）
   LLM（Gemini→Groq→DeepSeek）✅───┘  └──────────────────────┘
   J-Quants（会社予想、12 週遅れ）🆕（後日）
```

| 外部システム | 用途 | 状態 | 制約 |
|---|---|---|---|
| JPX | 銘柄一覧（`tickers`）、決算発表予定日（`calendar`） | ✅ | ブラウザ相当の User-Agent が必要 |
| Yahoo Finance（yfinance） | 株価・財務・四半期 EPS | ✅ | 現在値のみ。日本の中小型株の四半期データは EPS だけ |
| EDINET API v2 | 有価証券報告書 | 🆕 | API キー（`.env` に設定済み） |
| Web（Gemini 検索の出典、決算短信） | 中計・決算説明・ニュース | 🆕 | 決算短信は TDnet で 31 日分のみ |
| LLM | 調査・要約・判定 | ✅（クライアント） | [データ：2026-10-14] 稼働：Gemini・Groq・DeepSeek。Cerebras は 402、Mistral は 429 |
| J-Quants | 会社予想 | 🆕（後日） | 無料は 12 週遅れ。事後検証用 |

## 3. コンポーネント

| ID | コンポーネント | 責務 | モジュール（現状） | 状態 |
|---|---|---|---|---|
| C1 | 銘柄一覧 | JPX の一覧から対象銘柄 CSV を作る | `tickers.py` | ✅ |
| C2 | データ取得 | 外部システムからの取得と保存（キャッシュ・文書） | `yahoo.py`、`cache.py`、`stock_data.py`、`earnings_calendar.py`、`edinet.py`、`webfetch.py`、`docstore.py`、`collect.py`（`docs`・`profiles` の流れ）、`throttle.py`（外部 API の呼び出し間隔。C4 の LLM も使う）（詳細は `L2_C2_data_acquisition.md`） | ✅ |
| C3 | 一次スクリーニング | 足切り（R1）、指標、改善の兆し（R2）、質の旗（R4）、順位と二次候補 | `rules.py`、`indicators.py`、`improvement.py`、`quality.py`、`metrics.py`、`screener.py`、`selection.py`（順位と二次候補）、`fields.py`（結果行の項目名と値の語彙を 1 か所で定義） | ✅ |
| C4 | 二次調査 | 業種の文脈、LLM による企業分析、引用の照合、調査メモ（R5） | `llm.py`、`sector.py`、`research.py`、`verify.py`、`review.py`（`review` の流れ）、`review_eval.py`（モデルの品質の関門）（詳細は `L2_C4_stage2_research.md`） | ✅ |
| C5 | 記録と答え合わせ | 実行・全銘柄の判定・二次の調査結果の記録、結果の計算（R6） | `records.py`（実行・判定）、`outcomes.py`（答え合わせ）、`backup.py`（git 対象外の記録のバックアップ）、`review_store.py`（`reviews`・`review_evals`、別の DB ファイル `review.db_file`、バージョン管理の対象外） | ✅ |
| C6 | 出力 | 結果 CSV、二次候補の一覧、調査メモ | `report.py`、`memo.py`（調査メモ） | ✅ |
| C7 | 設定と起動 | 設定の読み込み、`.env`、CLI、各コンポーネントの組み立て | `config.py`、`flows.py`（複数のコンポーネントにまたがる `docs`・`review` の流れ）、`main.py`（CLI と組み立てだけ。処理の流れは各コンポーネントのモジュール。`L3_composition.md`） | ✅ |
| C8 | 実験 | 過去の記録を別の設定で再現し比較する（R7） | 🆕（結果が貯まる 2027 年春以降） | 🆕 |
| C9 | 流れの調査（Tailwind Watch） | 根拠と 5 つの軸（R8）、恩恵企業の地図（R9）、会社ごとの数値と調査メモ（R10）、判断の記録（R11）（詳細は `L2_C9_tailwind.md`） | `company_map.py`（会社の地図）、`flow.py`（`flow-memo`・`flow-decide` の流れ、調査メモ）、`flow_store.py`（記録 `flow.db_file`） | ✅ |

## 4. 処理の流れ（コマンド）

```
tickers ─▶ fetch ─▶ calendar ─▶ analyze ─▶ docs ─▶ review ─▶ （人の判断）
   C1        C2        C2         C3+C5+C6     C2         C4+C5+C6
                                     │
                         evaluate（判定日から 6・12 か月後）C5
```

| コマンド | 入力 | 出力 | 頻度 |
|---|---|---|---|
| `tickers` | JPX 銘柄一覧 | `japan_tickers.csv` | 毎月〜四半期 |
| `fetch` | 銘柄一覧、Yahoo | キャッシュ、取得失敗 CSV | 四半期（四季報）＋決算シーズン後 |
| `calendar` | JPX 決算発表予定日 | `earnings_calendar.csv` | `analyze` の前 |
| `analyze` | キャッシュ、決算日 | 結果 CSV、記録（`runs`・`screen_results`・Parquet） | 同上 |
| `docs` | 二次候補、EDINET、Web 検索 | 文書ストア（本文と出典）、取得の失敗 | `analyze` の後 |
| `review-eval` | 正解のある銘柄、文書ストア、LLM | 記録（`review_evals`）、合否（不合格は終了コード 1） | モデル・プロンプトを変えたとき（`review` の前提） |
| `review` | 二次候補、文書ストア、LLM | 記録（`reviews`、同業比較つき）、調査メモ（`memo.dir`） | `docs` と `review-eval` の合格の後 |
| `evaluate` | 記録、Yahoo の価格履歴 | 記録（`outcomes`、流れの判断の答え合わせ） | 随時 |
| `backup` | `review.db_file`・`review.export_dir`・`memo.dir`・`docstore.db_file` | `backup.dir/<日時>/` の写し（新しい `backup.keep` 個だけ残す）。`backup.dir` がリポジトリの中なら拒否（公開リポジトリ） | `review` の後 |
| `llm-check` | LLM、検索 | 疎通の結果 | 任意（ライブ確認。CI では実行しない） |
| `profiles` | 銘柄一覧、EDINET | 文書ストア（全銘柄の有価証券報告書の「事業の内容」）、取得の失敗 | 年 1 回＋新しい報告書の差分（月 1 回） |
| `flow-memo` | 流れの名前と需要の説明（任意の URL）、Web 検索、文書ストア、最新の実行の記録、キャッシュ、LLM | 調査メモ（`flow.memo_dir`）、記録（`flow.db_file`） | 人が流れに気づいたとき |
| `flow-decide` | 流れ・銘柄・買う／見送る・理由・金額の上限 | 記録（判断） | 調査メモを読んだ後 |

## 5. データの受け渡し（コンポーネント間の約束）

E2E テストは、この表の形式が守られることを確かめる。

| 境界 | 形式 | 主な内容 | 状態 |
|---|---|---|---|
| C1 → C2・C3 | `japan_tickers.csv` | code、name、market、sector33、size | ✅ |
| C2 → C3 | キャッシュ（DuckDB `stock_cache`） | 銘柄ごとの info、財務・四半期損益・株価（JSON） | ✅ |
| C2 → C3 | `earnings_calendar.csv` | code、announce_date、period_en、fiscal_year_end | ✅ |
| C3 → C6 | 結果 CSV | `output.columns` の列（順位、二次候補、改善区分、質の旗、指標、次回決算日） | ✅ |
| C3 → C5 | `screen_results` | 全銘柄の通過・落ちた条件・改善区分・二次候補（`stage2_candidate` 列）・質の旗（リスト）・次回決算日・全指標（JSON）。項目名は `fields.py` が唯一の定義 | ✅ |
| C5 → C2・C4 | `RecordStore.candidates` | 実行の二次候補（`stage2_candidate` 列で選び、`Priority_Rank` の順）と指標 | ✅ |
| C2 → C4 | 文書ストア | 文書 ID、出典（URL・EDINET の書類 ID）、取得日時、本文 | ✅ |
| C4 → C5 | `reviews` | 調査結果、照合できた根拠、照合率、モデル・プロンプトの版（Parquet は `review.export_dir`、git 対象外：公開リポジトリに引用を載せない） | ✅ |
| C2 → C9 | 文書ストア | `profiles` が入れた全銘柄の「事業の内容」（文書 ID、EDINET の書類 ID、本文） | 🆕 |
| C5 → C9 | `RecordStore` の最新の実行 | 地図の会社の判定（通過・落ちた条件・改善区分・指標）。足切りをやり直さない | 🆕 |
| C2 → C9 | キャッシュ（`stock_cache`） | 地図の会社と業種の株価（直近 3 か月の上昇） | 🆕 |
| C9 → C5 | 記録（`flow.db_file`、git 対象外） | 流れ、軸の抜き出し、地図、判断、答え合わせ | 🆕 |
| C9 → 利用者 | 調査メモ（Markdown、`flow.memo_dir`） | 5 つの軸の引用、地図、会社ごとの判定と数値、終わりの手がかり | 🆕 |
| C5 → C8 | 記録（Parquet） | `runs`・`screen_results`・`outcomes`（`records/`、コミット）、`reviews`・`review_evals`（`review.export_dir`、git 対象外） | ✅ |

## 6. 横断的な決まり

- **設定**：調整値・パス・ファイル名はすべて `config.yaml`。`load_config` を呼ぶのは `config.py` と `main.py` だけ（アーキテクチャテストで強制）。
- **秘密情報**：API キーは `.env`（git 対象外）と環境変数だけ。キーをログ・例外・出力に出さない（N2）。
- **失敗の扱い**：外部取得の失敗は銘柄単位で記録して続行（N6）。
- **品質ゲート**：ruff、mypy、vulture、deptry、pytest（カバレッジ 85% 以上）、コード予算。フックとCI で強制。

## 7. E2E テスト計画

外部システムはすべてモック・フィクスチャで置き換え、ネットワークを使わない。本物の API を使う疎通確認（`llm-check`、`calendar`）は CI に入れず、手動の「ライブ確認」とする。

| ID | シナリオ | 確かめること（合格基準） | 対応する要件 | 状態 |
|---|---|---|---|---|
| E1 | フィクスチャのキャッシュで `analyze` | 結果 CSV が 5 章の形式で、正解（ゴールデン）と一致。全銘柄が `screen_results` に記録され、Parquet が書かれる | R1・R2・R4・R6・N1 | ある（`tests/e2e/test_e1_analyze.py`） |
| E2 | 決算日を含む `calendar` → `analyze` | 予定日が結果 CSV と記録に入る。予定日がないときは空 | R3 | ある（`tests/e2e/test_e2_calendar.py`） |
| E3 | Yahoo をモックした `fetch`（一部失敗） | 成功した銘柄はキャッシュに、失敗は取得失敗 CSV に。全体は止まらない | N6 | ある（`tests/e2e/test_e3_fetch.py`） |
| E4 | 記録＋モックの価格で `evaluate` | 期間を過ぎた実行だけ `outcomes` が計算される | R6 | ある（`tests/e2e/test_e4_evaluate.py`） |
| E5 | `--config` で別の設定 | 閾値が変わり、出力と記録が別の場所に書かれる | R7 | ある |
| E6 | 文書ストアにある二次候補で `review`（LLM をモック） | `reviews` に記録され、照合できない引用の主張は捨てられ、調査メモが出る。キーが出力に現れない | R5・N2・N3・N4 | ある |
| E7 | 二次候補で `docs`（EDINET・検索・Web をモック、一部失敗） | 候補ごとの文書が文書ストアに入り、失敗は記録されて全体は止まらない。キーが出力に現れない | R5・N2・N6 | ある |
| E8 | 一時ディレクトリで `backup` | 4 つの対象が日時のフォルダに写り、古いものは `backup.keep` 個を超えると消える。`backup.dir` がリポジトリの中なら終了コード 1 で何も写さない | N1 | ある（`tests/e2e/test_e8_backup.py`） |
| E9 | EDINET をモックした `profiles`（一部失敗） | 銘柄ごとの「事業の内容」が文書ストアに入り、失敗は記録されて全体は止まらない。2 回目は取得済みを飛ばす | R9・N6 | ある（`tests/e2e/test_e9_profiles.py`） |
| E10 | 検索・Web・LLM をモックし、フィクスチャの文書ストア・記録・キャッシュで `flow-memo` | 調査メモに 5 つの軸（照合できた引用だけ、無ければ「不明」）、地図（照合できた会社だけ）、会社ごとの判定と数値が出て、記録に残る。`profiles` 未実行なら案内して終了コード 1。キーが出力に現れない | R8・R9・R10・N2・N3・N7 | ある（`tests/e2e/test_e10_flow_memo.py`） |
| E11 | `flow-decide` → 期間を過ぎた記録で `evaluate`（価格をモック） | 判断が記録され、期間を過ぎた判断だけ超過リターンと比べる相手の超過リターンが計算される | R11・R12 | ある（`tests/e2e/test_e11_flow_decide.py`） |
| E12 | 株価の履歴を含むフィクスチャのキャッシュで `review-eval` → `review`（LLM をモック） | 調査メモと `reviews.sector_comparison` に業種の勢い（超過リターンと順位）と業種の中の位置が入る。二次候補の顔ぶれと順位は変わらない | R13 | ある（`tests/e2e/test_e12_review_momentum.py`） |

### 7.1 ライブ E2E（本物の API。CI に入れない）

上の E2E は外部をモックする。ライブ E2E は本物の JPX・Yahoo・EDINET・Gemini・LLM を使い、コマンドを通しで動かす（`uv run pytest -m live`。通常のテスト・関門・CI では選ばない）。

- 実行ごとに一時ディレクトリを作り、`config.yaml` を写して出力・記録・キャッシュ・文書ストアの場所をすべてそこへ向ける（リポジトリの `.env`・キャッシュ・記録には書かない。`.env` は読むだけ）。候補は `selection.candidates_n` を 3 に絞り、割り当て（検索 1 日 20 回など）と費用を抑える。
- モデルに依る結果（評価の合否）は値を決め打ちせず、**一貫性**を確かめる（評価が不合格なら `review` は拒む、など）。
- シナリオは順に依存する。前のシナリオが失敗したら、後は失敗ではなく skip とする。

| ID | シナリオ | 確かめること（合格基準） | 対応する要件 |
|---|---|---|---|
| LV1 | `tickers` | JPX から 3,000 銘柄以上、列 code・name・market・sector33・size | R1 |
| LV2 | `calendar` | 予定日の CSV に 1 行以上、日付が読める | R3 |
| LV3 | `fetch`（3 銘柄に絞った一覧） | 3 銘柄がキャッシュに入り、四半期損益を含む。失敗は CSV に | N6 |
| LV4 | `analyze`（全銘柄のキャッシュを読むだけ） | 結果 CSV と記録、`stage2_candidate` の数が CSV の二次候補の数と同じ | R1・R2・R4・R6 |
| LV5 | `evaluate` | 期間を過ぎていない実行では 0 行で正常終了 | R6 |
| LV6 | `llm-check` | チャットが主のプロバイダーで答え、検索が出典を返す（検索の割り当て切れは skip） | N2 |
| LV7 | `docs` | 候補ごとに EDINET の節（経営成績の分析を含む）、Web 文書は会社名を含むものだけ。割り当て切れでも正常終了し残りを表示 | R5・N6 |
| LV8 | `review-eval` | 正常終了か終了コード 1。`review_evals` に 1 行、合否と終了コードが一致 | R5・N3・N4 |
| LV9 | `review` | 評価が合格なら候補ごとに `reviews` に 1 行（状態つき）、不合格なら拒否（終了コード 1、行なし） | R5・N3 |
| LV10 | `review` の再実行 | 合格の場合、レビュー済みの候補を飛ばし行が増えない | R5 |
| LV11 | プロンプトを 1 文字変えた複製で `review` | 拒否（新しい版の評価がない） | N4 |
| LV12 | API キーなし（EDINET・LLM） | 終了コード 1 とキーの案内。スタックトレースを出さない | N2 |
| LV13 | キーの漏れ | 全シナリオの出力・CSV・DB・Parquet のどこにも API キーの文字列がない | N2 |

### 7.2 Tailwind Watch の E2E シナリオ（前提・操作・合格基準）

テストの本体は L3 の後、実装の前に書き、先に失敗することを確かめる（それまでは strict xfail の仮置き）。外部（EDINET・検索・Web・LLM・価格）はすべてモック。

| ID | 前提 | 操作 | 合格基準 |
|---|---|---|---|
| E9 | 銘柄一覧 4 社、EDINET のモックは 3 社に報告書、1 社は 500 | `profiles` を 2 回 | 1 回目：3 社の「事業の内容」とセグメント情報が文書ストアに入り、1 社は失敗として記録され、終了コード 0。2 回目：取得済みの 3 社を飛ばし、失敗した 1 社だけ取り直す |
| E10a | E9 の文書ストア（需要に売っている会社 2 社、売っていない会社 1 社）、Value Turn の実行の記録、株価のキャッシュ。偽の LLM は、軸ごとに文書の文を引用する答えと、文書に無い引用の答えを 1 つずつ返す | `flow-memo --name … --demand …` | 調査メモに 5 つの軸が出て、文書に無い引用の軸は「不明」。地図は売っている 2 社だけ（何次か・引用つき）。会社ごとに通過・落ちた条件・PBR・PER・実質 PSR と業種の中央値・直近 3 か月の地図の中の位置が記録どおりに出る。記録に流れ・軸・地図が残る。LLM の呼び出し数は `flow.map.top_k` と軸の数で決まる上限以内 |
| E10b | 文書ストアに「事業の内容」が無い | `flow-memo` | 終了コード 1、`profiles` を先に実行するよう案内。メモも記録も作らない |
| E10c | E10a と同じ | 全シナリオの後 | 出力・メモ・DB のどこにも API キーの文字列が無い |
| E11 | E10a の流れ、判断の月から 7 か月分の価格のモック | `flow-decide`（買う 1 社・見送る 1 社）→ `evaluate` | 判断が 2 件記録される。6 か月を過ぎた判断だけ超過リターンと、比べる相手（同じ業種の直近 3 か月の上昇が中央値以下かつ PBR が中央値以下の会社）の超過リターンが計算される。12 か月はまだ計算されない |
| E12 | E6 と同じ候補に、3 か月以上の株価の履歴を持つキャッシュ（2 業種、片方の業種だけ上昇） | `review-eval` → `review` | 調査メモと `sector_comparison` に、業種の超過リターン・全業種の中の順位・候補の業種の中の位置が入り、上昇した業種の候補にだけ「先に上がった会社はその後負けやすい（有意ではない）」の注記が付く。`Stage2_Candidate` と `Priority_Rank` は E6 と同じ |

## 8. 追跡表（要件 → コンポーネント → E2E）

| 要件 | コンポーネント | E2E |
|---|---|---|
| R1 | C1、C2、C3 | E1 |
| R2 | C3 | E1 |
| R3 | C2、C3 | E2 |
| R4 | C3 | E1 |
| R5 | C2、C4、C5、C6 | E6、E7 |
| R6 | C5 | E1、E4 |
| R7 | C7、C8 | E5 |
| N1 | C5 | E1、E8 |
| N2 | C2、C4、C7、C9 | E6、E7、E10 |
| N3 | C4、C9 | E6、E10 |
| N4 | C4、C9 | E6、E10 |
| N5 | C7 | ゲート（設計の関門 `tests/unit/test_design_docs.py`、`tests/unit/test_architecture.py`、コード予算） |
| N6 | C2 | E3、E7、E9 |
| R8 | C9 | E10 |
| R9 | C2、C9 | E9、E10 |
| R10 | C5、C9 | E10 |
| R11 | C9 | E11 |
| R12 | C5、C9 | E11 |
| N7 | C9 | E10 |
| R13 | C4、C6 | E12 |

## 9. 機械的な強制（この設計を守らせる仕組み）

1. テストに階層の印を付ける（pytest のマーカー `e2e`・`integration`・`unit`）。各要件に最低 1 つの E2E があることをテストで確かめる。
2. 本書 3 章のモジュール一覧と、実際の `src/` のモジュールが一対一で対応することをテストで確かめる（設計にないモジュールがあれば失敗）。
3. 変更は設計書 → テスト → コードの順。PR／マージのメッセージに、変更した設計書の節を書く。
4. コンポーネント間で受け渡す結果行の項目名と値（改善区分など）は `fields.py` だけが文字列で持つ。`src/`・`main.py` の他の場所にその文字列があれば失敗し、`output.columns` が `fields.py` にない項目を挙げても失敗する（`tests/unit/test_architecture.py`）。

## 10. 訂正履歴

詳細は git の履歴にある。要件・コンポーネント・E2E 計画は 2026-10-14 に承認（本物の API の疎通は CI に入れず手動のライブ確認）。

- 2026-10-15：文書の取得を `review` から `docs` に分けた（E7）。結果行の項目名を `fields.py` に集め、文字列の重複を禁じる関門を足した（9 章 4）
- 2026-10-16〜17：SOLID の見直し 2 回（`selection.py`・`throttle.py`、`L3_composition.md` の組み立て、C5 を `records.py`・`outcomes.py`・`review_store.py` に、`flows.py`）。品質の関門 `review-eval`、`backup`（E8）、ライブ E2E（7.1 節）を足した
- 2026-10-18：2 つの手法に名前を付けた（Value Turn、Tailwind Watch）。Tailwind Watch を C9（R8〜R12、N7、E9〜E11）と、Value Turn への追加（R13、E12）として加えた。週 1 回の自動の取り込みと月 1 回の売上の確認の案は、検証の結果で取りやめた（`docs/tailwind_watch_design.md`）
