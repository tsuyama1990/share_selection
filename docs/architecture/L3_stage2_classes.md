# L3 クラス設計：二次調査（C2 文書の取得、C4 二次調査、C5 `reviews`、C6 調査メモ）

作成：2026-10-14 ／ 状態：**承認・実装済み**　親：`L2_C2_data_acquisition.md`、`L2_C4_stage2_research.md`　対応テスト：単体テスト（4 章）

凡例：✅ 実装済み ／ 🆕 未実装。根拠：[データ：日付]＝実測、[推論]＝未検証の判断。

## 1. 方針

- 外部とやりとりする部分（HTTP、DB、ファイル）と、純粋な処理（解析・抽出・照合・集計・整形）を分ける。純粋な処理は単体テスト、つなぎは L2 の結合テストで確かめる。
- 組み立ては `main.py`（CLI と各部品の `from_config`）、処理の流れは `collect.py`・`review.py`（`L3_composition.md`）。設定値は引数で渡し、`src/` は設定を読まない（`tests/unit/test_architecture.py`）。
- 抽象化は 2 つ目の実例が出るまで作らない。HTTP の間隔の制御は `throttle.RateLimiter`（`max_calls=1`、`window_s=間隔`）を EDINET・Web・LLM で共有する（2026-10-16 に `llm.py` から移した）。
- 新しい依存は `pypdf`（PDF の本文抽出）の 1 つだけ。HTML は標準ライブラリの `html.parser` で抜く（L2 C2 §8 の先送りをここで決定）。

## 2. モジュールと公開する名前

モジュールが存在するとき、公開する名前（先頭が `_` でないモジュール直下のクラス・関数）はこの表と一致しなければならない（設計の関門）。

| モジュール | 公開する名前 | 責務 | 状態 |
|---|---|---|---|
| `docstore.py` | `Company`、`Document`、`DocStore`、`DocumentRewriteError` | 文書・EDINET の索引・取得の失敗の保存と検索。同じ doc_id への別の本文の保存を拒む | ✅ |
| `edinet.py` | `EdinetClient`、`parse_index`、`extract_sections`、`sec_code`、`update_index`、`fetch_annual_report` | EDINET API v2 の呼び出し、書類一覧の解析、ZIP の本文 CSV からの節の抽出、索引の差分更新、最新の有価証券報告書の保存 | ✅ |
| `webfetch.py` | `extract_text`、`web_doc_id`、`fetch_document`、`download`、`fetch_page` | URL の取得（リダイレクト追従・サイズ上限）、HTML・PDF の本文抽出、保存 | ✅ |
| `verify.py` | `normalize`、`check_claims` | 引用の照合と照合率、支えのない項目の unknown への置き換え | ✅ |
| `sector.py` | `Peers`、`PeerSettings`、`sector_medians`、`compare`、`Universe`、`MomentumSettings`、`momentum`、`momentum_note`、`laggard_peers` | 業種ごとの中央値と、候補の同業比較（`Peers.build` は指標の辞書から作り、記録の置き場には依存しない）。業種の勢い（`L2_C4_stage2_research.md` 3.1 節）。業種の中のまだ上がっていない割安株（Tailwind Watch の答え合わせの比べる相手） | ✅ |
| `research.py` | `ReplyError`、`TaskResult`、`load_prompts`、`prompt_version`、`build_messages`、`parse_reply`、`run_task` | T1〜T5 の実行（プロンプトの組み立て、JSON の検証と 1 回の再依頼、照合） | ✅ |
| `memo.py` | `render_memo`、`render_flow_memo`、`CompanyLine`、`axis_value` | 調査メモ（1 銘柄の二次調査、流れの調査）の Markdown の文字列 | ✅ |

候補と全銘柄の指標は `records.py`（`RecordStore.candidates`・`run_metrics`）、`reviews`・`review_evals` は `review_store.py`（`ReviewStore.record_review`・`reviewed`・`passed_eval`）。`docs`・`review` の流れは `collect.py`・`review.py`（`L3_composition.md`）。

## 3. クラス・関数

### 3.1 `docstore.py`

