# L2 詳細設計：C9 流れの調査（Tailwind Watch）

作成：2026-10-18 ／ 状態：**設計（受け入れ待ち）**　親：`L1_architecture.md` C9（R8〜R12）　方針：`docs/tailwind_watch_design.md` 4 章　対応テスト：結合テスト（7 章）、E2E は L1 の E9〜E11

凡例：✅ 実装済み ／ 🆕 未実装

## 1. 責務

人が指定した流れについて、5 つの軸の引用と数値、恩恵企業の地図、会社ごとの Value Turn の判定と割安さを、引用を照合した調査メモにまとめる（R8〜R10）。人の判断を記録し、6・12 か月後に機械の合図と比べて答え合わせする（R11・R12）。最終判断は人。

## 2. モジュール

| モジュール | 責務 | 状態 |
|---|---|---|
| `company_map.py` | 需要から検索語（LLM）→ 文書ストアの全銘柄の「事業の内容」とセグメント情報を正規化（NFKC）して部分一致で順位付け → 上位 `flow.map.top_k` 社を LLM で確かめる（売っているか、何次か、売上に占める割合、引用）。照合できない会社は載せない | ✅ |
| `flow.py` | `flow-memo` の流れ：根拠の文書を集める（Gemini の検索と指定の URL、`webfetch.py`）→ 5 つの軸の抜き出し（LLM、`verify.py`）→ 地図 → 会社ごとの数値 → 調査メモ（Markdown）。`flow-decide` の記録 | ✅ |
| `flow_store.py` | `flow.db_file`（git 対象外）：流れ、根拠の文書の ID、軸の抜き出し、地図、判断 | ✅ |
| `sector.py`（C4） | `momentum`：業種の超過リターンと順位、業種の中の位置（L2 C4 3.1 節）。`flow-memo` の地図の中の位置もこの関数で計算する | ✅ |
| `collect.py`（C2） | `profiles`：全銘柄に既存の `fetch_annual_report` を回す（`docs` と同じ節。取得済みは飛ばす） | ✅ |
| `outcomes.py`（C5） | `evaluate` で、判断の 6・12 か月後の超過リターンと、比べる相手（同じ業種の、まだ上がっていない割安株）を計算する | ✅ |

## 3. 処理の流れ

```
flow-memo --name <名前> --demand <需要の説明> [--url <出典> ...]
 1. 根拠の文書：Gemini の検索（docs と同じ仕組み、`flow.search_prompt`）と指定の URL を取得し、文書ストアに入れる
 2. 5 つの軸（規模・強制と裾野・持続・注目の広がり・織り込み度）と終わりの手がかりを、LLM が文書から引用つきで抜き出す。照合できない主張は捨て、軸は「不明」
 3. 地図（company_map.py）。文書ストアに「事業の内容」が無ければ、先に profiles を実行するよう案内して止める
 4. 会社ごとの数値：最新の実行の記録（通過・落ちた条件・改善区分・PBR・PER・実質 PSR と業種の中央値）、キャッシュの株価（直近 3 か月の上昇と地図の中の位置）、最新の reviews の T1 の需要の波
 5. 調査メモ（`flow.memo_dir/<流れ>-<日付>.md`）と記録

flow-decide --flow <ID> --ticker <コード> --action buy|skip --reason <理由> [--max-yen <金額>]
 判断を記録する（見送るも記録）

evaluate（既存）
 判断の翌月から 6・12 か月を過ぎた判断について、超過リターンと比べる相手の超過リターンを計算する
```

LLM の出力は `research.py` と同じ claims の形（answer・claims・unknown）。プロンプトは `prompts/flow/`、版は内容のハッシュ。

### 3.1 引数

- `flow-memo`：`--name <名前>`、`--demand <需要の説明>`、`--url <出典>`（複数可）。
- `flow-decide`：`--flow <ID>`、`--ticker <コード>`、`--action buy|skip`、`--reason <理由>`、`--max-yen <金額>`（任意）。

### 3.2 軸の抜き出しの JSON

```json
{"answer": {"scale": "…", "compulsion": "…", "persistence": "…", "attention": "…", "priced_in": "…", "ending": "…"},
 "claims": [{"field": "…", "claim": "…", "quote": "…", "doc_id": "…"}],
 "unknown": ["…"]}
```

照合できない主張だけが支える項目は `"unknown"` にする。

### 3.3 地図の確かめの JSON

```json
{"answer": {"sells": true, "tier": "1次", "exposure": "…"},
 "claims": [{"field": "…", "claim": "…", "quote": "…", "doc_id": "…"}],
 "unknown": ["…"]}
```

`tier` は `1次`・`2次`・`3次以上`・`unknown`。`exposure` は文書の表記のまま、分からなければ `unknown`。`sells` の主張が照合できなければ、その会社は地図に載せない。地図の中の位置は `sector.py` の `momentum`（L2 C4 3.1 節）と同じ関数で計算する。

