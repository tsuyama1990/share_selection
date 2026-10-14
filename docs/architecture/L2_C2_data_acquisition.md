# L2 詳細設計：C2 データ取得

作成：2026-10-14 ／ 状態：**承認（2026-10-14）・QA 完了**　親：`L1_architecture.md` C2　対応テスト：結合テスト（7 章）

凡例：✅ 実装済み ／ 🆕 未実装

## 1. 責務

外部システムからデータを取得し、後段（C3 一次・C4 二次）が使う形で保存する。取得の失敗は銘柄・文書単位で記録し、全体は止めない（L1 N6）。

| 範囲 | 内容 | 状態 |
|---|---|---|
| 株価・財務 | Yahoo Finance → キャッシュ（DuckDB `stock_cache`） | ✅ |
| 決算発表予定日 | JPX → `earnings_calendar.csv` | ✅ |
| 有価証券報告書 | EDINET → 文書ストア（必要な節の本文） | 🆕 |
| Web 文書 | Gemini 検索の出典 URL・決算短信 → 文書ストア（本文） | 🆕 |

## 2. モジュール

| モジュール | 責務 | 状態 |
|---|---|---|
| `yahoo.py` | Yahoo Finance からの取得（財務・株価・四半期損益、調整済み終値） | ✅ |
| `cache.py` | キャッシュの読み書き、鮮度、取得失敗の扱い | ✅ |
| `stock_data.py` | 1 銘柄の生データの型（形を知る唯一の場所） | ✅ |
| `earnings_calendar.py` | JPX の決算発表予定日の取得・解析・統合 | ✅ |
| `edinet.py` | EDINET API v2：書類一覧の走査と索引、有価証券報告書の取得、必要な節の抽出 | 🆕 |
| `webfetch.py` | URL の取得（リダイレクト追従）と本文の抽出（HTML・PDF） | 🆕 |
| `docstore.py` | 文書ストア：取得した文書の本文と出典の保存・検索 | 🆕 |

## 3. EDINET（`edinet.py`）

### 3.1 事実（[データ：2026-10-14 実測]）

- 書類一覧 `GET /api/v2/documents.json?date=YYYY-MM-DD&type=2`。**提出日ごと**にしか引けない。各書類に `docID`、`edinetCode`、`secCode`（証券コード＋末尾 1 桁、例 `65990`）、`docTypeCode`（有価証券報告書 = `120`）、`periodEnd`、`csvFlag` がある。
- 書類取得 `GET /api/v2/documents/{docID}?type=5` は ZIP。中の `XBRL_TO_CSV/jpcrp…-asr-….csv` が本文（タブ区切り・UTF-16、列：要素ID・項目名・…・値）。
- エブレンの有価証券報告書（`S100YI0V`、2026-06-25 提出）の本文 CSV に、テキストブロックが 132 要素。事業の内容 `DescriptionOfBusinessTextBlock`、経営方針・経営環境・対処すべき課題 `BusinessPolicyBusinessEnvironmentIssuesToAddressEtcTextBlock`、事業等のリスク `BusinessRisksTextBlock`、セグメント情報 `NotesSegmentInformationEtcConsolidatedFinancialStatementsTextBlock` などを確認。
- 認証は `Subscription-Key`（`.env` の `EDINET_API_KEY`）。

### 3.2 設計

| 処理 | 入力 → 出力 | 方針 |
|---|---|---|
| 索引の更新 | 日付の範囲 → 索引（文書ストアの `edinet_index`：docID、secCode、docTypeCode、periodEnd、提出日） | 初回は過去 `edinet.index_days`（例 450 日）を走査。以後は前回の最終日から今日まで。3 月決算の有価証券報告書は 6 月下旬に集中 |
| 最新の有価証券報告書 | 証券コード → docID | 索引から `docTypeCode = 120` かつ最新の `periodEnd` |
| 本文の取得と節の抽出 | docID → 節ごとの本文 | `type=5` の ZIP から本文 CSV を読み、`edinet.sections` に列挙した要素だけを抜く（HTML タグを除いたテキスト）。節は config で増減できる |
| 保存 | 節ごとの本文 → 文書ストア | 文書 ID = `edinet:{docID}:{要素名}`。同じ docID は取り直さない |

