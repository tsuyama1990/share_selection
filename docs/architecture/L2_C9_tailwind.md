# L2 詳細設計：C9 追い風の検知（Tailwind Watch）

作成：2026-10-18 ／ 改訂：2026-10-18（流れで見張り、売上で確かめる形に合わせた） ／ 状態：**設計（受け入れ待ち）**　親：`L1_architecture.md` C9（R8〜R13、N7）　方針と根拠：`docs/tailwind_watch_design.md`（ユーザー了承）　対応テスト：結合テスト（11 章）、E2E は L1 の E9〜E13

凡例：✅ 実装済み ／ 🆕 未実装

## 1. 責務

週 1 回、官公庁・海外の規則・金利と為替から需要を変える出来事を拾い（R8・R9）、同じ向きの出来事を「流れ」にまとめて重なりと期限を記録し（R10）、流れの恩恵を受ける会社を特定して見張りの一覧を出す（R11・R12）。月 1 回、`fetch` の後に地図の会社の売上の前年比を記録し、伸びて加速した会社に Value Turn の足切りと二次調査の結果を添えて通知する（R12）。選ばれなかったものも含めて記録し、後の採点に使う（R13）。最終判断は人。

## 2. モジュール

| モジュール | 責務 | 状態 |
|---|---|---|
| `govfeed.py` | 情報源ごとの取り込み：e-Gov の RSS と案件のページ（案件番号・日付）、閣議案件の一覧、Federal Register の API、FRED の系列、添付の PDF の本文（`webfetch.py` の PDF の文字化）。許可リストの外へは取りに行かない | 🆕 |
| `triage.py` | 選別と項目の抜き出し（LLM、`verify.py` の引用の照合）、流れへの割り当ての候補、確度と期間の規則（4 章）、金利・為替の局面の変わり目の判定 | 🆕 |
| `ledger.py` | 台帳（`tailwind.db_file`、git 対象外）：案件、出来事、流れ、（流れ, 会社）の組、売上の記録、通知、評価 | 🆕 |
| `company_map.py` | 会社の地図：需要から検索語（LLM）→ 文書ストアの「事業の内容」の検索 → 上位の会社を LLM で確かめる（引用つき）。業種で指定する流れは 33 業種で割り当てる | 🆕 |
| `tailwind.py` | `watch`（週）・`confirm`（月）・`tailwind-eval` の流れ、売上の選ぶ条件、通知の Markdown | 🆕 |
| `collect.py`（C2） | `profiles` の流れ：全銘柄に既存の `fetch_annual_report` を回す（`docs` と同じ節を入れる）。`docs` に銘柄の指定を足す | ✅ |
| `cache.py`（C2） | 地図の会社の `info`（`revenueGrowth`・`mostRecentQuarter`）を読む | ✅ |
| `review.py`（C4） | 二次調査（既存）。`confirm` が足切りを通った会社を渡す | ✅ |
| `records.py`（C5） | 最新の実行の全銘柄の判定（通過・落ちた条件）を読む | ✅ |
| `review_store.py`（C5） | 地図の会社の最新の T1 の需要の波を読む | ✅ |

## 3. 処理の流れ

### 3.1 `watch`（週 1 回）

```
前提：tailwind-eval の合格の記録（プロンプトの版と最初のモデル）。無ければ拒否（終了コード 1）
 1. 取り込み（govfeed.py）：情報源ごとに新しい案件（台帳に無い (source, item_id)）と系列の新しい値。失敗は案件ごとに記録して続ける
 2. 選別（triage.py）：案件ごとに LLM が「需要を変える出来事か」と項目（5 章）を引用つきで返す。系列は局面の変わり目（4.4）を出来事にする
 3. 流れ（ledger.py）：案件番号が同じ出来事は機械で同じ流れへ。それ以外は LLM の割り当ての候補を記録し、人の確認を待つ（6.2）。新しい流れの候補も同じ
 4. 流れの項目の計算（triage.py の規則）：始まり、重なり、期限、確度、状態
 5. 地図（company_map.py）：地図が無いか需要が変わった流れについて会社を特定し、組を記録
 6. 見張りの一覧（tailwind.py）：9.1 の形の Markdown を `tailwind.alert_dir` に書く
```

