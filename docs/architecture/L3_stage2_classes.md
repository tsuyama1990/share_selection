# L3 クラス設計：二次調査（C2 文書の取得、C4 二次調査、C5 `reviews`、C6 調査メモ）

作成：2026-10-14 ／ 状態：**承認（2026-10-15）**　親：`L2_C2_data_acquisition.md`、`L2_C4_stage2_research.md`　対応テスト：単体テスト（4 章）

凡例：✅ 実装済み ／ 🆕 未実装。根拠：[データ：日付]＝実測、[推論]＝未検証の判断。

## 1. 方針

- 外部とやりとりする部分（HTTP、DB、ファイル）と、純粋な処理（解析・抽出・照合・集計・整形）を分ける。純粋な処理は単体テスト、つなぎは L2 の結合テストで確かめる。
- 組み立ては既存と同じく `main.py`（`run_review`）が行う。設定値は引数で渡し、`src/` は設定を読まない（`tests/unit/test_architecture.py`）。
- 抽象化は 2 つ目の実例が出るまで作らない。HTTP の間隔の制御は `llm.RateLimiter`（`max_calls=1`、`window_s=間隔`）を使い回す（2 つ目の利用者になるので、ここで初めて共有する）。
- 新しい依存は `pypdf`（PDF の本文抽出）の 1 つだけ。HTML は標準ライブラリの `html.parser` で抜く（L2 C2 §8 の先送りをここで決定）。

## 2. モジュールと公開する名前

モジュールが存在するとき、公開する名前（先頭が `_` でないモジュール直下のクラス・関数）はこの表と一致しなければならない（設計の関門）。

| モジュール | 公開する名前 | 責務 | 状態 |
|---|---|---|---|
| `docstore.py` | `Document`、`DocStore`、`DocumentRewriteError` | 文書・EDINET の索引・取得の失敗の保存と検索。同じ doc_id への別の本文の保存を拒む | 🆕 |
| `edinet.py` | `EdinetClient`、`parse_index`、`extract_sections`、`sec_code`、`update_index`、`fetch_annual_report` | EDINET API v2 の呼び出し、書類一覧の解析、ZIP の本文 CSV からの節の抽出、索引の差分更新、最新の有価証券報告書の保存 | 🆕 |
| `webfetch.py` | `extract_text`、`web_doc_id`、`fetch_document` | URL の取得（リダイレクト追従・サイズ上限）、HTML・PDF の本文抽出、保存 | 🆕 |
| `verify.py` | `normalize`、`check_claims` | 引用の照合と照合率、支えのない項目の unknown への置き換え | 🆕 |
| `sector.py` | `sector_medians`、`compare` | 業種ごとの中央値と、候補の同業比較 | 🆕 |
| `research.py` | `ReplyError`、`TaskResult`、`load_prompts`、`build_messages`、`parse_reply`、`run_task`、`review_ticker` | T1〜T5 の実行（プロンプトの組み立て、JSON の検証と 1 回の再依頼、照合）と 1 銘柄分の結果の行 | 🆕 |
| `memo.py` | `render_memo` | 1 銘柄の調査メモ（Markdown の文字列） | 🆕 |

`records.py`（✅）には `reviews` テーブル、`candidates(run_id)`、`run_metrics(run_id)`、`reviewed(run_id)`、`record_review(run_id, row)` を足す。`main.py`（✅）には `review [--run RUN_ID]` と `run_review` を足す。

## 3. クラス・関数

### 3.1 `docstore.py`

```python
@dataclass(frozen=True)
class Document:
    doc_id: str; ticker: str; source: str  # "edinet" | "web"
    source_ref: str; title: str; fetched_at: datetime; text: str

class DocumentRewriteError(RuntimeError): ...

class DocStore:                        # with 文で使う（RecordStore と同じ形）
    def __init__(self, db_path: Path)
    def put(self, doc: Document) -> None          # 同じ doc_id・同じ本文は何もしない、別の本文は DocumentRewriteError
    def has(self, doc_id: str) -> bool
    def documents(self, ticker: str) -> list[Document]
    def record_error(self, ticker: str, source: str, ref: str, error: str) -> None
    def add_index(self, rows: list[dict]) -> None  # edinet_index。同じ doc_id は無視
    def index_last_date(self) -> date | None
    def latest_annual_report(self, sec_code: str, doc_type_code: str) -> str | None  # docID
```

