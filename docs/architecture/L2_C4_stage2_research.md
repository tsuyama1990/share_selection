# L2 詳細設計：C4 二次調査

作成：2026-10-14 ／ 状態：**承認・実装済み**（業種の勢いの追加は未実装）　親：`L1_architecture.md` C4　対応テスト：結合テスト（8 章）、E2E は L1 の E6

凡例：✅ 実装済み ／ 🆕 未実装

## 1. 責務

二次候補（`Stage2_Candidate`）ごとに、業種の文脈と同業比較（機械）、一次情報と Web 検索にもとづく企業分析（LLM）、引用の照合を行い、根拠付きの調査結果を `reviews` に記録し、調査メモを出す（L1 R5、N2〜N4）。最終判断は人。

## 2. モジュール

| モジュール | 責務 | 状態 |
|---|---|---|
| `llm.py` | OpenAI 互換のチャット（`llm.providers` の順のフォールバック。2026-10-17 から DeepSeek → Gemini → Groq、レート制限）、Gemini ネイティブの検索 | ✅ |
| `sector.py` | 2-1・2-3：業種（33 業種）ごとの中央値と、候補の同業比較（機械）。🆕 業種の勢いと業種の中の位置（3 章 1 の追加） | ✅ |
| `research.py` | T1〜T5 のプロンプトの組み立て、LLM 呼び出し、JSON の検証 | ✅ |
| `verify.py` | 引用の照合（正規化した部分一致）、照合できない主張の除外、照合率 | ✅ |
| `review.py` | `review` の流れ：候補ごとに文書 → T1〜T5 → 照合 → 記録 → 調査メモ、失敗は状態として残す | ✅ |
| `review_eval.py` | モデルの品質の関門：正解のある銘柄の採点と合否（`L3_composition.md` 5.3） | ✅ |
| `memo.py`（C6） | 調査メモ（銘柄ごとの Markdown）の出力 | ✅ |
| `records.py`（C5） | 実行記録（候補・全銘柄の指標を C4 に渡す） | ✅ |
| `review_store.py`（C5） | `reviews`・`review_evals`（別の DB ファイル `review.db_file`、Parquet は `review.export_dir`。どちらも git 対象外） | ✅ |

## 3. 処理の流れ（`review` コマンド）

```
入力：最新の実行の二次候補（screen_results / 結果 CSV）
 1. 業種の文脈（sector.py）：同じ実行の全銘柄の指標から、業種ごとの中央値（実質PSR、PBR、改善の大きさ）→ 候補ごとの同業比較
    業種の勢い（3.1 節）も計算し、同業比較の表の下に 1 行で載せる。選ぶ条件には使わない
 2. 文書の読み出し：文書ストアから候補の文書（`docs` コマンドが事前に取得。L2 C2 2.1 節）
 3. 調査（research.py）：T1 改善の源泉、T2 一時的な損益、T3 資本の使い方、T4 忘れられている理由 → T5 総合
 4. 照合（verify.py）：各主張の引用が、渡した文書の本文に含まれるか
 5. 記録（review_store.py `reviews`）と調査メモ（memo.py）
```

銘柄の失敗（文書が取れない、全プロバイダーの失敗、JSON 不正）は、その銘柄の `reviews` に状態として残し、次の銘柄へ進む。

### 3.1 業種の勢い（R13）

同業比較の表の下に、事実として 1 行を足す。二次候補と順位は変えない（選ぶ条件に使わない）。