### 3.2 `confirm`（月 1 回、`fetch` と `analyze` の後）

```
 1. 地図の会社ごとに、キャッシュの info から売上の前年比と四半期の日付を読み、台帳の売上の記録に足す（同じ四半期は上書きしない）
 2. 選ぶ条件（6.5 の方針の文書、値は config）：前年比 > 0、かつ流れの始まりの時点の記録より加速、かつ流れの地図の会社の中央値以上。状態が「終わった」流れは除く
 3. 足切りの結果（records.py）：最新の実行の通過・落ちた条件を組に写す（足切りはやり直さない）
 4. 二次（review.py）：足切りを通った会社のうち、まだ調べていない会社を docs → review に渡す（上限 `tailwind.max_review_tickers`）
 5. 通知（tailwind.py）：9.2 の形の Markdown。通知した組を台帳に記録
```

同じ月にもう一度実行しても、1 は同じ四半期を飛ばし、4 は調査済みを飛ばし、5 は同じ内容を上書きする（行は増えない）。

### 3.3 `profiles`（年 1 回＋月 1 回の差分）

EDINET の索引を更新し、全銘柄について最新の有価証券報告書が文書ストアに無ければ `fetch_annual_report`（既存、`edinet.sections` の節）。失敗は銘柄ごとに記録して続け、取得済みは飛ばす。

### 3.4 `tailwind-eval`

正解のある案件（`eval/tailwind_cases.yaml`）で選別と項目の抜き出しを採点し、合否を台帳に記録する。不合格は終了コード 1（8 章）。

## 4. 段階・確度・期間・変わり目の規則

### 4.1 情報源と段階

| 情報源 | 取り込む単位 | 段階 | 日付 |
|---|---|---|---|
| e-Gov 募集（`pcm_list.xml`、`PCMMSTDETAIL`） | 案件（案件番号） | 案 | 案の公示日 |
| e-Gov 結果（`pcm_result.xml`、`PCM1040`） | 案件（案件番号） | 確定（ページに公布日があれば公布） | 結果の公示日、命令等の公布日 |
| 首相官邸の閣議案件 | 案件（閣議の日付と案件名） | 法律案・予算案は案、政令・閣議決定は確定 | 閣議の日付 |
| Federal Register | 文書（document number） | Proposed Rule は案、Rule は確定 | 公示日、施行日（effective date） |
| FRED | 系列（月次） | 変わり目（4.4）は確定 | 系列の月 |

e-Gov の募集と結果は、両方のページに載る案件番号で結ぶ [データ：2026-10-18、案件番号 595320006・620340009 のページで確認]。

### 4.2 確度（規則。値は `config.yaml`）

| 強制の種類 | 段階：案 | 段階：確定以上 |
|---|---|---|
| 義務（法令・告示・基準・海外の規則で対象に求める） | 中 | 高 |
| 予算・補助（金額や事業が書かれている） | 中 | 高 |
| 市場の変化（金利・為替の変わり目） | — | 中 |
| 推奨（指針で促す） | 低 | 中 |

流れの確度は、属する出来事の最も高い確度。見張りの一覧には全部載せ、確度は並べる順に使う（通知の合図は売上、3.2）。

### 4.3 期限と期間

出来事の期限は、施行日と経過措置の終わりの遅いほう（予算は年度の終わり）。流れの期限は属する出来事の期限の最も遅いもの。金利・為替の流れは期限なし（逆向きの変わり目で「終わった」）。期限まで `tailwind.ending_soon_days`（182 日）を切ったら「終わりが近い」。

### 4.4 金利・為替の変わり目

