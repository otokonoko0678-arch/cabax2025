# Cabax 運用安定化パック 設計

**日付**: 2026-05-23
**ステータス**: design
**スコープ**: 安定運用フェーズへの移行に必要な最小工数の改修

## 背景・目的

Cabax は去年（2025年）構築され、現在は pre-launch〜運用開始フェーズ。今後は機能追加・画面改修を頻繁に行わず、**安定運用に入る**方針。

現状の問題：

- `main.py` 3229行に 78 エンドポイントが集約、`admin.html` 11963行（HTML+CSS+JS一体）。構造はモノリシック。
- テスト実質ゼロ（`test_connection.py` のみ）、CI/CD なし。git push → Railway 自動デプロイ。
- ロギング 12 箇所、try/except 19 箇所（78 ルート対比で薄い）。
- Tailwind CDN 依存（`cdn.tailwindcss.com`）。
- Supabase は **Free プラン**。マネージドな自動バックアップは無く、復元できる状態にない。さらに 7日間無アクセスでプロジェクトが自動停止するリスクがある。
- ヘルスチェック `/health` はあるが外部監視なし。また DB の生死を見ていない。

「安定運用」を前提とすると、**構造改修（main.py / admin.html 分割）は不要**。優先すべきは「壊れた時に追える」「壊れたまま本番に上がらない」「データを失わない」基盤の整備。

## 非ゴール

- `main.py` のモジュール分割（routers/models/schemas）
- `admin.html` の分割・SPA化
- 新規機能追加
- パフォーマンス改善
- **ステージング環境の新設** — 最小工数方針のため今回は見送る。CI + 自前バックアップで当面のデプロイ／データリスクはカバーできる。将来運用を厚くする場合、非本番 DB を指す Railway ステージング環境が次の最有力候補（「本番前に実物で検証」できる）であることは記録しておく。

## スコープ（7項目）

### 1. Structured logging

**目的**: 本番障害時に「誰が・どの店舗で・どの API を叩いて・どこでコケたか」を Railway logs から追える状態にする。

**内容**:

- `logging` モジュールで JSON 形式の structured logger を追加（別ファイル `logger.py` 推奨）。
- FastAPI middleware で全リクエストに以下を記録：
  - `timestamp`
  - `request_id`（middleware 入口で発行する UUID。1リクエスト内の全ログ行に付与）
  - `store_id`（トークンから抽出）
  - `user_id`
  - `method` + `path`
  - `status_code`
  - `duration_ms`
- トークンのデコードは middleware 内で行うが、**未認証エンドポイント（ログイン・`/health` 等）や不正トークンで例外を投げないこと**。`store_id` / `user_id` は不明なら `null` で記録する。
- エラー時は `exception` フィールドに stacktrace を含める。
- ログレベル: 通常 INFO、4xx は WARNING、5xx は ERROR。
- Railway logs で `grep store_id=3` のような検索ができる形式に。

**完了条件**: Railway logs で任意の store_id・任意のエンドポイントの呼び出しを grep で抽出でき、かつ 1 リクエストの入口ログとエラーログを `request_id` で突合できる。

### 2. Supabase バックアップ構築（Free プラン対応）

**目的**: Free プランにはマネージドな自動バックアップが無いため、自前でバックアップを構築し、かつ実際に復元できることを検証する。「バックアップがあるつもり」状態の解消ではなく、ゼロからの構築。

**内容**:

- GitHub Actions のスケジュール（cron、日次）で `pg_dump` を実行。schema + data に加え roles / sequences / triggers / RLS ポリシーまで含む形式で取得。
- 出力先: Cloudflare R2（`pullcraft.jp` 等で Cloudflare を利用済みのため追加コスト・学習コスト最小）。Cabax 専用バケットを用意し、世代保持（例: 直近 14 日分 + 週次 4 本）。
- dump は gzip 圧縮し、`age` または `gpg` で暗号化してからアップロード。顧客・キャストの個人情報を含むため、**R2 に平文で置かない**。暗号鍵は Railway / GitHub Secrets とは別管理。
- 復元検証: 別の Supabase プロジェクト（または別 DB）を作成し、最新 dump を流し込む。`cabax-deploy` の `DATABASE_URL` だけ差し替えて接続し、主要画面が表示されることを確認。
- 手順を `docs/runbook-restore.md` に残す（次回障害時に手探りしないため）。復元検証はスキーマ変更のたびに再実施する運用とする（一回きりにしない）。
- 注記: Free プロジェクトは 7 日間無アクセスで自動停止する。項目5の外部監視（5分間隔で `/health` にアクセス）が keep-alive を兼ねるが、監視を唯一の生命線にしないこと（停止時アラートも併せて設定）。

**完了条件**: GitHub Actions が日次で R2 に暗号化済み dump を出力しており、その dump から「復元 → アプリ接続 → 画面表示」まで通ったログ or スクショが `runbook-restore.md` に添付されている。

### 3. try/except 補強 + rollback（主要 API）

