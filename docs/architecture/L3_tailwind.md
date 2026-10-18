# L3 クラス設計：Tailwind Watch（地図・流れの調査・記録）

作成：2026-10-18（DeepSeek の下書きを DeepSeek と Claude がレビュー） ／ 状態：**設計（受け入れ待ち）** ／ 親：`L2_C9_tailwind.md`、`L2_C4_stage2_research.md` 3.1 節　関連：`L3_composition.md`（組み立て）、`L3_stage2_classes.md`（既存モジュールのクラス）

凡例：✅ 実装済み ／ 🆕 未実装

## 1. 方針

- **部品は自分の `from_config` で作る**。`config.yaml` を読むのは `from_config` と `main.py` だけで、処理の関数は設定を引数で受け取る（`src/` は設定を読まない）。
- **純粋な処理と外部とのやりとりを分ける**：順位付け・会社ごとの数値・メモの組み立ては引数だけで決まる関数にし、LLM・検索・HTTP・DB は依存（`MapDeps`・`FlowDeps`・`FlowStore`）から呼ぶ。
- **既存の部品を使い回す**：軸の抜き出しと地図の確かめは `research.run_task`（JSON の検証、1 回の再依頼、`verify.check_claims` による照合）をそのまま使い、照合を書き直さない。文書の取得とレート制限は `webfetch.py`・`throttle.py` を使う。プロンプトは `prompts/flow/` に置き、版は `research.prompt_version`。
- 関数の引数は 5 個以内（ruff PLR0913）。依存は `MapDeps`・`FlowDeps` にまとめ、日付で変わる外部の値は `outcomes.evaluate` と同じく関数（callable）で渡す。

## 2. モジュールと公開する名前

| モジュール | 公開する名前 | 責務 | 状態 |
|---|---|---|---|
| `company_map.py` | `MapSettings`、`MapDeps`、`CompanyHit`、`MapResult`、`search_terms`、`rank_companies`、`build_map` | 恩恵企業の地図：需要から検索語（LLM）、全銘柄の「事業の内容」とセグメント情報の部分一致での順位付け、上位 `top_k` 社の確かめ（LLM と照合） | ✅ |
| `flow.py` | `FlowSettings`、`Throttles`、`FlowDeps`、`FlowSummary`、`CompanyLine`、`MissingProfilesError`、`flow_memo`、`company_numbers`、`render_flow_memo` | `flow-memo`・`flow-decide` の流れ：根拠の文書、軸の抜き出し、地図、会社ごとの数値、調査メモ、判断の記録 | ✅ |
| `flow_store.py` | `FlowRow`、`AxisRow`、`CompanyRow`、`FlowStore` | `flow.db_file`（git 対象外）の記録：流れ、軸、地図、判断、答え合わせ | ✅ |

## 3. クラス・関数

判断と答え合わせ（`Decision`・`flow_decide`・`DecisionRow`・`OutcomeRow`・`record_decision`・`record_outcome`・`decisions`・`due_decisions`）は flow-decide のブランチで作り、そのとき 2 章の表に足す。

### 3.1 `company_map.py`

```python
MapSettings(max_terms, top_k, max_doc_chars)          # from_config(cfg): flow.map.max_terms, flow.map.top_k, flow.max_doc_chars
MapDeps(llm, prompts, store)                          # prompts: research.load_prompts の辞書、store: DocStore
CompanyHit(ticker, tier, exposure, evidence, verified_ratio)
MapResult(terms, ranked, hits)
def search_terms(demand, settings, deps) -> list[str]
def rank_companies(terms, profiles, limit) -> list[tuple[str, int]]
def build_map(demand, settings, deps) -> MapResult
```

