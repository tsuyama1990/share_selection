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
| `review.py` | `ReviewDeps`、`ReviewSettings`、`ReviewSummary`、`review_candidates` | `review` の流れ：業種の中央値、候補ごとに文書の読み出し → T1〜T5（`research.py`）→ 照合（`verify.py`）→ 記録 → 調査メモ。銘柄の失敗は状態として記録して次へ（B：業種の中央値・調査メモはまだ無い） | ✅ |
| `review_eval.py` | `EvalCase`、`EvalResult`、`EvalGate`、`load_eval_cases`、`score_case`、`judge`、`combine`、`evaluate_model` | モデルの品質の関門：正解のある銘柄の調査結果の採点と合否 | ✅ |

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

def collect_documents(companies: list[Company], settings, clients, store, today) -> CollectSummary
```

- `companies` は優先順（良い順）に並べて渡す（`docs` は `Priority_Rank` 順、`review-eval` は評価の銘柄の順）。名前は日本語（`japan_tickers.csv` の `name`、無ければ指標の `Name`。評価は `EvalCase.name`）で、検索の指示の `{name}` に入れ、Web 文書の会社名の照合にも使う。検索は `docs.search` が真で `clients.search` が与えられたときだけ（偽なら `clients.search` は None）。
- Web 文書がまだ無い会社だけを、渡された順に検索する。`QuotaExceeded` で止め、残りの数を返す。

### 5.2 `review.py`

```python
@dataclass(frozen=True)
class ReviewSettings:           # from_config(cfg)：review の値と memo.filename（C）
    max_tickers: int; min_verified_ratio: float; max_doc_chars: int
    prompt_version: str; task_fields: dict[str, list[str]]; context_metrics: list[str]
    memo_filename: str

@dataclass(frozen=True)
class ReviewSummary:
    reviewed: int; failed: int; needs_attention: int      # メモの場所は main.py が memo.dir を表示する（memo_paths は作らない）

@dataclass(frozen=True)
class ReviewDeps:               # 引数を 5 個に収めるための束
    llm: LLMClient; prompts: dict[str, str]; records: RecordStore; store: DocStore
    peers: Peers | None; memo_dir: Path | None            # C。評価は両方 None

def review_candidates(run_id, candidates, tickers, settings, deps) -> ReviewSummary
```

- 対象：`tickers` が与えられればそれ（少数での確認用。`max_tickers` の対象外）、無ければ `candidates`（`RecordStore.candidates` の (ticker, 指標)。評価では正解の銘柄から作る）のうち `reviewed(run_id)` に無いものを `Priority_Rank` の順に `max_tickers` 件。
- 1 銘柄：文書を `max_doc_chars` で切る → T1〜T4 → T5（T1〜T4 の照合済みの answer を文脈 `verified_answers` に。照合は `run_task` の中）→ `record_review`（B）→ `render_memo` を書き出す（C）。文脈は銘柄コード・名前と `review.context_metrics` の指標。銘柄の照合率はタスクごとの照合率の平均。`needs_attention` は成功した銘柄の照合率が `min_verified_ratio` 未満のとき。業種の比較（`sector.py`）と調査メモ（`memo.py`）はブランチ C で足す：`ReviewDeps` に `peers: Peers | None` と `memo_dir: Path | None` を足す。`main.py` が実行の全銘柄の指標（`records.run_metrics`）と銘柄一覧の業種（`tickers.read_column(csv, "sector33")`）から `Peers` を 1 回作る。評価（`review-eval`）は両方 None（同業比較なし、メモなし）。銘柄ごとに `compare` を `reviews.sector_comparison` に記録し、`render_memo` を書き出す。`tickers.read_names` は `read_column(csv, "name")` に置き換える。失敗（文書が無い、全プロバイダーの失敗、JSON 不正）は status に残して次へ。
- **品質の関門**：`records.passed_eval(prompt_version, first_model)` が偽なら、評価以外の実行を拒む（`main.py` が「先に `review-eval` を」と表示して終了コード 1）。

### 5.3 `review_eval.py`（モデルの品質の関門）

正解の銘柄（L2 C4 8.1 節。`docs/hypothesis_map.md` で事実を確かめたもの）を YAML（`review.eval.cases_file`、例 `eval/stage2_cases.yaml`）に置く。

```python
@dataclass(frozen=True)
class EvalCase:
    ticker: str; name: str; task: str; field: str
    expect_any: list[str]       # 照合済みの answer か根拠の引用に、どれか 1 つが含まれれば合格（空なら「項目が unknown でない」）
    basis: str                  # 出典（hypothesis_map の節）

