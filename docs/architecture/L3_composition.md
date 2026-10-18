# L3 クラス設計：組み立てと処理の流れ、二次調査の実行と品質の関門

作成：2026-10-17 ／ 状態：**承認・実装済み**　親：`L1_architecture.md` 3 章（C2〜C7）、`L2_C2_data_acquisition.md`、`L2_C4_stage2_research.md`　関連：`L3_stage2_classes.md`（各モジュールのクラス）

凡例：✅ 実装済み ／ 🆕 未実装

## 1. 方針

- **`main.py` は CLI と組み立てだけ**（引数、設定と `.env`、部品の生成、呼び出し、要約の表示）。コマンドは `COMMANDS`（名前 → 関数）。処理の流れは `src/` に置き、結合テストで確かめる。
- **部品は自分の `from_config` で作る**。API キーの確認は `config.require_key(env, name)` だけで、無ければ `MissingKeyError`（`main.py` が終了コード 1）。
- **受け渡しは型で**：一次の結果は `ScreenResult`（行は `fields.py` の項目名）、実行情報は `records.RunInfo`。
- 調整値は `config.yaml`。プロンプトと評価の正解はファイルにして、場所を `config.yaml` に置く。

## 2. モジュールと公開する名前

設計の関門が公開名を照合する。他のモジュールは `L3_stage2_classes.md`。

| モジュール | 公開する名前 | 責務 | 状態 |
|---|---|---|---|
| `collect.py` | `CollectClients`、`CollectSettings`、`CollectSummary`、`collect_documents`、`companies` | `docs` の流れ：EDINET の索引の更新と有価証券報告書、Web 文書がまだ無い候補だけを優先順に検索し出典を取得、検索の割り当てで停止 | ✅ |
| `review.py` | `ReviewDeps`、`ReviewSettings`、`ReviewSummary`、`review_candidates` | `review` の流れ：候補ごとに文書の読み出し → T1〜T5（`research.py`）→ 照合（`verify.py`）→ 業種の比較（`sector.py`）→ 記録 → 調査メモ（`memo.py`）。銘柄の失敗は状態として記録して次へ | ✅ |
| `review_eval.py` | `EvalCase`、`EvalResult`、`EvalThresholds`、`EvalGate`、`load_eval_cases`、`score_case`、`judge`、`combine`、`evaluate_model` | モデルの品質の関門：正解のある銘柄の調査結果の採点と合否 | ✅ |

## 3. クラス・関数

### 3.1 `collect.py`

```python
CollectSettings(index_days, doc_type_code, sections, search_prompt, max_sources, max_bytes)   # from_config(cfg)
CollectSummary(edinet_docs, edinet_failed, web_docs, searches_left)
CollectClients(edinet, search: GeminiSearch | None, web_http, search_limiter, fetch_limiter)  # from_config(cfg, env, stack, search)
def companies(candidates, names) -> list[Company]
def collect_documents(companies, settings, clients, store, today) -> CollectSummary
```

会社は優先順に渡す。名前は日本語（`japan_tickers.csv`、無ければ指標の `Name`）で、検索の指示と Web 文書の会社名の照合に使う。Web 文書がまだ無い会社だけを検索し、`QuotaExceeded` で止めて残りの数を返す。

### 3.2 `review.py`

```python
ReviewSettings(max_tickers, min_verified_ratio, max_doc_chars, prompt_version, task_fields, context_metrics, memo_filename)  # from_config(cfg)
ReviewSummary(reviewed, failed, needs_attention)
ReviewDeps(llm, prompts, reviews: ReviewStore, store: DocStore, peers: Peers | None, memo_dir: Path | None)  # from_config(cfg, root, env, stack, peers)
def review_candidates(run_id, candidates, tickers, settings, deps) -> ReviewSummary
```