```python
@dataclass(frozen=True)
class Company:                         # 会社名の照合（L2 C2 2.2 節）
    ticker: str; name: str             # name は銘柄一覧の日本語名
    def mentioned_in(self, text: str) -> bool   # verify.normalize した text に、正規化した name か証券コード（ticker から tickers.TICKER_SUFFIX を除く）が含まれる

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
- `parse_index` は `edinet_index` の列名の辞書を返す。secCode のある書類はすべて索引に入れる（種類で絞らない）。
- `update_index` は失敗した日で走査を止め、失敗を記録する（次回は最後に索引に入った提出日の翌日から。抜けを作らない）。
- `fetch_annual_report`：索引から最新の docID。設定の節の**すべて**が保存済みのときだけ取り直さない。足りなければ取得して節を `put`（同じ本文は何もしない）。失敗（HTTP、ZIP 不正、設定の節が 1 つも無い）は `record_error` して空のリストを返す。
- 英字を含む証券コード（`130A` など、銘柄一覧に 181 件 [データ：2026-10-14 `japan_tickers.csv`]）の secCode も「コード＋0」（例 `250A0`）と確認した [データ：2026-10-15 EDINET 書類一覧 2026-06-25 提出分]。

### 3.3 `webfetch.py`

```python
def web_doc_id(final_url: str) -> str                 # "web:" + 正規化した URL の sha256 の先頭 16 桁
def extract_text(body: bytes, content_type: str) -> tuple[str, str]   # (title, text)。HTML は script・style・nav・header・footer を除く。PDF は pypdf
def fetch_document(url: str, company: Company, http: httpx.Client, store: DocStore,
                   max_bytes: int) -> str | None  # doc_id。失敗、または title + 本文が company.mentioned_in を満たさない（"not about the company"）ときは record_error して None（保存しない）。取得間隔は呼び出し側の RateLimiter が守る（引数 6 個は ruff PLR0913 に触れるため limiter を外した）
```

正規化：スキームとホストを小文字、フラグメントを除く。上限を超える応答は読み切らずに失敗とする。

### 3.4 `verify.py`

```python
def normalize(text: str) -> str      # NFKC、空白・改行の除去
def check_claims(answer: dict, claims: list[dict], docs: dict[str, str]) -> tuple[dict, list[dict]]
    # → (支えのない項目を "unknown" にした answer, 照合できた claims)
```

- 照合できる claim：`doc_id` が `docs` にあり、正規化した `quote` が正規化した本文の部分文字列。空の quote は不一致。
- 照合率は銘柄ごとに `review.py` が計算する：全タスクの照合できた数 ÷ 全タスクの claims の数（0 件なら 0.0）。「unknown」と正直に答えて claims の無いタスクは、照合率を下げない。
- `answer` の項目は、照合できた claim のどれかの `field` がその項目名のときだけ残す。

### 3.5 `sector.py`

```python
@dataclass(frozen=True)
class Peers:                      # 実行ごとに 1 回作る
    medians: dict[str, dict[str, float | None]]   # 業種 → 指標 → 中央値
    sectors: dict[str, str]                        # ticker → 33 業種
    metrics: list[str]

def sector_medians(metrics_by_ticker: dict[str, dict], sectors: dict[str, str], metrics: list[str], min_peers: int) -> dict[str, dict[str, float | None]]
    # 実行の全銘柄（足切りの前、L2 C4 §9）。値のある銘柄が min_peers 未満の指標は None
def compare(ticker: str, row: dict, peers: Peers) -> dict
    # {"sector": ..., "metrics": {指標: {"value": ..., "median": ..., "ratio": value/median}}}。中央値が None か 0 なら ratio は None
```

指標の名前は `sector.metrics`（`fields.py` の項目であることを architecture テストが確かめる）。業種は銘柄一覧の `sector33`（`tickers.read_column`）。

### 3.6 `research.py`

```python
class ReplyError(ValueError): ...

@dataclass(frozen=True)
class TaskResult:
    task: str; answer: dict; evidence: list[dict]; unknown: list[str]
    verified_ratio: float; providers: list[str]

