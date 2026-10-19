# 引き継ぎ（次のセッションが最初に読む）

更新：2026-10-20。今の状態と次の一手だけを書く。設計の詳細は各設計書、経緯は git の履歴。

## 1. 今の状態

| 対象 | 状態 | 設計 |
|---|---|---|
| Value Turn（月 1 回のスクリーン） | 実装済み。一次（足切り・改善・順位）、二次（`docs`・`review`、品質の関門 `review-eval`）、記録と答え合わせ（`evaluate`）、`backup` | `docs/selection_flow.md`、`docs/architecture/L1_architecture.md`（C1〜C7） |
| Tailwind Watch（流れの調査） | 実装済み（2026-10-18）。`profiles`・`flow-memo`・`flow-decide`、`evaluate` での判断の答え合わせ、Value Turn の調査メモへの業種の勢い | `docs/tailwind_watch_design.md`（方針と学び）、L1 C9・R8〜R13、`L2_C9_tailwind.md`、`L3_tailwind.md` |
| git | main は origin より先に進んでいて、**プッシュしていない**（`git log --oneline origin/main..main` で確認。プッシュはユーザーの指示があるときだけ） | — |

## 2. 運用の手順

- 月 1 回（Value Turn）：`tickers` → `fetch` → `calendar` → `analyze` → `docs` → `review`（モデルやプロンプトを変えたら先に `review-eval`）→ `backup`。`evaluate` は随時
- Tailwind Watch：
  1. `profiles`：全上場企業の有価証券報告書の節を文書ストアへ。全社で数時間かかる見込み（EDINET の間隔 0.5 秒）[推論]。年 1 回＋月 1 回の差分
  2. `flow-memo --name "…" --demand "…" [--url …]`：流れの調査メモ（`results/flows/`）。`profiles` が無いと案内して終了コード 1
  3. `flow-decide --flow <ID> --ticker <コード> --action buy|skip --reason "…" [--max-yen N]`
  4. 答え合わせは `evaluate` が判断の 6・12 か月後に行う（比べる相手：同じ業種のまだ上がっていない割安株）

## 3. 未確認・未決（ユーザーが決めるものは明記）

| 項目 | 内容 |
|---|---|
| ライブ確認 | 済み（2026-10-20）。LV14〜16（`profiles`・`flow-memo`・`flow-decide`）を本物の EDINET・検索・LLM で通した。見つかった不具合は修正済み。残る注意：何次の判定は実行ごとに揺れる（メモに注記）、地図は LLM の検索語に左右される（`flow-memo --terms` で人が語を足せる。将来の自動化もここに渡す） |
| 止める基準（ユーザー） | 流れの調査は「買う」が 10 件たまって機械の合図に負けていればやめる、という初期値でよいか。記録を始める前に確定（`tailwind_watch_design.md` 6 章） |
| 調査メモの品質の関門（ユーザー） | 最初の数件のメモを人が採点して正解を作り、`review-eval` と同じ関門にするか |
| 通知・定期実行（ユーザー） | どちらも未設定（ファイルの出力と手動の実行） |
| TDnet の文章 | 閲覧ページは robots.txt で断られている。使うなら J-Quants の TDnet アドオン（有料）か、使わない |

## 4. 次にやること（優先順）

1. 全上場企業の `profiles`（数時間）。今は数社しか文書ストアに入っていないので、地図が実用になるのはこの後
2. ユーザーに止める基準を確定してもらう
3. 数件の判断がたまったら、調査メモの品質の関門を検討する
4. C8 実験（Value Turn の記録が 6 か月たまる 2027 年春以降）

## 5. つまずきやすい点

- **フック**：main の上では編集・コミットできない（ブランチを切る）。別の作業ツリーで作業していても、本体が main の上だとコミットがフックで止まるので `git -C <作業ツリー> commit` を使う。マージは本体（main）で `~/.claude/bin/merge-to-main.sh <branch> <msg-file>`（作業ツリーとブランチも消える）
- **関門**：`scripts/gate.sh` がすべて（ruff・format・mypy・vulture・deptry・pytest・カバレッジ 85%・コード予算）。コードを足したら `pyproject.toml` の `max_source_lines` を実際の行数に上げ、コミットに `Budget-Increase: <理由>` の行。減らしたら下げる（10 行以上ずれると落ちる）
- **設計の関門**（`tests/unit/test_design_docs.py`）：L3 の表の 2 列目のバッククォートの名前は「公開する名前」として src と照合される（注記に名前を書かない）。未実装の E2E・結合テストは strict xfail の仮置きが要り、実装したら外す。単体テストの計画の名前はテストファイルに現れる必要がある
- **設定の関門**：config のキーを読む変数名は `tests/unit/test_architecture.py` の `CONFIG_NAMES` に限られる（例：`cfg`・`flow`）。使われないキーも落ちる
- **vulture**：呼び出し元の無い関数は置けない。部品は呼び出すコマンドと同じブランチで作る
- **文書はスリムに**：今の設計だけ。不採用・失敗は 1 行の学び、履歴は 1 行ずつ（CLAUDE.md）
- **DeepSeek への委譲**（トークンの節約）：`aider --model openai/deepseek-v4-flash --openai-api-base https://api.deepseek.com --openai-api-key "$DEEPSEEK_API_KEY" --yes-always --no-auto-commits --edit-format whole --map-tokens 0 --message-file <指示> <変更するファイル> --read <参照>`。渡すファイルは数個まで（多いと入力の上限で止まるか、何も書かずに終わる）。迷いそうな細部は指示書で先に決める。`.gitignore` に `.aider*` を足すので戻す。**出来たものは必ずゲートを流し、差分を読む**（今回、性能の問題・既存機能の後退・テストの誤りが見つかった）
- **データの注意**：`portfolio_arena` の J-Quants の株価表（〜2026-06-12）は同じ値の重複行と優先株のコードを含む（`select distinct`、末尾 0 のコード）。Yahoo のキャッシュの四半期データは EPS だけ。シェルは zsh（変数にコマンドを入れても単語に分かれない。関数を使う）

## 6. 文書の地図

`CLAUDE.md`（決まり）→ 本書 → `docs/architecture/process.md`（進め方）→ `L1_architecture.md`（要件・構成・E2E）→ L2・L3 → 方針と根拠（`selection_flow.md`、`hypothesis_map.md`、`selection_tuning.md`、`tailwind_watch_design.md`）