失敗（HTTP エラー、ZIP 不正、節が無い）は文書ストアの失敗記録に残し、次の銘柄へ進む。

## 4. Web 文書（`webfetch.py`）

| 処理 | 方針 |
|---|---|
| 取得 | Gemini 検索の出典はリダイレクト URL（`vertexaisearch.cloud.google.com/grounding-api-redirect/…`）[データ]。リダイレクトを追って最終 URL を記録する |
| 本文の抽出 | HTML：本文テキスト（スクリプト・ナビゲーションを除く）。PDF：テキスト抽出。使うライブラリは L3 で決める（候補：HTML は標準の解析＋簡易抽出、PDF は `pypdf`） |
| 保存 | 文書 ID = `web:{最終 URL の正規化ハッシュ}`。取得日時・タイトル・最終 URL を保存 |
| 制限 | タイムアウト、最大サイズ、User-Agent、取得間隔は config。robots.txt やサイトの利用規約に反する一括取得はしない（検索結果の出典を 1 件ずつ取るだけ） |

## 5. 文書ストア（`docstore.py`）

保存先：DuckDB の別ファイル（`docstore.db_file`、例 `documents.duckdb`。git 対象外）。キャッシュ（消して取り直せる）とも記録（取り直せない）とも分ける。文書は取り直せるが、時間がかかるため保存する。

| テーブル | 列 |
|---|---|
| `documents` | doc_id（主キー）、ticker、source（edinet／web）、source_ref（docID・要素名、または最終 URL）、title、fetched_at、text、text_sha256 |
| `edinet_index` | doc_id、sec_code、edinet_code、doc_type_code、period_end、submit_date |
| `fetch_errors` | ticker、source、ref、error、at |

C4 への約束（L1 5 章「C2 → C4 文書ストア」）：C4 は `documents` の `text` を LLM に渡し、引用の照合も同じ `text` に対して行う。**本文は保存後に書き換えない**（照合の根拠が変わらないように。取り直したら新しい doc_id にする）。

## 6. 設定（`config.yaml` に追加する節）

`edinet:`（base_url、key_env、index_days、sections、request_interval_s）、`webfetch:`（timeout_s、max_bytes、user_agent、request_interval_s）、`docstore:`（db_file）。

## 7. 結合テスト計画

すべて HTTP はモック（`httpx.MockTransport`）、DB は一時ファイル。

| ID | 対象 | 確かめること | 状態 |
|---|---|---|---|
| I-C2-1 | Yahoo 取得 → キャッシュ | 取得・鮮度・四半期損益の往復、失敗の扱い | ✅（`tests/integration/test_cache.py` など） |
| I-C2-2 | JPX 予定日の取得・統合 | 複数ファイルの統合、未定・過去日の扱い | ✅（`tests/integration/test_earnings_calendar.py`） |
| I-C2-3 | EDINET 索引 → 最新の有価証券報告書 → 節の抽出 → 文書ストア | 索引の差分更新、120 の最新の選択、ZIP の本文 CSV から指定節だけ保存、同じ docID は取り直さない、失敗の記録 | 🆕 |
| I-C2-4 | Web 取得 → 文書ストア | リダイレクト追従、HTML・PDF の本文抽出、サイズ上限、失敗の記録 | 🆕 |
| I-C2-5 | 文書ストア | 保存・取得、本文を書き換えない（同じ doc_id への上書きを拒否） | 🆕 |

## 8. 先送り（2026-10-14 承認）

- HTML・PDF の抽出ライブラリ：L3 で決める（先送り、理由：L3 の範囲）。
- 決算短信の定期収集（TDnet は 31 日分のみ）：フェーズ 1 では Web 検索の出典として取るだけにし、定期収集は先送り（理由：検索で直近の短信に届くかを、まず実データで確かめる）。

## 9. 訂正履歴

（なし）