**目的**: DB 例外・外部要因による失敗時に、ユーザーには丁寧なメッセージ・ログには詳細を残し、かつ破損したセッションを連鎖させない。

**対象**: 注文系・会計系・delete 系 API（具体的なエンドポイント一覧は実装計画で確定）。

**内容**:

- 汎用処理は FastAPI の **グローバル `exception_handler` に集約**する（78 ルート分の try/except 重複を避け、項目1のロギング middleware と素直に合成するため）。
  - `SQLAlchemyError` ハンドラ: **先頭で必ず `session.rollback()` を実行**する。破損セッションのまま返すと、コネクションプール経由で後続リクエストまで連鎖的に失敗する。その上でログにエラー詳細、ユーザーには 503 と「もう一度お試しください」。
  - `Exception` ハンドラ: ログに stacktrace、ユーザーには 500 と汎用メッセージ。
- 個別 try/except は、業務上のリカバリ挙動（部分コミットの取り消し、リトライ等）が汎用処理と異なる箇所だけに限定する。
- 特に**会計系は 1 トランザクションで commit-or-rollback を担保**し、中途半端なコミットが残らないようにする。

**完了条件**:

- DB を一時的に切断した状態で対象 API を叩くと、500 ではなく 503 + 適切なメッセージが返り、rollback 後の後続リクエストが正常動作する。
- 会計操作を途中で失敗させても、部分的にコミットされた行が残らない（原子性）。
- Railway logs にエラー詳細が `request_id` 付きで残っている。

### 4. GitHub Actions CI（+ 依存ピン留め）

**目的**: 構文エラー・マイグレーション破綻・依存ドリフトを本番デプロイ前に検知する。

**内容**:

- 前提作業: `requirements.txt` のバージョンを固定（`pip freeze` 相当、可能ならハッシュ付き）。固定しないと CI と本番がドリフトし、推移的依存の更新で本番が無言で壊れる。
- `.github/workflows/ci.yml` を新設。push および PR 時にトリガー。
- ジョブ:
  - `pip install -r requirements.txt`
  - 構文チェック: `python -m py_compile $(git ls-files '*.py')`。全 `.py` の構文をコード実行せずに検証する。`python -c "import main"` は import 時に DB 接続・env 読込を実行して flaky になりうるため、`main.py` が import-safe だと確認できた場合のみ追加する。
  - マイグレーション検証: Actions の `services:` で PostgreSQL コンテナを起動し、その実 DB に対して `alembic upgrade head` を実行する。`--sql`（オフラインモード）や SQLite は方言差があり検証にならない。
- デプロイゲート: Railway の GitHub 連携を「push で即デプロイ」から外し、CI 成功時に GitHub Actions から Railway の deploy をトリガーする方式に切り替える（CI 通過を確実な前提にできる）。

**完了条件**: 意図的に `main.py` に構文エラーを入れて push して CI が fail すること、PostgreSQL 非互換のマイグレーションを入れて CI が fail すること、CI が緑のときのみ本番デプロイが走ることを確認。

### 5. Healthcheck 強化 + 外部監視

**目的**: 本番（特に DB）が落ちた時に能動的に気付ける状態にする。

**内容**:

- `/health` を DB まで触る形にする。軽量な `SELECT 1` を実行し、DB 不達なら 503 を返す。現状の「200 を返すだけ」では「アプリは生存・DB は死亡」（項目1・3が扱う障害モード）を検知できない。Railway 自身のヘルスチェックを軽く保ちたい場合は `/health`（浅い）と `/health/deep`（DB 込み）を分離してもよい。
- UptimeRobot 無料枠（または Better Stack / Cronitor 等の代替）で DB 込みエンドポイントを 5 分間隔で監視。
- 連続 2 回失敗で通知発火（瞬断で誤検知しない設定）。
- 通知先: メール（`otokonoko0678@gmail.com`）+ LINE Messaging API のプッシュメッセージ（Product B で実装済みのものを流用）または Slack / Discord Webhook。**LINE Notify は 2025年3月末で終了済みのため使わない。**
- 副次効果: この 5 分間隔の監視は Supabase Free プロジェクトの自動停止（7日無アクセス）に対する keep-alive を兼ねる。

**完了条件**: テストで Railway を一時停止し、設定した通知先に実際にアラートが届く。DB だけを落とした状況でも `/health`(deep) が 503 を返し検知される。

### 6. Tailwind CDN → CLI 化（v3 にピン）

**目的**: `cdn.tailwindcss.com` への外部依存を排除。CDN 停止・遅延・ポリシー変更のリスクを除去。

**内容**:

- `tailwindcss@^3` を **明示的にバージョンピン**して devDependency 導入。
  - ピン無しで `npm install tailwindcss` すると v4（現行 4.3 系）が入る。v4 は `tailwind.config.js` を既定で持たず（設定は CSS の `@theme`）、入力 CSS の書式も CLI パッケージも異なるため、本スペックの手順が成立しない。
  - さらに既存 HTML は CDN 経由で v3 系のクラスを前提に書かれているため、v4 でビルドするとユーティリティ改名で画面が無言で壊れる。v3 ピンでこのリスクも回避する。