系列の直近 `tailwind.macro.window_months`（6）か月の変化の向きが、前の同じ長さの期間と逆になり、変化の大きさが `tailwind.macro.min_change`（系列ごと）以上の月を出来事とする。初期の系列：日本の 10 年国債利回り（`IRLTLT01JPM156N`）、円ドル（FRED の系列。L3 で系列 ID を確かめる）。A.7 では変わり目の後の 6 か月の先行性は弱かったため、変わり目は見張りの開始にだけ使う。

## 5. 選別のインタフェース（`triage.py`）

入力：案件の題名、ページの本文、添付の PDF の本文（1 件の上限 `tailwind.max_doc_chars`）、既存の流れの一覧（名前と需要）。出力（JSON、`research.py` と同じ claims の形）：

```json
{"answer": {"relevant": true, "event": "...", "demand": "誰に何の支出が増えるか", "direction": "追い風|逆風",
            "enforcement": "義務|予算|推奨|該当なし", "target": "...",
            "effective_date": "YYYY-MM-DD|unknown", "transition_end": "YYYY-MM-DD|unknown",
            "budget_amount": "文書の表記のまま|unknown",
            "flow": {"existing_flow_id": "...|null", "new_flow_name": "...|null", "sector33": "...|null"}},
 "claims": [{"field": "...", "claim": "...", "quote": "逐語引用", "doc_id": "..."}],
 "unknown": [...]}
```

- `relevant` が false の案件は、理由とともに案件として記録するだけ
- 引用の照合は `verify.py`。照合できない項目は unknown（N3）。LLM は確度・期間・状態を判断しない
- プロンプトは `prompts/tailwind/`、版は内容のハッシュ。版が変われば `tailwind-eval` をやり直す

## 6. 台帳（`ledger.py`、`tailwind.db_file`）

### 6.1 表

| 表 | 主キー | 列 |
|---|---|---|
| `feed_items` | (source, item_id) | url、title、published、fetched_at、status、error、relevant、reason、event_id |
| `events` | event_id | event、demand、direction、enforcement、target、effective_date、transition_end、budget_amount、confidence、evidence、prompt_version、llm_provider、updated_at |
| `event_stages` | (event_id, stage) | date、source、item_id |
| `flows` | flow_id | name、demand、direction、sector33、started、overlap_12m、deadline、confidence、state、updated_at |
| `flow_events` | (flow_id, event_id) | assigned_by（機械／人）、assigned_at |
| `flow_candidates` | (event_id, candidate) | 割り当ての候補（既存の流れか新しい流れ）、理由、resolved |
| `flow_companies` | (flow_id, ticker) | tier、exposure、evidence、verified_ratio、mapped_at |
| `company_sales` | (ticker, quarter_end) | revenue_growth、recorded_at（`fetch` の日） |
| `confirmations` | (month, flow_id, ticker) | revenue_growth、accel、flow_median、selected、run_id、gate_passed、fail_rule、reviewed_run_id |
| `alerts` | (period, kind, flow_id, ticker) | kind は 新しい流れ／強まった流れ／終わりが近い／割り当ての確認／売上で確かめられた |
| `tailwind_evals` | (prompt_version, model, evaluated_at) | 指標、passed |

Parquet の書き出しは `tailwind.export_dir`（git 対象外）。`backup` の対象に `tailwind.db_file` を足す。

### 6.2 流れへの割り当て

- 機械で結ぶ：e-Gov の案件番号が同じ出来事は同じ流れ
- 人が決める：それ以外の割り当てと新しい流れは、LLM の候補（引用つき）を `flow_candidates` に入れ、見張りの一覧に載せる。人が台帳に結ぶまでは、その出来事は流れの重なりに数えない（自動では結ばない。誤った重なりで流れを強く見せないため）
- 人の操作の入口（コマンドの引数か、台帳への書き込みか）は L3 で決める

## 7. 会社の地図（`company_map.py`）