- 定数：`TERMS = "terms"`、`CONFIRM_TASK = "confirm"`、`CONFIRM_FIELDS = ["sells", "tier", "exposure"]`、`TIERS = ("1次", "2次", "3次以上")`、`SOURCE = "edinet"`。
- プロンプト（`prompts/flow/`）：`system`・`user`・`retry`（`research.build_messages` が使う）、`confirm`・`axes`（タスク本文。ファイル名は `task.lower()` と一致させる）、`terms_system`・`terms`（検索語専用）。
- `search_terms`：**claims を使わない**。検索語は需要の説明から作り、引用で支えられないため、`system.md` の claims の規則（文書だけを根拠にする・応答は claims の JSON）に当てはまらない。そこで `build_messages` は使わず、`terms_system` をシステム文、`terms` に `demand` と `max_terms` を埋めたものをユーザー文にして `deps.llm.chat(messages, json_mode=True)` を呼ぶ。応答 `{"terms": [...]}` を 1〜`max_terms` 個の空でない文字列として検証し、合わなければ assistant の応答と `retry`（`{error}`）を足して 1 回だけ再依頼、それでも合わなければ `research.ReplyError`。
- `rank_companies`：**純粋**。`profiles`（ticker → 本文）を `verify.normalize` で正規化し、検索語ごとに部分一致するかを数える。一致した語の数が多い順、同数は ticker の順。上位 `limit` 件を `(ticker, 一致した語の数)` で返す（一致 0 の銘柄は返さない）。
- `build_map`：
  1. `search_terms(demand, settings, deps)`。
  2. `rank_companies(terms, deps.store.profiles(), settings.top_k)`。
  3. 上位を 1 社ずつ `research.run_task(deps.llm, deps.prompts, (CONFIRM_TASK, CONFIRM_FIELDS), docs, {"ticker": t, "demand": demand})` で確かめる。`docs` はその会社の `SOURCE` の文書だけを `max_doc_chars` で切った `doc_id` → 本文（JSON の検証・再依頼・照合は `run_task` が行う）。`LLMError`・`ReplyError` の会社は `hits` に載せず次へ進む。
  4. `answer["sells"] is True` の会社だけ `hits` に載せる（照合できなければ `fields.UNKNOWN` になるので載らない）。`tier` は `TIERS` のいずれかでなければ `fields.UNKNOWN`、`exposure` は文書の表記のまま（無ければ `fields.UNKNOWN`）。`verified_ratio` は `len(evidence) / TaskResult.claims`（claims が 0 なら 0.0）。
- 文書ストアに「事業の内容」が 1 社も無ければ `build_map` は呼ばない（`flow.py` が `MissingProfilesError` にして止める。メモも記録も作らない）。呼び出し数の上限は、検索語 1 回＋ `top_k` 回（どちらも再依頼を含めない）。

### 3.2 `flow.py`

```python
FlowSettings(memo_dir, prompts_dir, search_prompt, max_sources, max_doc_chars, max_bytes, axes, map, outcome_months, control_past_months)  # from_config(cfg, root)
Throttles(search, fetch)                               # RateLimiter 2 つ
FlowDeps(llm, prompts, search, store, flows, records, history, throttles)   # from_config(cfg, root, env, stack, settings)
FlowSummary(flow_id, memo_path, unknown_axes, companies, searches_left)
Decision(flow_id, ticker, action, reason, max_yen)
CompanyLine(ticker, name, tier, exposure, numbers, note)
class MissingProfilesError(RuntimeError)
def flow_memo(name, demand, urls, settings, deps) -> FlowSummary
def flow_decide(decision, deps) -> None
def company_numbers(ticker, row, peers, momentum) -> dict[str, Any]
def render_flow_memo(name, demand, axes, companies) -> str
```

