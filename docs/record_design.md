# 記録（段階 7）設計書：フローが必要とするデータからの逆算

作成：2026-10-14 ／ 状態：**実装済み**（`runs`・`screen_results`・`outcomes`。その他のテーブルは各ブランチで追加）

根拠の表記は `docs/hypothesis_map.md` と同じ。段階番号は `docs/selection_flow.md`。

## 0. 設計の原則

1. **問いから逆算する**：記録は「あとで答えたい問い」に必要なものだけにする。問いに紐づかない列は持たない。
2. **時点のデータは、その時に保存しない限り失われる**：yfinance は現在の値しか返さない [データ]。スクリーニング時点の指標・判定は、実行のたびに保存する。一方、**株価の履歴はあとから取り直せる**ので、将来の騰落率は答え合わせの時点で計算すればよい。
3. **落とした銘柄も記録する**：選んだ銘柄だけでは、どの段階が効いたか（落とした判断が正しかったか）を測れない。
4. **キャッシュと記録は分ける**：キャッシュ（`stocks_cache.duckdb`）は消して取り直せる。記録は取り直せないので、別ファイルで、バックアップ（後述）を取る。

## 1. 答えたい問い（出典つき）

| # | 問い | 出典 |
|---|---|---|
| Q1 | 改善あり群は、兆しなし群より TOPIX に勝ったか | selection_flow 段階 7、hypothesis_map 2.2（13/15 対 0/6 の再現） |
| Q2 | きっかけ（段階 4）があった銘柄は、なかった銘柄より勝ったか。予想した時期に、実際に開示はあったか | selection_flow 段階 7、hypothesis_map H3a |
| Q3 | どの型（P1〜P4）が効いたか | selection_flow 段階 7、hypothesis_map 4 章 |
| Q4 | 各段階の足切り・反証チェックで落とした銘柄は、残した銘柄より本当に劣っていたか | selection_flow 段階 7「どの段階が効いているか」 |
| Q5 | 資本の使い方で前提が崩れた銘柄（N2）を、事前に検出できたか | hypothesis_map H4d（第一興商） |
| Q6 | 会社予想は保守的だったか。上方修正は実際に起きたか | hypothesis_map H2d、selection_flow 段階 2・4 |
| Q7 | 人（＋LLM）の二次判断は、機械の一次判定に上乗せの価値があったか | レイヤーマスター手法書 Step 7（採用群と落選群の差＝二次の実力） |
| Q8 | 個々の売買は、仮説どおりに動いたか。売る判断は正しかったか | レイヤーマスター手法書 Step 5・6 |
| Q9 | いつの、どの設定・データで出した結果か（再現性） | bonsai の再現性の原則 |

## 2. 問い × 必要なデータ × 作る段階

| データ | 使う問い | 作る段階・担当 | 時点の保存が必要か |
|---|---|---|---|
| 実行の情報（日時、四季報の号、git のコミット、config 全体、銘柄リストの日付、データ取得日時） | Q9 | 段階 1 実行時・機械 | 必要 |
| 全銘柄の段階 1 の判定（通過／落ちた条件） | Q4 | 段階 1・機械 | 必要 |
| 判定時の指標（株価、時価総額、PSR、実質PSR、PBR、配当、自己資本比率、営業利益率、営業 CF、純現金、現金、売買代金、売上 CAGR など現在の出力列すべて） | Q1・Q4・Q5 | 段階 1・機械 | 必要（yfinance は今の値しか返さない） |
| 改善の兆し（四半期 EPS と前年同期 EPS、前年同期比、年次営業利益の推移、利益率の変化）と区分 | Q1 | 段階 2・機械 | 必要 |
| 型のタグ（P1〜P4）と、その根拠となった機械の印 | Q3 | 段階 3・機械 | 必要 |
| きっかけ候補と見込み時期（次回決算日など） | Q2 | 段階 4・機械＋LLM | 必要 |
| 反証チェックの結果（N2・N3・N4・織り込み済み） | Q4・Q5 | 段階 5・機械＋一次情報 | 必要 |
| 二次判断（採用／落選／監視、理由、型、急所、根拠リンク、LLM の入出力） | Q7 | 段階 3〜6・人＋LLM | 必要（判断はその時のもの） |
| 買う前の 4 行（改善の源泉、証拠、きっかけと時期、売る条件） | Q8 | 段階 6・人 | 必要 |
| 売買（日付、数量、価格、口座、売った理由） | Q8 | 段階 6 以降・人 | 必要 |
| 実際に起きた開示（決算日、予想修正の有無と幅、中計の発表など） | Q2・Q6 | 答え合わせ時・機械（JPX、J-Quants）＋人 | 不要（あとから集められる。ただし J-Quants 無料は 2 年分まで [報道]） |
| 会社予想の履歴 | Q6 | 答え合わせ時・機械（J-Quants 無料、12 週遅れ） | 2 年を超える前に取り込む |
| 判定日から半年後・1 年後の株価と TOPIX（1306） | Q1〜Q4・Q7 | 答え合わせ時・機械（yfinance の価格履歴） | 不要（取り直せる）。計算結果は固定して保存する |