1. 業種で指定する流れ（`flow.sector33` がある）：`japan_tickers.csv` の 33 業種で会社を割り当てる（引用は業種の理由の 1 つ）
2. それ以外：需要から製品・サービス・業界の言葉を LLM に挙げさせ（`tailwind.map.max_terms`）、全銘柄の「事業の内容」とセグメント情報を正規化（NFKC）した本文の部分一致の数で順位を付け、上位 `tailwind.map.top_k` 社を LLM で確かめる（「その需要に売っているか」「何次の供給元か」「売上に占める割合」、引用つき、`verify.py`、`Company.mentioned_in`）
3. 何次の供給元かは記録するが、選ぶ条件には使わない（方針の文書 D4）

## 8. 品質の関門（`tailwind-eval`）

| 項目 | 内容 |
|---|---|
| 正解のファイル | `eval/tailwind_cases.yaml`：案件の本文（取得済みの写し）と正解（relevant、direction、enforcement、effective_date、transition_end）。需要を変える案件と変えない案件を両方含める。例：省エネ法のサッシの性能の基準の改正（案件番号 620340009、変える）、ワシントン条約の輸入手続の改正（595320006、変えない） |
| 指標 | relevant の適合率と再現率、direction と enforcement の一致率、日付の一致率、照合率 |
| 合格基準 | L3 で正解の件数と合わせて決める。合格の記録が無い版・モデルでは `watch` を拒む |
| 正解の確かめ | ユーザーが確かめてから使う |

## 9. 通知（`tailwind.py`、Markdown）

### 9.1 見張りの一覧（週、`tailwind.alert_dir/watch-<週>.md`）

新しい流れ、強まった流れ（重なりが増えた）、終わりが近い流れ（期限まで 182 日）、終わった流れ、割り当ての確認（6.2）、流れごとの地図の会社（何次か、最新の T1 の需要の波）、取り込み・選別・地図の失敗の数。**買いの合図ではない**と冒頭に書く。

### 9.2 売上の確認（月、`tailwind.alert_dir/confirm-<月>.md`）

選ばれた会社ごとに：流れ（始まり・重なり・期限・確度・出典の URL と引用）、売上の前年比と加速、流れの地図の会社の中央値、足切りの結果（通過／落ちた条件）、二次の提案（採用・落選・監視）。終わりが近い流れの地図の会社の一覧。

メールなどへの送り方は方針の文書 11 章の未決事項（先送り：ユーザーが決める）。

## 10. 設定（`config.yaml` に追加する節。キーは実装と同じブランチで足す）

`tailwind:`（`db_file`、`export_dir`、`alert_dir`、`sources`（情報源ごとの URL・段階の対応・系列 ID）、`allowed_hosts`（N7）、`max_items_per_run`、`max_doc_chars`、`ending_soon_days`、`confidence`（4.2 の表）、`macro.window_months`、`macro.min_change`、`map.max_terms`、`map.top_k`、`confirm.min_growth`、`confirm.require_acceleration`、`confirm.min_flow_percentile`、`max_review_tickers`、`prompts_dir`、`eval_cases`）。

## 11. 結合テスト計画

情報源・EDINET・LLM はモック、DB は一時ファイル。フィクスチャの案件のページは 2026-10-18 に取った実物の形（案件番号 595320006 の結果、620340009 の募集）にそろえる。