- 定数：`AXES_TASK = "axes"`、`ACTIONS = ("buy", "skip")`、`OWNER = "flow:{flow_id}"`（流れの文書を入れる `documents.ticker` の値）。
- `FlowSettings.from_config(cfg, root)`：`flow:` のキーを読み、`memo_dir`・`prompts_dir` を `root` で解決する。`max_bytes` は `webfetch.max_bytes`。`axes` は `flow.axes`（軸の項目名を実行の順に並べたもの。`run_task` に `(AXES_TASK, axes)` として渡す）、`map` は `MapSettings.from_config(cfg)`。
- `FlowDeps.from_config(cfg, root, env, stack, settings)`：`httpx.Client`・`LLMClient`・`GeminiSearch` を `stack` で開き（`CollectClients.from_config` と同じ作り方）、`prompts = load_prompts(root / settings.prompts_dir)`、`FlowStore`・`DocStore`・`RecordStore` をつなぐ。`history` は `outcomes.evaluate` に渡すものと同じ（調整済みの日次終値、naive な日付）。`throttles` は `llm.max_calls_per_minute` と `webfetch.request_interval_s`。キーが無ければ `MissingKeyError` で早く失敗する。
- `flow_memo(name, demand, urls, settings, deps)`：
  1. `flow_id = deps.flows.save_flow(FlowRow(name, demand, urls, prompt_version(deps.prompts), deps.llm.primary.model))`。以降の文書の `owner` は `OWNER` の値。
  2. 根拠の文書：`deps.search.search(settings.search_prompt.format(name=name, demand=demand))` の出典の先頭 `max_sources` 件と `urls` を、`throttles` を掛けながら `webfetch.fetch_page(uri, http, store, max_bytes, owner)` で入れる（`collect.py` の Web の取得と同じ仕組み）。`QuotaExceeded` は検索を止め、`searches_left` に残す。
  3. 軸の抜き出し：`run_task(deps.llm, deps.prompts, (AXES_TASK, settings.axes), docs, {"name": name, "demand": demand})`。`docs` は `store.documents(owner)` を `max_doc_chars` で切ったもの。照合できない主張だけが支える項目は `fields.UNKNOWN`。`LLMError`・`ReplyError` は流れ全体の失敗（記録したうえで送出）。
  4. 地図：`deps.store.profiles()` が空なら `MissingProfilesError`。あれば `build_map(demand, settings.map, MapDeps(deps.llm, deps.prompts, deps.store))`。
  5. 会社ごとの数値：`run_id = deps.records.resolve_run(None)`、`tickers = list(deps.records.run_metrics(run_id))`、`peers = Peers.from_run(deps.records, run_id, sectors, cfg)`、`momentum = sector.momentum(universe, ticker, momentum_settings, today)`（`universe = sector.Universe(deps.history, tickers, sectors)`）、`row = deps.records.screen_row(run_id, ticker)` → `company_numbers` と `CompanyLine`（`sectors` と名前は `read_column(input_csv, …)`）。
  6. `record_axes` → `record_companies` のあと、`render_flow_memo` の結果を `memo_dir / f"{name}-{today}.md"` に書いて `FlowSummary` を返す。
- `flow_decide(decision, deps)`：`deps.flows.record_decision(DecisionRow(...))`。`decided_at` は実行の時刻を分単位に丸める。`ValueError`（`Decision` の検証）はそのまま送出し、`main.py` が終了コード 1。
- `Decision`：`action` が `ACTIONS` に無ければ `ValueError`。`max_yen` は `None` か 0 以上の整数で、`None`（上限なし）と 0（1 円も買わない）を区別する。負の値は `ValueError`。
- `company_numbers(ticker, row, peers, momentum)`：**純粋**。`sector.compare` の値・業種の中央値・比に、`row`（`RecordStore.screen_row` の 1 行）の通過・落ちた条件・改善区分と `momentum["position"]`（地図の中の位置）を並べる。記録に無い項目は null。
- `render_flow_memo(name, demand, axes, companies)`：**純粋**。5 つの軸と終わりの手がかり（引用つき、無ければ「不明」）、地図（何次か・売上に占める割合・引用）、会社ごとの数値の表を Markdown にする。注記の 1 行（先に上がった会社はその後負けやすい）は `CompanyLine.note` が真のときだけ出す。判定は `sector.momentum_note`（3.4 節）が行い、`render_flow_memo` は印を出すだけ。

### 3.3 `flow_store.py`

```python
FlowRow(name, demand, urls, prompt_version, llm_provider)
AxisRow(axis, answer, evidence, verified_ratio)
CompanyRow(ticker, tier, exposure, evidence, run_id, stage1_pass, fail_rule, valuations, past3m_rank)
DecisionRow(flow_id, ticker, decided_at, action, reason, max_yen)
OutcomeRow(flow_id, ticker, decided_at, months, excess, control_excess, control_n)
FlowStore  # from_config(cfg, root): flow.db_file；context manager
```