def load_prompts(prompt_dir: Path) -> dict[str, str]         # system と t1〜t5（prompts/<版>/*.md）
def build_messages(prompts: dict[str, str], task: str, docs: dict[str, str], context: dict) -> list[dict[str, str]]   # system と prompts/user.md（文書を先、タスクを後）
def parse_reply(text: str, fields: list[str]) -> dict         # JSON・answer の項目・claims の形を検証。合わなければ ReplyError
def run_task(llm: LLMClient, prompts: dict[str, str], task_fields: tuple[str, list[str]],
             docs: dict[str, str], context: dict) -> TaskResult   # task_fields＝(タスク名, 項目名)。1 回だけ再依頼。それでも ReplyError なら送出
```

- `prompts` はファイル名の語幹をキーにした辞書（`system`、`t1`〜`t5`、再依頼の文面 `retry`。`{error}` を埋める）。文書は `<document id="doc_id">` で囲んで渡す。`TaskResult.providers` は `<プロバイダー>/<モデル>` の呼び出し順。
- T1〜T5 の順番、T5 への文脈の渡し方、全体の照合率と `needs_attention` は `review.py`（`L3_composition.md` 3.2 節）。
- 各タスクの項目名（`task_fields`）は config の `review.tasks` に置く（L2 C4 §4 の表と同じ項目）。
- 文書が長すぎないよう、`review.py` が 1 文書を `review.max_doc_chars` 文字で切ってから渡す。照合も切った後の本文に対して行う（LLM に見せた本文と照合の対象を一致させる）。

### 3.7 `memo.py`

```python
def render_memo(ticker: str, name: str, review: dict, comparison: dict | None, sources: dict[str, str]) -> str
    # review：reviews の 1 行（answers・evidence・verified_ratio・needs_attention・suggestion）
    # sources：doc_id → 出典（URL か EDINET の docID:要素名）。照合率が下限未満なら冒頭に「要注意」
```

Markdown：見出し（銘柄・名前・提案）→ 要注意 → タスクごとの答えと、照合できた引用（出典つき）→ unknown の一覧 → 同業比較の表。ファイルは `memo.dir`（`results/` の下、git 対象外）に `memo.filename`（`{run_id}_{ticker}.md`）。

### 3.8 記録（`review_store.py`）

- `reviews`：主キー（run_id, ticker）。列は L2 C4 §6。書くたびに Parquet を git 対象外の `review.export_dir` に書き出す（公開リポジトリに引用と提案を載せない）。調査メモは `results/` の下（git 対象外）。
- `reviewed(run_id)`：status が `ok` の ticker（再実行で飛ばす。失敗した銘柄は取り直して上書き）。検索の回答文そのものは LLM の生成なので保存しない（出典の本文だけ）。

## 4. 単体テスト計画

外部（HTTP、DB、ファイル）を使わない。ZIP・PDF はテストの中でバイト列として作るか、`tests/fixtures/` の小さなファイルを読む。

| ID | 対象 | 確かめること |
|---|---|---|
| U-docstore-1 | `Document` | 不変（frozen） |
| U-docstore-2 | `Company`、`mentioned_in` | 日本語名または証券コードを含むと真、含まないと偽。全角・半角・空白の違いを無視。英字を含むコード（`130A`） |
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
| U-research-4 | `prompt_version` | プロンプトのどの文字が変わっても版が変わる、順番に依らない |
| U-research-3 | `run_task`（偽の LLM） | 1 回目の不正 → 再依頼で成功、2 回とも不正で ReplyError、照合の反映 |
| U-memo-1 | `render_memo` | 見出し・根拠と出典・unknown・要注意の表示 |

`DocStore`、`EdinetClient`、`update_index`、`fetch_annual_report`、`fetch_document`、`records` の追加、`collect.py`・`review.py` の流れは、L2 の結合テスト（I-C2-3〜5、I-C4-2〜4）と E2E の E6 で確かめる。

## 訂正履歴

詳細は git の履歴にある。

- 2026-10-15：L3 で分かったことを L2 に反映（claims に `field`、`reviews` から人の判断の列を外す、1 文書の文字数の上限）。文書の取得を `docs` コマンドに分けた
- 2026-10-17：プロンプトの版を内容のハッシュに、照合率を銘柄の全 claims に対する割合に、`sector_medians` の母集団を実行の全銘柄にした。組み立てと流れは `L3_composition.md` へ
- 2026-10-18：経緯の節（L2 の変更、設定の表、実装の順番）を削り、今の設計だけにした。設定は `config.yaml` のコメントが正