- 対象：`tickers` があればそれ、無ければ `candidates` のうち未調査のものを `Priority_Rank` の順に `max_tickers` 件。
- 1 銘柄：文書を `max_doc_chars` で切る → T1〜T4 → T5（T1〜T4 の照合済みの答えを文脈に）→ 記録 → 成功した銘柄だけ調査メモ。照合率は銘柄の全 claims に対する割合。`needs_attention` は照合率が `min_verified_ratio` 未満。評価（`review-eval`）は `peers` と `memo_dir` が None（同業比較もメモも無し）。
- **品質の関門**：プロンプトの版（内容のハッシュ）と最初のモデルに合格の記録が無ければ、評価以外の実行を拒む（終了コード 1）。

### 3.3 `review_eval.py`（モデルの品質の関門）

```python
EvalCase(ticker, name, task, field, expect_any: list[str], basis)   # expect_any：答えか根拠の引用にどれか 1 つが含まれれば一致
EvalResult(cases, hits, parse_failures, min_verified_ratio, fallback_rows, passed)
def load_eval_cases(path) -> list[EvalCase]
def score_case(case, review_row) -> bool
def judge(results, review_rows, thresholds: EvalThresholds, primary) -> EvalResult
def combine(results: list[EvalResult]) -> EvalResult           # すべての回が合格のときだけ合格
def evaluate_model(cases, cfg, deps, run_id) -> list[...]       # 回ごとの結果
```

`review-eval`：正解の銘柄（`review.eval.cases_file`、`eval/stage2_cases.yaml`。正解は `docs/hypothesis_map.md` と一次情報で確かめたものだけ）について、`review.eval.sources` の文書（EDINET だけ。毎回同じ文書でモデルを比べ、検索の割り当ても使わない）で調査を `review.eval.repeats` 回繰り返し、回ごとに `judge`、`combine` で合否を決めて `review_evals` に 1 行を記録する。不合格は終了コード 1。本物の API を使うので CI には入れず、モデルの順番やプロンプトを変えたら手で実行する。

合格の条件（値は `review.eval:`。各回で満たし、全回で合格）：正解の一致率 `min_hit_rate`（0.8）以上、再依頼の後の JSON の不正 `max_parse_failures`（0）以下、銘柄ごとの照合率の最小 `review.min_verified_ratio`（0.7）以上、主のモデル以外の回答 0 件。

## 4. 単体テスト計画

| ID | 対象 | 確かめること |
|---|---|---|
| U-review_eval-1 | `score_case` | expect_any の一致（answer・引用のどちらでも）、不一致、空の expect_any は項目が unknown でなければ合格 |
| U-review_eval-2 | `judge` | 一致率・JSON の不正・照合率の最小値の、それぞれ境界での合否 |
| U-review_eval-3 | `load_eval_cases` | YAML の読み込み、必須の項目の欠けで失敗 |
| U-review_eval-4 | `combine` | 全回合格で合格、1 回でも不合格なら不合格、合計と最小 |
| U-collect-1 | `CollectSettings` | 設定から作る（`from_config`） |
| U-review-1 | `ReviewSettings` | 設定から作る（`from_config`） |

結合と E2E：`collect_documents`（I-C2-3・I-C2-4 と停止）、`review_candidates`（I-C4-4）、`review-eval`（I-C4-5）、E6・E7。

## 訂正履歴

詳細は git の履歴にある。

- 2026-10-17：組み立ての見直し（`main.py` を CLI と組み立てだけに、`collect.py`・`review.py`・`review_eval.py`）と、第 2 回の見直し（`records.py`・`outcomes.py`・`review_store.py` に分割、`flows.py`）を実装。挙動は不変
- 2026-10-17：品質の関門を、ライブの試験（軽いモデルは合否が揺れた）から「k 回続けて合格」「文書は EDINET だけ」「照合率は銘柄の全 claims に対する割合」に直した。主のモデルを `deepseek-v4-flash` にした（ユーザー決定）
- 2026-10-17：評価の正解を一次情報で確かめたものだけにした（燦ホールディングス・東プレ・セントラル硝子を外し、カヤバ・三菱化工機を加えた。エブレンは「価格転嫁」）
- 2026-10-18：経緯の節（見直しの理由、既存モジュールの変更、実装の順番、ライブ試験の記録、第 2 回の見直しの表）を削り、今の設計だけにした