| 項目 | 内容 |
|---|---|
| データ | キャッシュ（`stock_cache` の `history`、日次 1 年）の終値。業種は `japan_tickers.csv` の sector33。母集団はその実行の全銘柄（足切りの前） |
| 期間 | `sector.momentum_months`（初期値 3）。基準日はキャッシュの最新の営業日、始点はその `months` か月前。始点以前の最後の終値と基準日の終値で単純リターンを出す |
| 業種の超過リターン | 業種の全銘柄の期間リターンの等加重平均 − 全銘柄の期間リターンの等加重平均。単純リターン（対数にしない） |
| 全業種の中の順位 | 業種の超過リターンを高い順に並べた順位（1 が最も高い）。同値は同じ順位（最も小さい順位を付ける） |
| 業種の中の位置 | 候補の期間リターンの、同じ業種の中での順位（1 が最も高い）÷ 業種の銘柄数。0〜1。記録はそのまま、表示は四捨五入して 0.1 刻み |
| 記録 | `reviews.sector_comparison` の `momentum` キーに {months, industry_excess, industry_rank, industries, position}。計算できない（履歴が足りない、銘柄がない）値は null |
| 調査メモ | 業種の順位が全業種の上位 `sector.momentum_note_top_share`（初期値 1/3。`industry_rank ÷ industries` がこれ以下）に入り、かつ候補の位置が `sector.momentum_note_position`（初期値 0.5）より大きい（下半分）ときだけ「先に上がった会社はその後負けやすい（有意ではない）」と注記する |
| 関数 | `sector.py` の `momentum`。C9（`flow-memo`）は同じ関数で地図の中の位置を計算する（重複させない） |

シグネチャは `L3_tailwind.md` 3.4 節（母集団を `Universe`、設定を `MomentumSettings` にまとめる）。

履歴が始点に届かない銘柄は母集団から外す。

## 4. 調査タスクのインタフェース

各タスクは「入力文書の一覧（doc_id と本文）＋銘柄の指標」を受け取り、次の JSON を返させる。

```json
{"answer": {...タスクごとの項目...},
 "claims": [{"field": "支える answer の項目名", "claim": "...", "quote": "文書からの逐語引用", "doc_id": "..."}],
 "unknown": ["文書から分からなかった点"]}
```

| タスク | `answer` の項目 |
|---|---|
| T1 改善の源泉 | source_type（P1〜P4）、demand_wave、tier、chokepoint、exposure_pct |
| T2 一時的な損益 | one_off_items（項目・金額）、recurring_view（持続／一時的／不明） |
| T3 資本の使い方 | capital_actions、n2_risk |
| T4 忘れられている理由 | reason_forgotten（事業の弱さ／見えにくさ／期待先行／一時的な悲観） |
| T5 総合 | suggestion（採用／落選／監視）、open_questions |

- 指示：渡した文書だけを根拠にする。分からなければ unknown。数値は文書の表記のまま。
- 温度 0、JSON モード。スキーマに合わない応答は 1 回だけ再依頼し、それでも合わなければ失敗として記録する。
- プロンプトはファイル（`prompts/`）に置き、版はその内容のハッシュ。記録に版を残し、版が変われば品質の関門をやり直す。

## 5. 引用の照合（`verify.py`）

| 規則 | 内容 |
|---|---|
| 正規化 | 全角・半角の統一、空白・改行の除去、記号の統一（NFKC） |
| 一致 | 正規化した引用が、正規化した doc_id の本文の部分文字列であること |
| 除外 | 一致しない主張は捨てる。`answer` の項目が、残った主張で支えられない場合は unknown に置き換える |
| 照合率 | （一致した主張数）÷（主張数）を記録。設定の下限（例 0.7）未満の銘柄は「要注意」として調査メモに明示 |

## 6. 記録（`reviews`、`docs/record_design.md` の設計に沿う）

主キー（run_id, ticker）。列：status（完了／失敗の種類）、suggestion、source_type、reason_forgotten、answers（T1〜T5 の JSON）、evidence（照合できた主張の JSON）、verified_ratio、needs_attention、sector_comparison（JSON）、doc_ids、llm_providers、prompt_version、reviewed_at。人の判断の記録は、調査メモを使い始めてから設計する（先送り）。

保存先は `review.db_file`（`reviews.duckdb`、実行の記録とは別のファイル）、Parquet の書き出し先は `review.export_dir`（どちらも git 対象外）。**リポジトリは公開のため、`reviews` と調査メモはコミットしない**（Web 記事の逐語引用と銘柄ごとの提案を含むため。2026-10-15 決定）。バックアップは公開リポジトリ以外に取る。