- 表と主キーは `L2_C9_tailwind.md` 4 章のとおり（`flows`・`flow_axes`・`flow_companies`・`flow_decisions`・`flow_outcomes`）。DuckDB の 1 ファイル。
- 書き込み：`save_flow(row) -> str`（`flow_id` を決めて返す）、`record_axes(flow_id, rows)`、`record_companies(flow_id, rows)`、`record_decision(row)`、`record_outcome(row)`。
- 読み出し：`axes(flow_id) -> list[AxisRow]`、`companies(flow_id) -> list[CompanyRow]`、`decisions(flow_id) -> list[DecisionRow]`、`due_decisions(months, today) -> list[DecisionRow]`（答え合わせの対象：`decided_at` から `months` を過ぎ、その (flow_id, ticker, decided_at, months) の `flow_outcomes` がまだ無い判断。`months` は繰り返す）。
- 主キーが同じ 2 回目は増やさない（上書き）。`flow_decisions` の主キーは (flow_id, ticker, decided_at) なので、決め直すと行が増える。JSON の列（`urls`・`answer`・`evidence`・`valuations`）は文字列で往復する。

### 3.4 既存モジュールへの追加（文章）

- `sector.py`：`Universe(history, tickers, sectors)`（実行ごとに 1 回作る母集団）、`MomentumSettings(months, note_top_share, note_position)`（`from_config(cfg)`：`sector.momentum_*`）、`momentum(universe, target, settings, today) -> dict[str, Any]`（L2 C4 3.1 節の 6 引数を 4 引数にまとめた。PLR0913）。業種の超過リターン・全業種の中の順位・業種の中の位置を返し、計算できない値は null。注記の条件も `momentum_note(momentum, settings) -> bool` としてここに置く。
- `review.py`：`_process` が `compare` の結果に `momentum` キーを足して `sector_comparison` にする（`{"sector": …, "metrics": …, "momentum": …}`）。二次候補と順位は変えない。
- `memo.py`：`render_memo` が `sector_comparison` の `momentum` を 1 行にし、`momentum_note` が真なら注記の 1 行を足す。
- `docstore.py`：`profiles() -> dict[str, str]`（`source` が `edinet` の文書を ticker ごとにつないだもの。`docs` が入れた同じ節も混ざるが、同じ報告書なので害は無い）。
- `webfetch.py`：取得と本文の抽出を `download(url, http, max_bytes)` に切り出し、`fetch_document`（会社名を照合してから保存。挙動は変えない）と新しい `fetch_page(url, http, store, max_bytes, owner) -> str | None`（照合せずに保存。流れの出典は会社に結び付かない。`Document.ticker` に `owner`、失敗は `record_error(owner, "web", url, …)`）がそれぞれ保存する。`fetch_document` を `fetch_page` の包みにはしない（照合の前に保存されてしまうため）。
- `records.py`：`screen_row(run_id, ticker) -> dict[str, Any]`（`screen_results` の 1 行。`stage1_pass`・`stage1_fail_rule` と、`metrics` の JSON を展開した項目）。`run_metrics` は指標の JSON しか返さないため、通過と落ちた条件はここから引く。
- `collect.py`：`profiles` の流れ。全銘柄に既存の `fetch_annual_report(client, store, ticker, doc_type_code, sections)` を回し（`docs` と同じ節）、取得済みは飛ばす。失敗は記録して次の銘柄へ（全体は止めない）。
- `outcomes.py`：`evaluate` は引数が 5 個で埋まっているので変えない。判断の答え合わせは別の `evaluate_decisions(flows, history, controls, months, today) -> int` にし、`controls(sector, date) -> list[str]`（同じ 33 業種で、直近 3 か月の上昇と PBR が業種の中央値以下の会社）を `evaluate_recorded` が実行の記録と `sector.py` から作って渡す（`history` を callable で渡すのと同じ形。日付で変わるので判断の月ごとに呼ぶ）。`evaluate_recorded` は `FlowStore.from_config` を開き、返す行数に足す。
- `main.py`：`COMMANDS` に `profiles`・`flow-memo`・`flow-decide` を足す（CLI と組み立てだけ）。`flow-memo` は `--name`・`--demand`・`--url`（複数可）、`flow-decide` は `--flow`・`--ticker`・`--action`・`--reason`・`--max-yen`。`except` に `MissingProfilesError`・`ValueError` を足し、案内と終了コード 1。
- PER（ユーザー決定 2026-10-18）：業種で統一した PER の足切りは難しいため、Value Turn の足切りには使わない。流れの調査メモでは、キャッシュの `info.trailingPE` を会社ごとの数値に並べ、`flow.per_max`（初期値 100）以上の会社だけを「超割高」として一覧から外し、理由つきで別の欄に載せる。PER が無い（赤字など）会社は外さない
- `config.yaml`：`flow:`（`db_file`、`memo_dir`、`prompts_dir`、`search_prompt`、`max_sources`、`max_doc_chars`、`axes`、`map.max_terms`、`map.top_k`、`outcome_months`、`control.past_months`、`per_max`）と `sector.momentum_months`・`sector.momentum_note_top_share`・`sector.momentum_note_position`。