text_sha256 は `put` が計算して保存する（`Document` には持たせない）。

### 3.2 `edinet.py`

```python
class EdinetClient:
    def __init__(self, base_url: str, api_key: str, http: httpx.Client, limiter: RateLimiter)
    def list_documents(self, day: date) -> dict      # documents.json?date=&type=2
    def download_csv_zip(self, doc_id: str) -> bytes  # documents/{docID}?type=5

def sec_code(ticker: str) -> str                       # "6599.T" → "65990"、"130A.T" → "130A0"
def parse_index(listing: dict, submit_date: date) -> list[dict]   # docID・secCode・edinetCode・docTypeCode・periodEnd
def extract_sections(zip_bytes: bytes, elements: list[str]) -> dict[str, str]  # 要素名 → タグを除いた本文
def update_index(client, store, today: date, index_days: int) -> int            # 走査した日数
def fetch_annual_report(client, store, ticker: str, doc_type_code: str, elements: list[str]) -> list[str]  # doc_id
```

- `update_index`：`store.index_last_date()` の翌日（無ければ `today - index_days`）から `today` まで 1 日ずつ。
- `fetch_annual_report`：索引から最新の docID。既に `edinet:{docID}:*` があれば取り直さない。失敗（HTTP、ZIP 不正、節が無い）は `record_error` して空のリストを返す。
- 英字を含む証券コード（`130A` など、銘柄一覧に 181 件 [データ：2026-10-14 `japan_tickers.csv`]）の secCode が「コード＋0」かは未確認 [推論]。実装の後、ライブで 1 件確かめる。

### 3.3 `webfetch.py`

```python
def web_doc_id(final_url: str) -> str                 # "web:" + 正規化した URL の sha256 の先頭 16 桁
def extract_text(body: bytes, content_type: str) -> tuple[str, str]   # (title, text)。HTML は script・style・nav・header・footer を除く。PDF は pypdf
def fetch_document(url: str, ticker: str, http: httpx.Client, store: DocStore,
                   max_bytes: int, limiter: RateLimiter) -> str | None  # doc_id。失敗は record_error して None
```

正規化：スキームとホストを小文字、フラグメントを除く。上限を超える応答は読み切らずに失敗とする。

### 3.4 `verify.py`

```python
def normalize(text: str) -> str      # NFKC、空白・改行の除去
def check_claims(answer: dict, claims: list[dict], docs: dict[str, str]) -> tuple[dict, list[dict], float]
    # → (支えのない項目を "unknown" にした answer, 照合できた claims, 照合率)
```

- 照合できる claim：`doc_id` が `docs` にあり、正規化した `quote` が正規化した本文の部分文字列。空の quote は不一致。
- 照合率 = 照合できた数 ÷ claims の数（claims が 0 件なら 0.0）。
- `answer` の項目は、照合できた claim のどれかの `field` がその項目名のときだけ残す（下の 5 章の変更 1）。

### 3.5 `sector.py`

```python
def sector_medians(rows: list[dict], sectors: dict[str, str], metrics: list[str], min_peers: int) -> dict[str, dict[str, float | None]]
    # rows：実行の全銘柄の metrics（"Ticker" を含む）。sectors：ticker → 33 業種。値のある銘柄が min_peers 未満の指標は None
def compare(row: dict, sector: str, medians: dict[str, dict[str, float | None]], metrics: list[str]) -> dict
    # {"sector": ..., "metrics": {指標: {"value": ..., "median": ..., "ratio": value/median}}}
```

### 3.6 `research.py`

