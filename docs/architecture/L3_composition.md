# L3 クラス設計：組み立てと処理の流れ、二次調査の実行と品質の関門

作成：2026-10-17 ／ 状態：**承認（2026-10-17）**　親：`L1_architecture.md` 3 章（C2〜C7）、`L2_C2_data_acquisition.md`、`L2_C4_stage2_research.md`　関連：`L3_stage2_classes.md`（各モジュールのクラス）　対応テスト：単体（5 章）、結合・E2E（6 章）

凡例：✅ 実装済み ／ 🆕 未実装。根拠：[データ：日付]＝実測、[推論]＝未検証の判断。

## 1. 見直しの理由（SOLID の監査、2026-10-17）

| # | 問題 | 原則 |
|---|---|---|
| 1 | `main.py`（290 行、`review` を足すと約 370 行 [推論]）が、組み立てだけでなく処理の流れそのもの（全銘柄の判定の繰り返し、候補ごとの取得・スキップ・割り当ての停止、記録の行の組み立て）を持つ。E2E でしか確かめられない | 単一責任 |
| 2 | 一次の結果を記録へ渡す形が文字列キーの辞書（`"ticker"`、`"stage1_pass"` など）、実行情報も文字列キーの辞書。結果行の項目名を `fields.py` に集めたのと同じ弱さが残る | 型のある約束 |
| 3 | クライアントとストアを設定から作る処理が各所に散る（`RecordStore(...)` 4 か所、Gemini 2 か所、API キーの確認が 2 通り） | 重複・依存の逆転 |
| 4 | L3（`L3_stage2_classes.md`）の計画では、候補ごとの二次調査の流れが `research.review_ticker` と `main.run_review` に分かれる | 単一責任 |

## 2. 方針

- **`main.py` は CLI と組み立てだけ**：引数の解析、設定と `.env` の読み込み、各部品の生成、処理の呼び出し、要約の表示。コマンドは `COMMANDS` 辞書（名前 → 関数）で選ぶ。処理の流れ（繰り返し・スキップ・停止）は `src/` に置き、結合テストで確かめる。
- **部品は自分の `from_config` で作る**（既存の `Screener.from_config` と同じ形）。API キーは `config.require_key(env, name)` が唯一の確認の場所で、無ければ `MissingKeyError`（`main.py` が捕まえて終了コード 1）。
- **コンポーネント間の受け渡しは型で**：一次の結果は `ScreenResult`（行は `fields.py` の項目名）、実行情報は `records.RunInfo`。記録の列は `records.py` が `ScreenResult` から作る。
- 新しい設定値はすべて `config.yaml`（プロンプト・評価の正解はファイルにして、その場所を `config.yaml` に置く）。

## 3. モジュールと公開する名前

既存モジュールの変更は 4 章に書く。ここには新しいモジュールだけを載せる（設計の関門が公開名を照合する）。

| モジュール | 公開する名前 | 責務 | 状態 |
|---|---|---|---|
| `collect.py` | `CollectClients`、`CollectSettings`、`CollectSummary`、`collect_documents` | `docs` の流れ：EDINET の索引の更新と有価証券報告書、Web 文書がまだ無い候補だけを優先順に検索し出典を取得、検索の割り当てで停止 | ✅ |
| `review.py` | `ReviewSettings`、`ReviewSummary`、`review_candidates` | `review` の流れ：業種の中央値、候補ごとに文書の読み出し → T1〜T5（`research.py`）→ 照合（`verify.py`）→ 記録 → 調査メモ。銘柄の失敗は状態として記録して次へ | 🆕 |
| `review_eval.py` | `EvalCase`、`EvalResult`、`load_eval_cases`、`score_case`、`judge` | モデルの品質の関門：正解のある銘柄の調査結果の採点と合否 | 🆕 |

## 4. 既存モジュールの変更

| モジュール | 変更 |
|---|---|
| `config.py` | `MissingKeyError`、`require_key(env, name)` を追加 |
| `main.py` | `run_*` の処理の流れを `src/` へ移し、`cmd_<コマンド>(cfg, args)`（各 10 行程度）と `COMMANDS` だけにする。`get_japan_tickers`・`require_env`・`collect_web_documents` を削除 |
| `screener.py` | `screen_universe(tickers, cache, screener, calendar) -> dict[str, ScreenResult]`（キャッシュの無い銘柄、決算予定日の項目を含む）。`NO_CACHE` を `records.py` から移す |
| `records.py` | `RunInfo`（dataclass）。`record_run(info: RunInfo, results: Mapping[str, ScreenResult])` が列を `fields.py` の項目から作る（文字列キーの辞書をやめる）。`from_config(cfg, root)`。`reviews`・`review_evals` テーブル、`record_review`、`reviewed`、`run_metrics`、`passed_eval` |
| `cache.py` | `from_config(cfg, root)`、`refresh_all(cache, client, tickers, max_age_days) -> dict[str, str]`（失敗した銘柄 → 理由） |
| `report.py` | `write_failures(failures, out_dir, filename)` を追加（`fetch` の失敗 CSV） |
| `yahoo.py`・`docstore.py`・`edinet.py`・`llm.py` | `from_config`（`edinet`・`llm` は `env` を受け取りキーを `require_key` で取る）。`LLMClient`・`GeminiSearch` の組み立ての重複を消す |
| `research.py` | `review_ticker` を削除（流れは `review.py`）。1 タスクの実行（`run_task`）までを持つ |