## 4. 単体テスト計画

| ID | 対象 | 確かめること |
|---|---|---|
| U-company_map-1 | `rank_companies` | NFKC の正規化（全角・半角）、部分一致、一致した語の数での順位、同数は ticker の順、`limit` で切る、一致 0 の銘柄は返さない |
| U-company_map-2 | `search_terms` | `terms` が 1〜`max_terms` 個の空でない文字列であることの検証、スキーマに合わない応答は 1 回だけ再依頼、再依頼で成功すれば通る、それでも合わなければ `ReplyError`、`terms_system` と `terms` で組み立てる（`system` は使わない） |
| U-company_map-3 | `build_map` | `sells` を照合できない会社は載らない、`sells` が偽の会社は載らない、`tier` の語彙（1次・2次・3次以上・不明）、各社の確かめはその会社の `edinet` の文書だけ、呼び出しは 1 ＋ `top_k` 回以内、`LLMError` の会社は飛ばして続ける |
| U-company_map-4 | `MapSettings` | 設定から作る（`from_config`）。`flow.map` と `flow.max_doc_chars` のキーを読む |
| U-flow-1 | `render_flow_memo` | 軸が引用つきで並ぶ、軸が「不明」のときの表記、会社ごとの数値の表、注記の 1 行は `note` が真のときだけ |
| U-flow-2 | `company_numbers` | 通過・落ちた条件・改善区分・`sector.compare` の値と中央値・`position`・PER をそのまま入れる、記録に無い項目は null。PER が `per_max` 以上なら超割高の印、PER が無ければ印なし |
| U-flow-3 | `Decision` | `action` は buy・skip だけ、それ以外は `ValueError`。`max_yen` は `None` と 0 を区別し、負の値は `ValueError` |
| U-flow-4 | `FlowSettings` | 設定から作る（`from_config`）。`flow:` のキーを読み、`memo_dir`・`prompts_dir` を `root` で解決し、`max_bytes` は `webfetch.max_bytes` |
| U-flow-5 | `flow_decide` | 判断を 1 行記録する（見送るも記録する）、`decided_at` は分単位に丸める。同じ流れ・銘柄を別の日に決め直すと行が増える |
| U-flow_store-1 | `FlowStore` | 流れ・軸・地図を 2 回入れて増えない、判断は (flow_id, ticker, decided_at) で別の行、書いたものを読み出せる |
| U-flow_store-2 | `FlowRow`・`AxisRow`・`CompanyRow`・`DecisionRow`・`OutcomeRow` | 列の順と型、JSON の列（urls・answer・evidence・valuations）の往復 |
| U-flow_store-3 | `due_decisions` | horizon を過ぎた判断だけ返す、その horizon の答え合わせが済んだ判断は返さない、繰り返しの `months` で horizon ごとに返す |

既存モジュール（`sector.momentum`・`sector.momentum_note`、`review.py` の `sector_comparison`、`memo.py` の注記、`docstore.profiles`、`webfetch.fetch_page` と `fetch_document` の挙動不変、`records.screen_row`、`collect.py` の `profiles`、`outcomes.evaluate_decisions`）の確かめは結合テスト I-C4-6・I-C9-* と E2E（E9〜E12）に任せる。

## 5. 訂正履歴

（なし）