```python
class ReplyError(ValueError): ...

@dataclass(frozen=True)
class TaskResult:
    task: str; answer: dict; evidence: list[dict]; unknown: list[str]
    verified_ratio: float; providers: list[str]

def load_prompts(prompt_dir: Path) -> dict[str, str]         # system と t1〜t5（prompts/<版>/*.md）
def build_messages(system: str, task_prompt: str, docs: dict[str, str], context: dict) -> list[dict[str, str]]
def parse_reply(text: str, fields: list[str]) -> dict         # JSON・answer の項目・claims の形を検証。合わなければ ReplyError
def run_task(llm: LLMClient, task: str, prompts: dict[str, str], fields: list[str],
             docs: dict[str, str], context: dict) -> TaskResult   # 1 回だけ再依頼。それでも ReplyError なら送出
def review_ticker(llm, prompts, task_fields: dict[str, list[str]], docs: dict[str, str],
                  context: dict, min_verified_ratio: float) -> dict   # reviews の 1 行（status 以外の列）
```

- `review_ticker`：T1〜T4 を実行し、T5 の `context` にそれまでの照合済みの `answer` を足して T5 を実行する。全体の照合率は全タスクの claims を合わせて計算し、下限未満なら `needs_attention = True`。
- 各タスクの項目名（`task_fields`）は config の `review.tasks` に置く（L2 C4 §4 の表と同じ項目）。
- 文書が長すぎないよう、`main.run_review` が 1 文書を `review.max_doc_chars` 文字で切ってから渡す。照合も切った後の本文に対して行う（LLM に見せた本文と照合の対象を一致させる）。

### 3.7 `memo.py`

```python
def render_memo(ticker: str, name: str, review: dict, sector_comparison: dict, sources: dict[str, str]) -> str
    # sources：doc_id → 出典（URL か EDINET の docID）。照合率が下限未満なら冒頭に「要注意」
```

### 3.8 `records.py` と `main.py` の追加

- `reviews`：主キー（run_id, ticker）。列は L2 C4 §6 から `human_decision`・`decided_at` を除き（5 章の変更 2）、`needs_attention`、`reviewed_at` を足す。書くたびに Parquet を git 対象外の `review.export_dir` に書き出す（公開リポジトリに引用と提案を載せない。`.gitignore` への追加は `feat/review-command` で設定と一緒に行う）。調査メモは `results/` の下（既に git 対象外）。
- `candidates(run_id)`：`Stage2_Candidate` が真の銘柄の (ticker, metrics)。`run_metrics(run_id)`：全銘柄の metrics（業種の中央値の母集団）。`reviewed(run_id)`：status が `ok` の ticker（再実行のとき飛ばす。失敗した銘柄は取り直して上書き）。
- `main.run_review`：実行の選択（既定は最新）→ 業種の中央値 → EDINET の索引の更新 → 候補ごとに（有価証券報告書の取得、検索 → 出典の取得、文書の読み出し、`review_ticker`、`record_review`、`render_memo` の書き出し）。検索の回答文そのものは LLM の生成なので根拠の文書にしない（出典の本文だけを使う）。

## 4. 単体テスト計画

外部（HTTP、DB、ファイル）を使わない。ZIP・PDF はテストの中でバイト列として作るか、`tests/fixtures/` の小さなファイルを読む。

| ID | 対象 | 確かめること |
|---|---|---|
| U-docstore-1 | `Document` | 不変（frozen） |
| U-edinet-1 | `sec_code` | 数字のコード、英字を含むコード、`.T` の除去 |
| U-edinet-2 | `parse_index` | 必要な列だけ、secCode の無い書類を除く |
| U-edinet-3 | `extract_sections` | UTF-16 タブ区切りの本文 CSV から指定の要素だけ、タグの除去、要素が無いときは空の辞書 |
| U-webfetch-1 | `web_doc_id` | 正規化（大文字・フラグメント）で同じ ID |
| U-webfetch-2 | `extract_text` | HTML のタイトルと本文（script・nav を除く）、PDF の本文 |
| U-verify-1 | `normalize` | 全角・半角、空白・改行 |
| U-verify-2 | `check_claims` | 一致・不一致・doc_id 違い・空の quote、照合率、項目の unknown への置き換え |
| U-sector-1 | `sector_medians` | 中央値、同業が少ない指標は None、値の無い銘柄を除く |
| U-sector-2 | `compare` | 比、中央値が None か 0 のとき |
| U-research-1 | `build_messages` | 文書が doc_id 付きで入る、指示と指標 |
| U-research-2 | `parse_reply` | 正しい JSON、JSON でない、項目の欠け、claims の形の誤り |
| U-research-3 | `run_task`（偽の LLM） | 1 回目の不正 → 再依頼で成功、2 回とも不正で ReplyError、照合の反映 |
| U-memo-1 | `render_memo` | 見出し・根拠と出典・unknown・要注意の表示 |