@dataclass(frozen=True)
class EvalResult:
    cases: int; hits: int; parse_failures: int; min_verified_ratio: float; passed: bool

def load_eval_cases(path: Path) -> list[EvalCase]
def score_case(case: EvalCase, review_row: dict) -> bool
def judge(results: list[tuple[EvalCase, bool]], review_rows: list[dict], thresholds: dict) -> EvalResult
```

`review-eval` コマンド：評価の銘柄は二次候補ではないので、まず `collect_documents` で評価の銘柄（名前は `EvalCase.name`）の文書を集め、次に `review_candidates(tickers=...)` を実行し（記録先は通常と同じ `reviews` だが run_id は評価用に `eval-<日時>`）、`judge` の結果を `review_evals` に記録して表示する。不合格なら終了コード 1。

**評価の文書は EDINET だけ**（2026-10-17 追加、ユーザー承認）：Web 検索の出典は実行ごと・日ごとに変わり、検索の割り当て（1 日約 20 回）も使う。評価は `review.eval.sources`（`[edinet]`）の文書だけで行い、Web 検索をしない。毎回同じ文書でモデルだけを比べられる。本番の `review` は `review.sources`（`[edinet, web]`）。

**反復**（2026-10-17 追加、ユーザー承認）：同じモデル・同じプロンプトでも合否が揺れた（8.1 節 S0：3 回中 1 回だけ合格）。`evaluate_model` は文書を 1 回集めた後、評価の銘柄の調査を `review.eval.repeats` 回（初期値 3）繰り返し、回ごとに `judge` する。`combine` が回ごとの結果をまとめ、**すべての回が合格したときだけ合格**とする（一致数・JSON の不正・主のモデル以外の回答は合計、照合率は最小）。`review_evals` には 1 回の `review-eval` につき 1 行（回ごとの結果は summary に）。

```python
def combine(results: list[EvalResult]) -> EvalResult
def evaluate_model(cases, candidates, settings, deps, gate) -> list[EvalResult]   # 回ごとの結果。gate は閾値・回数・主のプロバイダー
```

**合格の条件**（値はすべて `review.eval:` に置く。各回で満たし、全回で合格）：

| 条件 | 初期値 | 理由 |
|---|---|---|
| 正解の一致率（hits ÷ cases） | 0.8 以上 | 軽いモデルでも事実の取り違えを許さない。6 社中 1 件の外れまで |
| JSON の不正（再依頼の後も不正） | 0 件 | 不正が出るモデルは本番で銘柄を落とす |
| 銘柄ごとの照合率の最小値 | `review.min_verified_ratio`（0.7）以上 | 引用の捏造が多いモデルを止める |

初期の正解（`eval/stage2_cases.yaml` の中身。2026-10-17 に `docs/hypothesis_map.md` と照合済み）：

| 銘柄 | タスク・項目 | expect_any | 根拠 |
|---|---|---|---|
| 5232.T 住友大阪セメント | T1・source_type | 値上げ、価格改定、販売価格 | [一次] 決算短信：セメントの値上げで営業利益 +46 億円（hypothesis_map H1b） |
| 6599.T エブレン | T1・source_type | 価格転嫁 | [一次] 有価証券報告書（S100YI0V、2026 年 3 月期）経営成績の分析：「値上がりした仕入れ部材の売価への価格転嫁が進んだことで、営業利益が増加」（営業利益 +14.2%、売上 −0.8%） |
| 6430.T ダイコク電機 | T5・suggestion | 落選、監視 | [一次][報道] 第 1 四半期 営業利益 −34.4%、通期予想 経常 −53%（H4a、N1 改善なし） |

燦ホールディングス・東プレ・セントラル硝子（「四半期 EPS の急増に一時的な損益が含まれるか」）は入れない：根拠が自分たちの旗（`Quality_Flags`）だけで、一次情報で確かめていない。正解として使うには、先に決算短信で一時的な損益を確かめる（確かめたら追加する）。3 件のため、一致率 0.8 以上は「3 件すべて一致」になる。

評価は本物の API を使うライブの関門（CI には入れない）。モデルの順番・プロンプトの版を変えたら必ず実行する。`review` は合格の記録がないと動かない（上の 5.2）ので、実行を忘れても本番は走らない。

## 6. 単体テスト計画

| ID | 対象 | 確かめること |
|---|---|---|
| U-review_eval-1 | `score_case` | expect_any の一致（answer・引用のどちらでも）、不一致、空の expect_any は項目が unknown でなければ合格 |
| U-review_eval-2 | `judge` | 一致率・JSON の不正・照合率の最小値の、それぞれ境界での合否 |
| U-review_eval-3 | `load_eval_cases` | YAML の読み込み、必須の項目の欠けで失敗 |
| U-review_eval-4 | `combine` | 全回合格で合格、1 回でも不合格なら不合格、合計と最小 |
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
| `llm` | `retries`・`retry_wait_s`：429・5xx・タイムアウトは同じプロバイダーで再試行してから次へ（無料枠は負荷で 503 を返す [データ：2026-10-16]。評価はフォールバックで答えると不合格のため） |
| `llm.providers` | 先頭に `gemini-3.5-flash-lite`（無料枠：1 日 379 回以上、64k トークンの入力 [データ：2026-10-16]）、次に `gemini-2.5-flash`、Groq、DeepSeek |
| `review` | max_tickers、min_verified_ratio、prompt_dir（版はプロンプトの内容のハッシュ）、max_doc_chars、tasks（タスクごとの項目名）、export_dir、`eval:`（cases_file、min_hit_rate、max_parse_failures） |
| `sector` | metrics、min_peers |
| `memo` | dir（`results/` の下）、filename |

## 8. 実装の順番

| 順 | ブランチ | 中身 | 挙動 |
|---|---|---|---|
| A ✅ | `refactor/composition` | 4 章の既存モジュールの変更（`RunInfo`、`screen_universe`、`from_config`、`require_key`、`refresh_all`、`write_failures`、`collect.py`、`main.py` の `COMMANDS`）。E7 の流れのテストを `collect_documents` の結合テストへ | 変えない（ゴールデンと実データの全件が一致） |
| B ✅ | `feat/review-command` | `verify.py`、`research.py`（`run_task` まで）、`review.py`、`review_eval.py`、`prompts/`、`eval/stage2_cases.yaml`、`reviews`・`review_evals`、`review`・`review-eval` コマンド、プロバイダーの順番 | 新機能。ライブで評価を実行し、結果を報告して承認を受けてからマージ |
| C ✅ | `feat/review-sector-memo` | `sector.py`、`memo.py` | 新機能 |

各ブランチの後に bonsai。A の後、`main.py` は 150 行以下を目安にする [推論]。

## 8.1 ライブのシナリオ試験（2026-10-17、`gemini-3.5-flash-lite`、プロンプトの版 1b250eef9b52）[データ]

| # | シナリオ | 期待 | 結果 |
|---|---|---|---|
| S1 | `docs`（一部の候補は検索済み） | 検索済みを飛ばし、割り当てで止まり残りを表示 | 50 社の EDINET、16 社の検索で 73 文書、「12 candidates left」 |
| S0 | `review-eval` を 3 回 | 毎回合格 | 合格 1 回・不合格 2 回（照合率の最小 0.67・0.50、ダイコクの T5 の外れ 1 回）。同じモデル・同じプロンプトで結果が揺れる |
| S2 | 上位 5 社の `review` | 5 社 ok | 5 社 ok、要注意 1 |
| S3b | `max_tickers: 3` の `review` | レビュー済みを飛ばし 6〜8 位 | 3 社（ok 2、JSON 不正 1 は状態として記録して次へ） |
| S4 | プロンプトを 1 文字変えた複製 | 拒否 | 拒否（新しい版に評価がない） |
| S5 | 誤った正解での評価 | 不合格・終了コード 1 | 1/3、不合格 |
| S6 | S5 の後の `review` | 拒否 | 拒否（最新の評価が不合格） |
| S7 | Gemini のキーなし | 拒否かキーのエラー | 拒否（主のモデルが Groq になり、その評価がない） |

結論：流れと関門は期待どおり。軽いモデルは評価の合否が揺れるため、関門に「k 回続けて合格」を足し（ユーザー承認、次のブランチ）、DeepSeek を同じ関門で試す。

## 10. 第 2 回の SOLID の見直し（2026-10-17、ブランチ C の後）

監査：vulture（信頼度 0）で未使用なし。調整値は config、それ以外の文字列・数値は名前付きの定数。問題は組み立てと記録に集中していた。

| # | 問題 | 対応 |
|---|---|---|
| M1 | `main.py`（264 行）に処理の流れが戻った（実行の選択、候補 → 会社の変換、評価用の設定の書き換え、閾値の組み立て、`Peers` の組み立て） | 各モジュールの関数・`from_config` へ移す。`main.py` は 150 行以下 |
| M2 | 処理する銘柄が `(ticker, 指標)` と `Company` の 2 つの形。評価は両方へ変換 | `RecordStore.candidates` は `Priority_Rank` の順で返す（並べ替えは 1 か所）。`collect.companies(candidates, names)` が会社の一覧を作る。評価の銘柄は `EvalCase.company`・`EvalCase` から作る |
| M3 | 評価の閾値が文字列キーの辞書 | `review_eval.EvalThresholds`（dataclass、`from_config`） |
| M4 | `open_review` が `ReviewDeps` を None 2 つで作り `replace` で埋める | `ReviewDeps.from_config(cfg, root, env, stack, peers, memo_dir)`、`Peers.from_run(records, run_id, sectors, cfg)` |
| M5 | 「指定の実行、無ければ最新」が 2 か所 | `RecordStore.resolve_run(run_id)` |
| M6 | `records.py`（304 行）が 5 つの役割 | `records.py`：実行・全銘柄の判定・候補・指標・答え合わせの保存と `RunInfo`。`outcomes.py` 🆕：答え合わせの計算（`evaluate`）。`review_store.py` 🆕：`ReviewStore`・`ReviewRow`（`reviews`・`review_evals`、別ファイル `review.db_file`、git 対象外。公開リポジトリに引用を載せない記録を物理的にも分ける） |
| M7 | 評価で検索を止めるのに設定の辞書を書き換える | `CollectClients.from_config(cfg, env, stack, search)`（検索の有無を引数で明示） |
| M8 | 評価の結果の整形が `main.py` | `report.format_eval`（出力は C6） |
| M9 | テストが通らない行が 7 モジュールに 18 行 | 1 行ずつ「テストを足す」か「消す」 |

挙動は変えない（ゴールデン、実データの全件の一致、ライブ E2E）。実運用の `records.duckdb` の空の `reviews`・`review_evals` テーブルは一度だけ消す（行は 0）。

## 9. 訂正履歴

- 2026-10-17：第 2 回の SOLID の見直し（10 章）

- 2026-10-17：評価の文書を EDINET だけにした（`review.eval.sources`）。エブレンの正解を「半導体の需要」（決算説明会・報道。直近の利益の理由としては一次情報で確かめていない）から、有価証券報告書の経営成績の分析にある「価格転嫁」へ。2 つのモデルとも、きれいな文書でこの文を引用した。プロンプトの並び（文書を先、タスクを後）を `prompts/user.md` に置き、版のハッシュに含める（同じ文書を 5 タスクで送るため、プロバイダーの前方一致のキャッシュが効く）

- 2026-10-17：評価を k 回続けての合格に（`review.eval.repeats`、`combine`・`evaluate_model`）。評価の流れを `main.py` から `review_eval.py` へ（`main.py` は組み立てだけ）

- 2026-10-17（ライブのシナリオ試験の結果）：上位 5 社の review で、判断の項目（T4・T5）の引用がプロンプト自身の型の説明文になり unknown になった → system に「判断の項目も文書の根拠の文を引用し、指示の説明文は引用しない」を追加。その後の評価でダイコクの T5 が unknown（「落選」と書かれた文を探した）→ T5 に「判断を決めた事実を引用する」を追加。版の名前と中身がずれる危険があるため、版をプロンプトの内容のハッシュにした（`review.prompt_version` を削除、`prompts/` を 1 つに）

- 2026-10-17（ライブの評価 1 回目の結果による修正）：不合格（2/3、照合率の最小 0.40、フォールバック 1 件）。原因と対応：(1) 照合率の計算がタスクの平均で「unknown」と正直に答えたタスクを 0 と数えていた → 銘柄の全 claims に対する割合へ。(2) 一時的な 503 で次のモデルへ移っていた → 同じプロバイダーで再試行。(3) 住友大阪セメントの T1 で、決算短信にある「値上げ」ではなく中計の半導体の話を源泉にした → T1 のプロンプトを v2 に（源泉は決算で会社が書いた利益の増減の理由）。v1 は削除。評価の判定に `fallback_rows`（主のモデル以外が答えた銘柄の数）を追加

- 2026-10-17（ブランチ B の実装）：(1) `run_task` の引数が 6 個で PLR0913 を超えるため、`task` と `fields` を 1 つの組 `task_fields: tuple[str, list[str]]`（`ReviewSettings.task_fields.items()` の 1 要素）にして 5 個にした。(2) `review_candidates` も同じ理由で依存を `ReviewDeps` にまとめ、評価の銘柄を渡せるよう `candidates` を引数にした（`tickers` は絞り込み）。(3) `ReviewSettings` に `context_metrics`（LLM に見せる一次の指標。`review.context_metrics`）を足し、sector の値と `ReviewSummary.memo_paths` は C に送った。(4) 再依頼の文面は `prompts/<版>/retry.md`（`{error}`）。(5) 状態の語彙は `fields.ReviewStatus`（`ok`・`no_documents`・`llm_failed`・`bad_json`）。(6) 応答の `unknown` キーと答えの値 `unknown` は同じ語で `fields.UNKNOWN`（既存の `CLASS_UNKNOWN` はこれを指す）。(7) `review.tasks` の下はタスク名で動的に読むため、アーキテクチャテストの `DYNAMIC_PARENTS` に加えた。(8) `RecordStore.reviews(run_id)`（評価の採点が読む）と `LLMClient.primary_model`（最初のキーのあるプロバイダーのモデル。無ければ `MissingKeyError`）を足した。

- 2026-10-17：評価の正解を `hypothesis_map.md` と照合し、一次情報で確かめていない 3 件（燦ホールディングス・東プレ・セントラル硝子）を外した。ダイコク電機は「減益」の語ではなく T5 の提案（落選・監視）で採点する。評価の銘柄の文書は `review-eval` が `collect_documents` で集める（`EvalCase.name` を追加）

- 2026-10-17（ブランチ A の実装）：5.1 節の `collect_documents` の引数が 8 個で ruff の PLR0913（5 個まで）を超えるため、依存を `CollectClients`（edinet・search・web_http・二つのリミッター）にまとめ、`collect_documents(candidates, settings, clients, store, today)` にした。`CollectSettings.search` は `clients.search is None` と重複するので削除（`main.py` は `docs.search` を `CollectClients.from_config` 経由で読む）。`SECONDS_PER_MINUTE` は `llm.py` に置く。`latest_issue`・`git_sha` は `main.py` から `records.py`（`RunInfo` の隣）へ移した。`GeminiSearch.search` の「キー無し」検査は `from_config` の `require_key` に置き換えて削除。
- 2026-10-17（ブランチ C の実装）：(1) メモのファイル名の雛形 `memo.filename` を `ReviewSettings.memo_filename` に置いた（`ReviewDeps` は 5 個のまま）。(2) `ReviewSummary` に `memo_paths` は足さず、`cmd_review` が `memo.dir` を表示する。(3) `ReviewRow` に `sector_comparison` を足し、`review._process` が `compare` の結果を入れて記録し、成功（`ok`）した銘柄だけメモを書く（失敗した銘柄に書く内容が無いため）。(4) 出典は `Document.source_ref`（EDINET は docID:要素名、Web は URL）。