## 7. 設定（`config.yaml` に追加する節）

`llm:`（✅ 実装済み）、`review:`（対象の上限件数、照合率の下限、プロンプトの版、1 文書の文字数の上限、書き出し先）、`sector:`（比較に使う指標、`momentum_months`（初期値 3）、`momentum_note_top_share`（初期値 1/3）、`momentum_note_position`（初期値 0.5））。

## 8. 結合テスト計画

LLM・検索・EDINET・Web はモック、DB は一時ファイル。

| ID | 対象 | 確かめること | 状態 |
|---|---|---|---|
| I-C4-1 | `llm.py` とモックの HTTP | フォールバックの順番、キーのないプロバイダーを飛ばす、全失敗のエラー、検索の解析、キーが URL・例外・出力に出ない | ✅（`tests/integration/test_llm.py`） |
| I-C4-2 | `sector.py` と実行記録 | 業種ごとの中央値、候補の同業比較、同業が少ない業種の扱い | ✅ `tests/integration/test_i_c4_2_sector.py` |
| I-C4-3 | `research.py`＋`verify.py`＋モックの LLM | JSON の検証と 1 回の再依頼、引用の照合で捨てる主張、unknown への置き換え、照合率 | ✅ `tests/integration/test_i_c4_3_research_verify.py` |
| I-C4-4 | `review` の 1 銘柄分（文書ストア・LLM・記録） | `reviews` に 1 行、照合できた根拠だけが残る、失敗は状態として残り次へ進む | ✅ `tests/integration/test_i_c4_4_review_one.py` |
| I-C4-5 | `review-eval`（偽の LLM・一時 DB） | 正解との一致・JSON の不正・照合率で合否、合格の記録が無いと `review` が拒む（拒否は E2E の E6） | ✅ `tests/integration/test_i_c4_5_review_eval.py` |
| I-C4-6 | `sector.py` の勢いと `reviews.sector_comparison`・調査メモ（フィクスチャのキャッシュ：2 業種、片方だけ上昇、履歴の足りない銘柄 1 つ） | 業種の超過リターンと全業種の中の順位、業種の中の位置が計算どおり。履歴の足りない銘柄は null。上昇した業種で候補が下半分のときだけ注記が付く。二次候補と順位は変わらない | 🆕 |

E2E（L1 E6）は、複数銘柄で `review` を通しで実行し、調査メモまで出ることを確かめる。

## 8.1 モデルの品質の評価（関門）

正解のある銘柄（`eval/stage2_cases.yaml`。`docs/hypothesis_map.md` と一次情報で確かめたものだけ）で調査を採点し、合格の記録が無い版・モデルでは `review` を拒む。合格基準と流れは `L3_composition.md` 3.3 節。

## 9. 決定・先送り

- 業種の中央値の母集団：**その実行の全銘柄（足切りの前）**（業種全体の期待の水準を見るため）。
- 人の判断の記録：先送り（調査メモを使い始めてから設計する）。

## 10. 訂正履歴

詳細は git の履歴にある。

- 2026-10-15：文書の取得と検索を `docs` コマンド（C2）へ。claims に `field` を足し、`reviews` から人の判断の列を外し、1 文書の文字数の上限を足した。`reviews` と調査メモはコミットしない（公開リポジトリ）
- 2026-10-17：流れを `review.py`、品質の関門を `review_eval.py`（I-C4-5）、記録を `review_store.py` に置いた。主のモデルは DeepSeek
- 2026-10-18：業種の勢いと業種の中の位置（Tailwind Watch の ①）を追加予定として書いた。8.1 節の古い正解の表を削り、`L3_composition.md` と正解のファイルを正とした
- 2026-10-18：`momentum` の引数を L3 でまとめた（6 → 4、`Universe`・`MomentumSettings`）