## 5. クラス・関数（新しいモジュール）

### 5.1 `collect.py`

```python
@dataclass(frozen=True)
class CollectSettings:          # from_config(cfg)：edinet・webfetch・docs の値
    index_days: int; doc_type_code: str; sections: list[str]
    search_prompt: str; max_sources: int; max_bytes: int

@dataclass(frozen=True)
class CollectSummary:
    edinet_docs: int; edinet_failed: int; web_docs: int; searches_left: int   # 割り当てで止まったときの残り

@dataclass(frozen=True)
class CollectClients:           # from_config(cfg, env, stack)：HTTP クライアントを stack に開き、キーを require_key で確認
    edinet: EdinetClient; search: GeminiSearch | None; web_http: httpx.Client
    search_limiter: RateLimiter; fetch_limiter: RateLimiter

def collect_documents(candidates, settings, clients, store, today) -> CollectSummary
```

- 候補は `RecordStore.candidates` の (ticker, 指標)。検索は `docs.search` が真で `clients.search` が与えられたときだけ（偽なら `clients.search` は None）。
- Web 文書がまだ無い候補だけを `Priority_Rank` の良い順に検索する。`QuotaExceeded` で止め、残りの数を返す。

### 5.2 `review.py`

```python
@dataclass(frozen=True)
class ReviewSettings:           # from_config(cfg)：review・sector の値
    max_tickers: int; min_verified_ratio: float; max_doc_chars: int
    prompt_version: str; task_fields: dict[str, list[str]]; sector_metrics: list[str]; min_peers: int

@dataclass(frozen=True)
class ReviewSummary:
    reviewed: int; failed: int; needs_attention: int; memo_paths: list[Path]

def review_candidates(run_id, tickers, settings, llm, prompts, records, store, sectors, memo_dir) -> ReviewSummary
```

- 対象：`tickers` が与えられればそれ（評価・少数での確認用）、無ければ実行の二次候補のうち `reviewed(run_id)` に無いものを `Priority_Rank` の順に `max_tickers` 件。
- 1 銘柄：文書を `max_doc_chars` で切る → T1〜T4 → T5（T1〜T4 の照合済みの answer を文脈に）→ `check_claims` → `record_review` → `render_memo` を書き出す。業種の比較（`sector.py`）と調査メモ（`memo.py`）はブランチ C で足す（B では `sector_comparison` は空、メモは出さない。`ReviewSettings` の sector の値と `sectors`・`memo_dir` の引数も C で足す）。失敗（文書が無い、全プロバイダーの失敗、JSON 不正）は status に残して次へ。
- **品質の関門**：`records.passed_eval(prompt_version, first_model)` が偽なら、評価以外の実行を拒む（`main.py` が「先に `review-eval` を」と表示して終了コード 1）。

### 5.3 `review_eval.py`（モデルの品質の関門）

正解の銘柄（L2 C4 8.1 節。`docs/hypothesis_map.md` で事実を確かめたもの）を YAML（`review.eval.cases_file`、例 `eval/stage2_cases.yaml`）に置く。

```python
@dataclass(frozen=True)
class EvalCase:
    ticker: str; task: str; field: str
    expect_any: list[str]       # 照合済みの answer か根拠の引用に、どれか 1 つが含まれれば合格（空なら「項目が unknown でない」）
    basis: str                  # 出典（hypothesis_map の節）

@dataclass(frozen=True)
class EvalResult:
    cases: int; hits: int; parse_failures: int; min_verified_ratio: float; passed: bool

def load_eval_cases(path: Path) -> list[EvalCase]
def score_case(case: EvalCase, review_row: dict) -> bool
def judge(results: list[tuple[EvalCase, bool]], review_rows: list[dict], thresholds: dict) -> EvalResult
```

`review-eval` コマンド：評価の銘柄で `review_candidates(tickers=...)` を実行し（記録先は通常と同じ `reviews` だが run_id は評価用に `eval-<日時>`）、`judge` の結果を `review_evals` に記録して表示する。不合格なら終了コード 1。

**合格の条件**（値はすべて `review.eval:` に置く）：

| 条件 | 初期値 | 理由 |
|---|---|---|
| 正解の一致率（hits ÷ cases） | 0.8 以上 | 軽いモデルでも事実の取り違えを許さない。6 社中 1 件の外れまで |
| JSON の不正（再依頼の後も不正） | 0 件 | 不正が出るモデルは本番で銘柄を落とす |
| 銘柄ごとの照合率の最小値 | `review.min_verified_ratio`（0.7）以上 | 引用の捏造が多いモデルを止める |

初期の正解（`eval/stage2_cases.yaml` の中身。値は実装の前に `hypothesis_map.md` と照合する）：