| ID | 対象 | 確かめること | 状態 |
|---|---|---|---|
| I-C9-1 | `govfeed.py` とモックの HTTP | e-Gov の募集と結果から案件番号・段階・日付。閣議案件の一覧。Federal Register の文書の種類と日付。FRED の系列。添付の PDF の本文。許可リストの外は取りに行かず失敗として記録。1 件の失敗で他が止まらない | 🆕 |
| I-C9-2 | `triage.py`＋`verify.py`＋偽の LLM | JSON の検証と 1 回の再依頼、照合できない項目は unknown、relevant が false なら出来事を作らない、確度の表の全マス、期限・状態の計算、金利の系列の変わり目の判定 | 🆕 |
| I-C9-3 | `ledger.py`（一時 DB） | 同じ案件番号の募集と結果が 1 件の出来事・1 つの流れになり段階が足される。人が結ぶまで候補は重なりに数えない。もう一度入れても行が増えない。Parquet の書き出し | 🆕 |
| I-C9-4 | `company_map.py`＋文書ストア＋偽の LLM | 検索で正解の会社が上位 `top_k` に入る。照合できない「売っている」の主張の会社は組にならない。業種で指定した流れは 33 業種で割り当てる | 🆕 |
| I-C9-5 | `profiles` の流れ（`collect.py`）とモックの EDINET | 全銘柄の節が入る。失敗は記録して続ける。取得済みを飛ばす。後の `docs` がその銘柄の EDINET の取得を飛ばす | 🆕 |
| I-C9-6 | 見張りの一覧（`tailwind.py`）＋台帳 | 新しい流れ・強まった流れ・終わりが近い流れ・割り当ての確認の節。買いの合図ではない旨。キーが出力に出ない | 🆕 |
| I-C9-7 | `tailwind-eval`（偽の LLM・一時 DB） | 正解との一致で合否、記録、合格の記録が無い版では `watch` が拒む | 🆕 |
| I-C9-8 | `confirm`（キャッシュ・台帳・記録・偽の review） | 売上の記録（同じ四半期を上書きしない）、選ぶ条件（前年比・加速・中央値・終わった流れの除外）、足切りの結果の写し、調査済みを飛ばす、通知の節 | 🆕 |

### 11.1 確かめること（実装の前、ライブ）

| 項目 | 内容 |
|---|---|
| Yahoo の `revenueGrowth` の正確さ | 地図の候補になりそうな 20 社で、`revenueGrowth` と `mostRecentQuarter` を決算短信の売上の前年同期比と照合する（三菱重工が 0.0 だった。欠けた値が 0 で入っていないかも確かめる）。合わなければ方針の文書 11 章の経路をユーザーが決める |
| 首相官邸の閣議案件の本文 | 案件の PDF の取り方 |
| FRED の円ドルの系列 ID | 系列と更新の頻度 |

### 11.2 ライブ確認の予定（実装の後に L1 7.1 へ移す）

e-Gov・閣議案件・Federal Register・FRED の取得、`profiles`（3 銘柄）、`tailwind-eval`、`watch`・`confirm`（一時ディレクトリ、キーがどこにも出ない）。

## 12. 決定・先送り

| 項目 | 内容 |
|---|---|
| 通知の合図は売上の確認 | 決定（方針の文書 3 章・D1、2026-10-18 ユーザー了承） |
| 確度・期間を規則で決める | 決定（方針の文書 D2） |
| 流れへの割り当ては、案件番号以外は人が決める | 決定（誤った重なりを避ける） |
| 足切りはやり直さず、最新の実行の記録を使う | 決定（キャッシュは月 1 回の `fetch`） |
| 地図の検索は部分一致から | 決定（新しい依存を入れない）。段階 2 の関門で取りこぼしが多ければ見直す |
| `profiles` は `docs` と同じ節を入れる | 決定（取得の重複と食い違いを避ける） |
| 売上のデータは Yahoo の `revenueGrowth` から | 決定（無料、既に取得している）。11.1 の照合で合わなければ見直す |
| 通知の送り方、定期実行、TDnet の経路 | 先送り（ユーザーが決める。方針の文書 11 章） |
| 合格基準・選ぶ条件の値 | 先送り（L3 で正解の件数と合わせて決める。選ぶ条件は採点で直す） |
| 採点（方針の文書 7 章）の計算 | 先送り（記録が貯まってから。記録の形は 6.1 で今決める） |

## 13. 訂正履歴

- 2026-10-18：方針の文書の改訂（流れで見張り、売上で確かめる）に合わせて書き直した。`watch` は見張りの一覧だけを出し、足切りと二次は月 1 回の `confirm`（3.2、I-C9-8、L1 E13）へ移した。情報源に Federal Register と FRED を加え、出来事を流れにまとめる表（`flows`・`flow_events`・`flow_candidates`）と売上の記録（`company_sales`・`confirmations`）を足した