`DocStore`、`EdinetClient`、`update_index`、`fetch_annual_report`、`fetch_document`、`review_ticker`、`records` の追加は、L2 の結合テスト（I-C2-3〜5、I-C4-2〜4）と E2E の E6 で確かめる。

## 5. L2 の変更（L3 で分かったこと。2026-10-15 承認、L2 に反映済み）

1. **claims に `field` を足す**（L2 C4 §4）：`{"field": "answer の項目名", "claim", "quote", "doc_id"}`。L2 C4 §5 の「answer の項目が残った主張で支えられない場合は unknown」を機械で判定するには、主張がどの項目を支えるかが要る。
2. **`human_decision`・`decided_at` を `reviews` から外す**（L2 C4 §6）：人の判断を入れるコマンドが設計に無く、列だけ作っても使われない。人の判断を記録する方法は、調査メモを使い始めてから決める（先送り）。
3. **`review` の「1 回の実行の呼び出し上限」を外す**（L2 C4 §7）：呼び出しは「対象の上限件数 × タスク 5 件 × 最大 2 回 ＋ 検索」で上限が決まるため、別の上限は要らない [推論]。代わりに 1 文書の文字数の上限 `review.max_doc_chars` を足す（Groq の `openai/gpt-oss-120b` などフォールバック先の文脈の長さに収めるため）。

## 6. 設定（`config.yaml` に足す節）

| 節 | キー |
|---|---|
| `edinet` | base_url、key_env、index_days、doc_type_code（`"120"`）、sections、request_interval_s |
| `webfetch` | timeout_s、max_bytes、user_agent、request_interval_s、max_sources（1 銘柄で取る出典の数） |
| `docstore` | db_file |
| `sector` | metrics（`Real_PSR`、`PBR`、`Improvement_Yield(%)`）、min_peers |
| `review` | max_tickers、min_verified_ratio、search、search_prompt、prompt_dir（`prompts/v1`）、prompt_version、max_doc_chars、tasks（タスクごとの項目名）、export_dir |
| `memo` | dir（`results/` の下）、filename |

## 7. 実装の順番（1 ブランチ＝1 まとまり。各ブランチで単体テスト → 実装 → 結合テストの仮置きを本物に → bonsai）

| 順 | ブランチ | 中身 | 結合・E2E |
|---|---|---|---|
| 1 | `feat/docstore` | `docstore.py` | I-C2-5 |
| 2 | `feat/edinet` | `edinet.py`、`RateLimiter` の共有 | I-C2-3、ライブで 1 社 |
| 3 | `feat/webfetch` | `webfetch.py`、`pypdf` | I-C2-4 |
| 4 | `feat/verify-sector` | `verify.py`、`sector.py` | I-C4-2 |
| 5 | `feat/research` | `research.py`、`prompts/v1/` | I-C4-3 |
| 6 | `feat/review-command` | `records.py` の `reviews`、`memo.py`、`main.py review` | I-C4-4、E6、ライブで 2〜3 社 |

コード予算の増え方の見込みは合計で約 450 行（docstore 60、edinet 80、webfetch 55、verify 30、sector 30、research 90、memo 35、records 30、main 40）[推論]。各ブランチで `Budget-Increase:` に理由を書き、実際の行数に合わせる。

## 8. 訂正履歴

（なし）
