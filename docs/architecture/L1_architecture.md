# L1 全体アーキテクチャ

作成：2026-10-14 ／ 状態：**承認・QA 完了**（2026-10-14）。進め方は `docs/architecture/process.md`

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

### 1.2 非機能要件

| ID | 要件 |
|---|---|
| N1 | 再現性：結果は、設定・データ取得日・コードの版とともに記録する |
| N2 | 秘密情報（API キー）は `.env` と環境変数だけに置き、リポジトリ・ログ・出力に書かない |
| N3 | LLM の主張は、取得した文書の引用で機械的に照合し、照合できないものは使わない |
| N4 | 費用：無料枠を優先し、有料（DeepSeek）は最後のフォールバック。1 回の実行の呼び出し数に上限を置く |
| N5 | 追跡可能性：調整値はすべて `config.yaml`、コード量は予算で管理、設計とモジュールは一対一 |
| N6 | 外部サービスが落ちても、その銘柄・その段階だけを「取得失敗」として記録し、全体は止めない |

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
| C2 | データ取得 | 外部システムからの取得と保存（キャッシュ・文書） | `yahoo.py`、`cache.py`、`stock_data.py`、`earnings_calendar.py`、`edinet.py`、`webfetch.py`、`docstore.py`、`collect.py` 🆕（`docs` の流れ）、`throttle.py`（外部 API の呼び出し間隔。C4 の LLM も使う）（詳細は `L2_C2_data_acquisition.md`） | ✅／🆕 |
| C3 | 一次スクリーニング | 足切り（R1）、指標、改善の兆し（R2）、質の旗（R4）、順位と二次候補 | `rules.py`、`indicators.py`、`improvement.py`、`quality.py`、`metrics.py`、`screener.py`、`selection.py`（順位と二次候補）、`fields.py`（結果行の項目名と値の語彙を 1 か所で定義） | ✅ |
| C4 | 二次調査 | 業種の文脈、LLM による企業分析、引用の照合、調査メモ（R5） | `llm.py`、`sector.py` 🆕、`research.py` 🆕、`verify.py` 🆕、`review.py` 🆕（`review` の流れ）、`review_eval.py` 🆕（モデルの品質の関門）（詳細は `L2_C4_stage2_research.md`） | ✅／🆕 |
| C5 | 記録と答え合わせ | 実行・全銘柄の判定・二次の調査結果の記録、結果の計算（R6） | `records.py`（`reviews` テーブル 🆕） | ✅／🆕 |
| C6 | 出力 | 結果 CSV、二次候補の一覧、調査メモ | `report.py`、`memo.py` 🆕（調査メモ） | ✅／🆕 |
| C7 | 設定と起動 | 設定の読み込み、`.env`、CLI、各コンポーネントの組み立て | `config.py`、`main.py`（CLI と組み立てだけ。処理の流れは各コンポーネントのモジュール。`L3_composition.md`） | ✅ |
| C8 | 実験 | 過去の記録を別の設定で再現し比較する（R7） | 🆕（結果が貯まる 2027 年春以降） | 🆕 |

## 4. 処理の流れ（コマンド）

