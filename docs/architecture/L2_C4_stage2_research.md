# L2 詳細設計：C4 二次調査

作成：2026-10-14 ／ 状態：**承認（2026-10-14）・QA 完了**　親：`L1_architecture.md` C4、`docs/stage2_automation_design.md`　対応テスト：結合テスト（7 章）、E2E は L1 の E6

凡例：✅ 実装済み ／ 🆕 未実装

## 1. 責務

二次候補（`Stage2_Candidate`）ごとに、業種の文脈と同業比較（機械）、一次情報と Web 検索にもとづく企業分析（LLM）、引用の照合を行い、根拠付きの調査結果を `reviews` に記録し、調査メモを出す（L1 R5、N2〜N4）。最終判断は人。

## 2. モジュール

| モジュール | 責務 | 状態 |
|---|---|---|
| `llm.py` | OpenAI 互換のチャット（Gemini → Groq → DeepSeek のフォールバック、レート制限）、Gemini ネイティブの検索 | ✅ |
| `sector.py` | 2-1・2-3：業種（33 業種）ごとの中央値と、候補の同業比較（機械） | 🆕 |
| `research.py` | T1〜T5 のプロンプトの組み立て、LLM 呼び出し、JSON の検証 | 🆕 |
| `verify.py` | 引用の照合（正規化した部分一致）、照合できない主張の除外、照合率 | 🆕 |
| `memo.py`（C6） | 調査メモ（銘柄ごとの Markdown）の出力 | 🆕 |
| `records.py`（C5） | 実行記録。`reviews` テーブルの追加は未実装（L3 で設計） | ✅ |

## 3. 処理の流れ（`review` コマンド）

```
入力：最新の実行の二次候補（screen_results / 結果 CSV）
 1. 業種の文脈（sector.py）：同じ実行の全銘柄の指標から、業種ごとの中央値（実質PSR、PBR、改善の大きさ）→ 候補ごとの同業比較
 2. 文書の用意（C2）：最新の有価証券報告書の節（EDINET）／Web 検索（llm.GeminiSearch）→ 出典の本文（webfetch）→ 文書ストア
 3. 調査（research.py）：T1 改善の源泉、T2 一時的な損益、T3 資本の使い方、T4 忘れられている理由 → T5 総合
 4. 照合（verify.py）：各主張の引用が、渡した文書の本文に含まれるか
 5. 記録（records.py `reviews`）と調査メモ（memo.py）
```

銘柄の失敗（文書が取れない、全プロバイダーの失敗、JSON 不正）は、その銘柄の `reviews` に状態として残し、次の銘柄へ進む。

## 4. 調査タスクのインタフェース

各タスクは「入力文書の一覧（doc_id と本文）＋銘柄の指標」を受け取り、次の JSON を返させる。

```json
{"answer": {...タスクごとの項目...},
 "claims": [{"claim": "...", "quote": "文書からの逐語引用", "doc_id": "..."}],
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
- プロンプトはファイル（`prompts/` 配下、版番号付き）に置き、記録に版を残す。

## 5. 引用の照合（`verify.py`）

| 規則 | 内容 |
|---|---|
| 正規化 | 全角・半角の統一、空白・改行の除去、記号の統一（NFKC） |
| 一致 | 正規化した引用が、正規化した doc_id の本文の部分文字列であること |
| 除外 | 一致しない主張は捨てる。`answer` の項目が、残った主張で支えられない場合は unknown に置き換える |
| 照合率 | （一致した主張数）÷（主張数）を記録。設定の下限（例 0.7）未満の銘柄は「要注意」として調査メモに明示 |

## 6. 記録（`reviews`、`docs/record_design.md` の設計に沿う）

主キー（run_id, ticker）。列：status（完了／失敗の種類）、suggestion、source_type、reason_forgotten、answers（T1〜T5 の JSON）、evidence（照合できた主張の JSON）、verified_ratio、sector_comparison（JSON）、doc_ids、llm_providers、prompt_version、searched（検索の有無）、human_decision、decided_at。Parquet にも書き出す。

## 7. 設定（`config.yaml` に追加する節）

`llm:`（✅ 実装済み）、`review:`（対象の上限件数、照合率の下限、検索の有無、プロンプトの版、1 回の実行の呼び出し上限）、`sector:`（比較に使う指標）。

## 8. 結合テスト計画

LLM・検索・EDINET・Web はモック、DB は一時ファイル。

| ID | 対象 | 確かめること | 状態 |
|---|---|---|---|
| I-C4-1 | `llm.py` とモックの HTTP | フォールバックの順番、キーのないプロバイダーを飛ばす、全失敗のエラー、検索の解析、キーが URL・例外・出力に出ない | ✅（`tests/integration/test_llm.py`） |
| I-C4-2 | `sector.py` と実行記録 | 業種ごとの中央値、候補の同業比較、同業が少ない業種の扱い | 🆕 |
| I-C4-3 | `research.py`＋`verify.py`＋モックの LLM | JSON の検証と 1 回の再依頼、引用の照合で捨てる主張、unknown への置き換え、照合率 | 🆕 |
| I-C4-4 | `review` の 1 銘柄分（文書ストア・LLM・記録） | `reviews` に 1 行、照合できた根拠だけが残る、失敗は状態として残り次へ進む | 🆕 |

E2E（L1 E6）は、複数銘柄で `review` を通しで実行し、調査メモまで出ることを確かめる。

## 9. 決定・先送り（2026-10-14 承認）

- 業種の中央値の母集団：**その実行の全銘柄（足切りの前）**（決定。業種全体の期待の水準を見るため）。
- `feat/llm-client`：本設計の `llm.py` の責務と一致。テストを結合テストの階層へ移し、設計の関門を通してマージした（2026-10-14）。

## 10. 訂正履歴

（なし）