| 銘柄 | タスク・項目 | expect_any |
|---|---|---|
| 5232.T 住友大阪セメント | T1・source_type の根拠 | 値上げ、価格改定、販売価格 |
| 6599.T エブレン | T1・demand_wave | 半導体 |
| 6430.T ダイコク電機 | T4・reason_forgotten の根拠 | 減益 |
| 9628.T 燦ホールディングス | T2・one_off_items | （空でない） |
| 5975.T 東プレ | T2・one_off_items | （空でない） |
| 4044.T セントラル硝子 | T2・one_off_items | （空でない） |

評価は本物の API を使うライブの関門（CI には入れない）。モデルの順番・プロンプトの版を変えたら必ず実行する。`review` は合格の記録がないと動かない（上の 5.2）ので、実行を忘れても本番は走らない。

## 6. 単体テスト計画

| ID | 対象 | 確かめること |
|---|---|---|
| U-review_eval-1 | `score_case` | expect_any の一致（answer・引用のどちらでも）、不一致、空の expect_any は項目が unknown でなければ合格 |
| U-review_eval-2 | `judge` | 一致率・JSON の不正・照合率の最小値の、それぞれ境界での合否 |
| U-review_eval-3 | `load_eval_cases` | YAML の読み込み、必須の項目の欠けで失敗 |
| U-collect-1 | `CollectSettings` | 設定から作る（`from_config`） |
| U-review-1 | `ReviewSettings` | 設定から作る（`from_config`） |

`config.require_key`（キーが無いと `MissingKeyError`）と `records.RunInfo` は既存のテストファイル（`tests/unit/test_architecture.py` の隣に `tests/unit/test_config.py`、`tests/integration/test_records.py`）で確かめる。

### 6.1 結合・E2E

| 階層 | 対象 | 確かめること |
|---|---|---|
| 結合 | `collect_documents`（モック HTTP、一時 DB） | I-C2-3・I-C2-4 に加え、スキップ・優先順・割り当てで停止（今は E7 にあるものを結合へ移す） |
| 結合 | `review_candidates`（偽の LLM、一時 DB） | I-C4-4（1 銘柄分）、品質の関門で拒む |
| 結合 | `review-eval`（I-C4-5） | 合否の記録、合格が無いと `review` が拒む |
| 結合 | `records.record_run(RunInfo, ScreenResult)` | 列が `fields.py` の項目から作られる、`reviews`・`review_evals` の往復 |
| E2E | 既存の E1〜E5・E7 | 変更の前後で出力が同じ（ゴールデン、実データの全件の比較） |
| E2E | E6 `review`、`review-eval` | 評価の合否で `review` が動く・止まる、調査メモが出る、キーが出力に出ない |

## 7. 設定（`config.yaml`）

| 節 | 追加・変更 |
|---|---|
| `llm.providers` | 先頭に `gemini-3.5-flash-lite`（無料枠：1 日 379 回以上、64k トークンの入力 [データ：2026-10-16]）、次に `gemini-2.5-flash`、Groq、DeepSeek |
| `review` | max_tickers、min_verified_ratio、prompt_dir、prompt_version、max_doc_chars、tasks（タスクごとの項目名）、export_dir、`eval:`（cases_file、min_hit_rate、max_parse_failures） |
| `sector` | metrics、min_peers |
| `memo` | dir（`results/` の下）、filename |

## 8. 実装の順番

| 順 | ブランチ | 中身 | 挙動 |
|---|---|---|---|
| A | `refactor/composition` | 4 章の既存モジュールの変更（`RunInfo`、`screen_universe`、`from_config`、`require_key`、`refresh_all`、`write_failures`、`collect.py`、`main.py` の `COMMANDS`）。E7 の流れのテストを `collect_documents` の結合テストへ | 変えない（ゴールデンと実データの全件が一致） |
| B | `feat/review-command` | `verify.py`、`research.py`（`run_task` まで）、`review.py`、`review_eval.py`、`prompts/v1/`、`eval/stage2_cases.yaml`、`reviews`・`review_evals`、`review`・`review-eval` コマンド、プロバイダーの順番 | 新機能。ライブで評価を実行し、結果を報告して承認を受けてからマージ |
| C | `feat/review-sector-memo` | `sector.py`、`memo.py` | 新機能 |

各ブランチの後に bonsai。A の後、`main.py` は 150 行以下を目安にする [推論]。

## 9. 訂正履歴

- 2026-10-17（ブランチ A の実装）：5.1 節の `collect_documents` の引数が 8 個で ruff の PLR0913（5 個まで）を超えるため、依存を `CollectClients`（edinet・search・web_http・二つのリミッター）にまとめ、`collect_documents(candidates, settings, clients, store, today)` にした。`CollectSettings.search` は `clients.search is None` と重複するので削除（`main.py` は `docs.search` を `CollectClients.from_config` 経由で読む）。`SECONDS_PER_MINUTE` は `llm.py` に置く。`latest_issue`・`git_sha` は `main.py` から `records.py`（`RunInfo` の隣）へ移した。`GeminiSearch.search` の「キー無し」検査は `from_config` の `require_key` に置き換えて削除。