- `tailwind.config.js` の `content` に以下を含める:
  - `static/admin.html`
  - `static/order.html`
  - `static/super-admin.html`
- 動的 className の扱い:
  - スキャナは「完全な文字列リテラル」として現れるクラス名は自動で拾う（`admin.html` 内の JS テンプレートリテラルでも、完全な文字列なら検出される）。
  - `` `bg-${color}-500` `` のように実行時に組み立てられるクラスは拾えない。該当するものは `tailwind.config.js` の `safelist` に列挙する。可能なら断片連結でのクラス生成自体を避ける。
- ビルド: `npx tailwindcss -i input.css -o static/css/app.css --minify`。npm script 化して「再ビルド 1 コマンド」にする。
- 各 HTML から `<script src="https://cdn.tailwindcss.com">` を削除し、`<link rel="stylesheet" href="/static/css/app.css">` に置換。
- ビルド成果物 `static/css/app.css` は git 管理に入れる（Railway 側で Node を入れずに済む）。

**完了条件**: HTML から CDN 参照が消え、ローカル CSS のみで全画面の見た目が崩れない（全画面を目視確認）。

### 7. デプロイ Runbook + 環境変数棚卸し

**目的**: CI が捕まえられないロジックバグが本番に出た時、および設定が消失した時に、手探りしない状態にする。

**内容**:

- `docs/runbook-deploy.md` を新設:
  - ロールバック手順: Railway で直前の正常デプロイに戻す操作を 1 ステップで明記。CI は「捕まえられる悪いデプロイ」しか止められず、ロジックバグは本番に届くため。
  - 障害時の確認順序: Railway logs の見方、`/health`(deep) の確認、Supabase ステータスの確認。
- 環境変数の棚卸し: Cabax が必要とする env var の一覧を `runbook-deploy.md` に記載する（**名前のみ。値は書かない**）。設定が Railway 上にしか存在しない状態は、アカウント側の事故で設定ごと失われる。

**完了条件**: `runbook-deploy.md` が存在し、ロールバックを実際に 1 回実行して直前デプロイに戻れることを確認済み。env var 一覧が現行 Railway の設定と一致している。

## 実装順序

「観測性」を先、「復旧不能リスク」を次、「壊れた時に追える／止める」、最後に「壊れにくくする」。

1. Structured logging（最優先・他項目の前提）
2. Supabase バックアップ構築（Free プランは現状バックアップ皆無＝復旧不能リスクが最大）
3. try/except 補強 + rollback
4. GitHub Actions CI（+ 依存ピン留め）
5. Healthcheck 強化 + 外部監視
6. Tailwind CDN → CLI 化
7. デプロイ Runbook + 環境変数棚卸し

## リスクと回避策

| リスク | 回避策 |
|--------|--------|
| logging middleware で全 API にレイテンシ増 | duration_ms 計測のみ。重い処理は入れない |
| try/except 追加で例外を握りつぶしてバグを隠す | `except` 内では必ずログ出力＆500/503 を返す。silent fail 禁止 |
| rollback 漏れで破損セッションがプール経由で連鎖失敗 | `SQLAlchemyError` ハンドラの先頭で必ず rollback。完了条件で後続リクエストの正常動作を検証 |
| Tailwind CLI 化で動的 className が拾えず画面崩れ | safelist に列挙＋ビルド後に全画面を目視確認。v3 ピンで v4 改名リスクも回避 |
| バックアップ復元テストで本番 DB を誤って上書き | 必ず**別 Supabase プロジェクト**に復元。本番接続文字列は触らない |
| R2 に個人情報を平文保存 | dump は暗号化してからアップロード。R2 バケットは非公開設定 |
| Free プロジェクトが 7 日無アクセスで自動停止 | 外部監視の 5 分間隔アクセスが keep-alive を兼ねる。停止時もアラートで検知 |

## テスト戦略

ユニットテストの大量導入はスコープ外（安定運用方針と整合）。検証は以下で行う:

- CI: 構文チェック（py_compile）＋ 実 PostgreSQL に対する alembic マイグレーション
- logging: 本番デプロイ後、Railway logs を request_id・store_id で grep できることを確認
- try/except + rollback: DB 切断シミュレーションで 503・rollback・後続リクエスト正常動作を確認。会計操作の原子性を確認
- バックアップ: dump → 別プロジェクトへ復元 → 画面表示まで実機確認
- Tailwind: 全画面の目視確認
- 監視: Railway 停止・DB 停止の両方で実際にアラート発火を確認
- Runbook: ロールバックを 1 回実行して直前デプロイに戻れることを確認

## 完了の定義

上記 7 項目すべての「完了条件」が満たされ、`docs/runbook-restore.md` と `docs/runbook-deploy.md` が存在し、CI が緑かつ CI 通過時のみ本番デプロイが走り、外部監視からの test alert が届き、GitHub Actions が日次で R2 に暗号化 dump を出力している状態。