```
tickers ─▶ fetch ─▶ calendar ─▶ analyze ─▶ docs ─▶ review 🆕 ─▶ （人の判断）
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
| `review-eval` 🆕 | 正解のある銘柄、文書ストア、LLM | 記録（`review_evals`）、合否（不合格は終了コード 1） | モデル・プロンプトを変えたとき（`review` の前提） |
| `review` 🆕 | 二次候補、文書ストア、LLM | 記録（`reviews`）、調査メモ | `docs` と `review-eval` の合格の後 |
| `evaluate` | 記録、Yahoo の価格履歴 | 記録（`outcomes`） | 随時 |
| `llm-check` | LLM、検索 | 疎通の結果 | 任意（ライブ確認。CI では実行しない） |

## 5. データの受け渡し（コンポーネント間の約束）

E2E テストは、この表の形式が守られることを確かめる。

| 境界 | 形式 | 主な内容 | 状態 |
|---|---|---|---|
| C1 → C2・C3 | `japan_tickers.csv` | code、name、market、sector33、size | ✅ |
| C2 → C3 | キャッシュ（DuckDB `stock_cache`） | 銘柄ごとの info、財務・四半期損益・株価（JSON） | ✅ |
| C2 → C3 | `earnings_calendar.csv` | code、announce_date、period_en、fiscal_year_end | ✅ |
| C3 → C6 | 結果 CSV | `output.columns` の列（順位、二次候補、改善区分、質の旗、指標、次回決算日） | ✅ |
| C3 → C5 | `screen_results` | 全銘柄の通過・落ちた条件・改善区分・二次候補（`stage2_candidate` 列）・質の旗（リスト）・次回決算日・全指標（JSON）。項目名は `fields.py` が唯一の定義 | ✅ |
| C5 → C2・C4 | `RecordStore.candidates` | 実行の二次候補（`stage2_candidate` 列で選ぶ）と指標 | ✅ |
| C2 → C4 | 文書ストア 🆕 | 文書 ID、出典（URL・EDINET の書類 ID）、取得日時、本文 | 🆕 |
| C4 → C5 | `reviews` 🆕 | 調査結果、照合できた根拠、照合率、モデル・プロンプトの版（git 対象外：公開リポジトリに引用を載せない） | 🆕 |
| C5 → C8 | 記録（Parquet） | `runs`・`screen_results`・`outcomes`（`records/`、コミット）、`reviews`（`review.export_dir`、git 対象外） | ✅／🆕 |

## 6. 横断的な決まり

- **設定**：調整値・パス・ファイル名はすべて `config.yaml`。`load_config` を呼ぶのは `config.py` と `main.py` だけ（アーキテクチャテストで強制）。
- **秘密情報**：API キーは `.env`（git 対象外）と環境変数だけ。キーをログ・例外・出力に出さない（N2）。
- **失敗の扱い**：外部取得の失敗は銘柄単位で記録して続行（N6）。
- **品質ゲート**：ruff、mypy、vulture、deptry、pytest（カバレッジ 85% 以上）、コード予算。フックとCI で強制。

## 7. E2E テスト計画

外部システムはすべてモック・フィクスチャで置き換え、ネットワークを使わない。本物の API を使う疎通確認（`llm-check`、`calendar`）は CI に入れず、手動の「ライブ確認」とする。

| ID | シナリオ | 確かめること（合格基準） | 対応する要件 | 状態 |
|---|---|---|---|---|
| E1 | フィクスチャのキャッシュで `analyze` | 結果 CSV が 5 章の形式で、正解（ゴールデン）と一致。全銘柄が `screen_results` に記録され、Parquet が書かれる | R1・R2・R4・R6・N1 | 部分的にある（`test_regression.py`、`test_records.py`）→ 整理して E2E に |
| E2 | 決算日を含む `calendar` → `analyze` | 予定日が結果 CSV と記録に入る。予定日がないときは空 | R3 | 部分的にある |
| E3 | Yahoo をモックした `fetch`（一部失敗） | 成功した銘柄はキャッシュに、失敗は取得失敗 CSV に。全体は止まらない | N6 | 部分的にある |
| E4 | 記録＋モックの価格で `evaluate` | 期間を過ぎた実行だけ `outcomes` が計算される | R6 | 部分的にある |
| E5 | `--config` で別の設定 | 閾値が変わり、出力と記録が別の場所に書かれる | R7 | ある |
| E6 | 文書ストアにある二次候補で `review`（LLM をモック） | `reviews` に記録され、照合できない引用の主張は捨てられ、調査メモが出る。キーが出力に現れない | R5・N2・N3・N4 | 🆕 |
| E7 | 二次候補で `docs`（EDINET・検索・Web をモック、一部失敗） | 候補ごとの文書が文書ストアに入り、失敗は記録されて全体は止まらない。キーが出力に現れない | R5・N2・N6 | ある |

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
| N1 | C5 | E1 |
| N2 | C2、C4、C7 | E6、E7 |
| N3 | C4 | E6 |
| N4 | C4 | E6 |
| N5 | C7 | ゲート（設計の関門 `tests/unit/test_design_docs.py`、`tests/unit/test_architecture.py`、コード予算） |
| N6 | C2 | E3、E7 |

## 9. 機械的な強制（この設計を守らせる仕組み）

1. テストに階層の印を付ける（pytest のマーカー `e2e`・`integration`・`unit`）。各要件に最低 1 つの E2E があることをテストで確かめる。
2. 本書 3 章のモジュール一覧と、実際の `src/` のモジュールが一対一で対応することをテストで確かめる（設計にないモジュールがあれば失敗）。
3. 変更は設計書 → テスト → コードの順。PR／マージのメッセージに、変更した設計書の節を書く。
4. コンポーネント間で受け渡す結果行の項目名と値（改善区分など）は `fields.py` だけが文字列で持つ。`src/`・`main.py` の他の場所にその文字列があれば失敗し、`output.columns` が `fields.py` にない項目を挙げても失敗する（`tests/unit/test_architecture.py`）。

## 10. 決定事項（2026-10-14）

| 項目 | 決定 |
|---|---|
| 要件（1 章）とコンポーネント（3 章） | 提案どおり |
| E2E 計画（7 章） | 提案どおり。本物の API の疎通確認は CI に入れず、手動のライブ確認とする |
| L2 の順番 | C4 二次調査と C2 データ取得から |

## 11. 訂正履歴

- 2026-10-14：3 章に、追加予定のモジュール名（L2 で決定）を記載

- 2026-10-14：追跡表に N5 が抜けていた。E2E ではなく関門（設計の関門・アーキテクチャテスト・コード予算）で守る要件として追加

- 2026-10-15（承認済み）：文書の取得を `review` から `docs` コマンドに分けた（E7 を追加）。理由：文書の取得だけを LLM の費用なしにやり直せる。また L2 C2 のモジュールを `review` より前に呼び出し元つきでマージでき、未使用コードの関門（vulture）を通せる

- 2026-10-15（承認済み）：C3 の結果行の項目名を `fields.py` に集め（3 章・5 章）、文字列の重複を禁じる関門を追加（9 章 4）。理由：項目名が 2〜4 モジュールに文字列で重複し、つづりの違いが空の値になるだけで検出されなかった。`screen_results` に `stage2_candidate` 列を追加し、使われていない `types` 列を削除、質の旗はリストのまま記録する

- 2026-10-16：SOLID の見直し。順位づけを `report.py` から `selection.py` へ（`report.py` は出力だけ）、呼び出し間隔の制御を `llm.py` から `throttle.py` へ（EDINET・Web・LLM が共有）

- 2026-10-17（承認済み）：組み立ての見直し（`L3_composition.md`）。`main.py` を CLI と組み立てだけにし、`docs`・`review` の流れを `collect.py`・`review.py` へ。モデルの品質の関門 `review_eval.py` と `review-eval` コマンドを追加