### 3.4 LLM の呼び出し数の上限

軸の抜き出し 1 回（再依頼 1 回）＋ 検索語 1 回 ＋ `flow.map.top_k` 社 × 1 回（再依頼 1 回）。

## 4. 記録（`flow_store.py`）

| 表 | 主キー | 列 |
|---|---|---|
| `flows` | flow_id | name、demand、urls、created_at、prompt_version、llm_provider |
| `flow_axes` | (flow_id, axis) | answer、evidence（照合できた主張）、verified_ratio |
| `flow_companies` | (flow_id, ticker) | tier、exposure、evidence、run_id、stage1_pass、fail_rule、valuations（JSON）、past3m_rank |
| `flow_decisions` | (flow_id, ticker, decided_at) | action、reason、max_yen |
| `flow_outcomes` | (flow_id, ticker, decided_at, months) | excess、control_excess、control_n |

比べる相手：判断の月に、同じ 33 業種で「直近 3 か月の上昇が業種の中央値以下、かつ PBR が業種の中央値以下」の会社の平均（方針の文書の学び 1）。

## 5. 設定（`config.yaml` に追加する節。キーは実装と同じブランチで足す）

`flow:`（`db_file`、`memo_dir`、`prompts_dir`、`search_prompt`、`max_sources`、`max_doc_chars`、`map.max_terms`、`map.top_k`、`outcome_months`、`control.past_months`）。

## 6. 決定・先送り

| 項目 | 内容 |
|---|---|
| 流れは人が指定する | 決定（機械の合図で先回りしない。方針の文書の学び 1） |
| 軸に点数を付けない | 決定（効く点数の根拠が無い。学び 2） |
| 足切りはやり直さず、最新の実行の記録を使う | 決定 |
| 地図の検索は部分一致から | 決定（新しい依存を入れない）。既知の恩恵企業を拾えなければ見直す |
| 止める基準 | 方針の文書 6 章の未決事項（ユーザーが決める） |
| 調査メモの品質の関門 | 先送り（最初の数件を人が採点して正解を作ってから） |

## 7. 結合テスト計画

LLM・検索・EDINET・Web はモック、DB は一時ファイル。

| ID | 前提 | 操作 | 合格基準 | 状態 |
|---|---|---|---|---|
| I-C9-1 | 銘柄一覧 4 社（需要の語を「事業の内容」に含む 2 社）、文書ストア、偽の LLM（検索語は固定、1 社の `sells` の引用は文書に無い文） | `company_map.py` で地図を作る | 売っている 2 社が `top_k` に入る。引用を照合できない 1 社は載らない。各社の確かめはその会社の報告書の doc_id だけを使う | ✅ `tests/integration/test_i_c9_1_company_map.py` |
| I-C9-2 | 文書ストア、偽の LLM（軸ごとに文書の文を引用する答え。1 回目は JSON 不正） | `flow.py` の軸の抜き出し | JSON 不正は 1 回だけ再依頼する。照合できない主張だけが支える軸は「不明」。照合率を記録する。呼び出しは 2 回以内 | ✅ `tests/integration/test_i_c9_2_flow_axes.py` |
| I-C9-3 | Value Turn の実行の記録、株価のキャッシュ | 会社ごとの数値を作る | 通過・落ちた条件・改善区分・PBR・PER・実質 PSR と業種の中央値、直近 3 か月の地図の中の位置（`sector.momentum` と同じ値）が記録どおり | ✅ `tests/integration/test_i_c9_3_flow_companies.py` |
| I-C9-4 | 一時 DB | 流れ・軸・地図・判断を 2 回入れる | 1 回目で行が入り、2 回目で増えない。流れ・軸・地図・判断を読み出せる | ✅ `tests/integration/test_i_c9_4_flow_store.py` |
| I-C9-5 | 銘柄一覧 4 社、EDINET のモック（3 社に報告書、1 社は 500） | `profiles` を 2 回 | 1 回目：3 社の「事業の内容」とセグメント情報が入り、1 社は失敗として記録され、全体は止まらない。2 回目：取得済みの 3 社を飛ばし、失敗した 1 社だけ取り直す | ✅ `tests/integration/test_i_c9_5_profiles.py` |
| I-C9-6 | 判断の記録、7 か月分の価格のフィクスチャ | `evaluate` | 6 か月を過ぎた判断だけ、超過リターンと比べる相手の超過リターンを計算する。相手は同じ業種で直近 3 か月の上昇が中央値以下かつ PBR が中央値以下の会社。12 か月はまだ計算しない | ✅ `tests/integration/test_i_c9_6_flow_outcomes.py` |

## 8. 訂正履歴

- 2026-10-18：方針の文書の作り直し（2 本立て）に合わせて全面的に書き直した。週 1 回の自動の取り込み・流れの台帳・`watch`・`confirm`・`tailwind-eval` の設計（モジュール `govfeed.py`・`triage.py`・`ledger.py`・`tailwind.py`）は作らないため削除した