補足：
- 判定時の株価は記録するが、騰落率の計算には**答え合わせ時に取得した調整済み履歴**を使う（株式分割・配当の調整を揃えるため。レイヤーマスター手法書の記載：住友大阪セメントは保有中に 1:3 分割）。
- 中小型株指数との比較（手法書 Step 7）は、比較に使う指数・ETF を未確定（要確認）。当面は TOPIX のみ。

## 3. テーブル

保存先：`records.duckdb`（キャッシュとは別ファイル。DuckDB は既存の依存で、追加不要）。

| テーブル | 1 行の単位 | 主な列 | 書く担当 | 実装するブランチ |
|---|---|---|---|---|
| `runs` | 1 回のスクリーニング実行 | run_id、run_at、issue（四季報の号）、git_sha、config（JSON）、ticker_list_date、data_fetched_min/max | 機械 | `feat/record` |
| `screen_results` | 実行 × 銘柄（**全銘柄**） | run_id、ticker、stage1_pass、stage1_fail_rule、improvement_class、types、next_earnings_date、rebuttal_flags、metrics（その時の出力行すべてを JSON） | 機械 | `feat/record`（段階 2〜5 の列は各ブランチで埋める） |
| `outcomes` | 実行 × 銘柄 × 期間（6・12 か月） | price_t0、price_t1、return、benchmark_return（比較対象は config の `records.benchmark_ticker`、既定は TOPIX 連動の 1306）、excess、computed_at | 機械（`evaluate` コマンド） | `feat/record` |
| `events` | 銘柄 × 開示 | ticker、date、kind（決算・予想修正・中計・資本政策・テーマ）、detail、source | 機械＋人 | `feat/catalyst-calendar`、`feat/company-forecast` |
| `forecasts` | 銘柄 × 開示 × 予想の対象期 | ticker、disclosed_date、target（今期・来期・中間）、sales、op、odp、np、eps、source | 機械（J-Quants） | `feat/company-forecast` |
| `reviews` | 実行 × 銘柄（二次で調べた銘柄のみ） | decision（採用／落選／監視）、reason、type、chokepoint、evidence_links、llm_prompt、llm_answer、sources、thesis（4 行） | 人＋LLM | 二次スクリーニングの自動化時（当面は CSV で取り込み） |
| `trades` | 売買 1 件 | ticker、date、side、qty、price、account、review_id、exit_reason | 人 | 同上 |

設計上の判断：
- **指標は JSON 列にまとめる**：フローの改修で指標が増減しても、テーブルの形を変えずに済む。よく絞り込む値（通過・型・改善区分など）だけを通常の列にする。
- **全銘柄を記録する**：約 3,700 行 × 年 4 回。段階 1 で落ちた銘柄の指標は、落ちた条件までに計算できたものだけ。
- **レイヤーマスター手法書 Step 7 の表**の列は、`screen_results`（stage1_score → metrics）、`reviews`（stage2_decision、reason_forgotten、theme、tier、exposure_pct、closing_paths、llm_prompt/answer/sources）、`outcomes`（price_t0、topix_t0）、`trades`（exit_date、exit_reason）に対応する。

## 4. コードへの影響（`feat/record` の範囲）

1. `Screener` が、足切りで落ちた銘柄についても「どの条件で落ちたか」と計算済みの指標を返すようにする（現在は None を返すだけ）
2. `analyze` の実行時に、`runs` と `screen_results` を書く（CSV の出力はそのまま）
3. `evaluate` コマンド：判定日から 6・12 か月が経過した実行について、`outcomes` を計算して保存する
4. 往復テスト、全銘柄の記録件数のテスト。既存の出力（CSV）は変えない

## 5. 決定事項（2026-10-14、ユーザー承認）

1. **バックアップ**：実行ごとに `records/` へ Parquet で書き出し、リポジトリにコミットする（`records.duckdb` 本体は `.gitignore` のまま）
2. **全銘柄を記録する**（段階 1 で落ちた銘柄も、落ちた条件と計算済みの指標を記録）
3. **最初の記録**：再取得の完了後、すぐに初回を記録する

## 6. 実装メモ（2026-10-14）

- `run_id` は実行時刻（`YYYYMMDDTHHMMSSffffff`、マイクロ秒まで）。
- `evaluate` は、記録のうち最も古い実行の 14 日前から調整済み日足を取得する（休日をまたいでも「判定日以前の終値」が取れるように）。
- キャッシュがない銘柄は `stage1_fail_rule = "no_cache"` で記録し、`evaluate` の対象から外す。
- 判定日・評価日の株価は、その日以前で最後の終値。履歴がない場合は NULL。
