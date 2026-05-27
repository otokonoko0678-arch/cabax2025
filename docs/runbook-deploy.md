# Deploy / Recovery Runbook

最終更新: 2026-05-27

## 必須環境変数（Railway Variables）

| 名前 | 用途 | 必須 |
|------|------|------|
| `DATABASE_URL` | Supabase Postgres 接続文字列（direct connection。pooler だと pg_dump が一部失敗）。未設定だとコードは `sqlite:///./cabax.db` にフォールバックするため、本番では**必ず明示設定** | ✓ |
| `SECRET_KEY` | JWT 署名鍵。未設定だと起動時に RuntimeError。流出時はトークン全失効のため即ローテーション | ✓ |
| `SUPER_ADMIN_KEY` | super-admin 画面の API キー。未設定だと起動時に RuntimeError | ✓ |
| `RESET_DB` | 起動時 DB リセット。テスト時のみ `true`、**本番では未設定または `false`** | – |

- `PORT` は Railway が自動付与（`railway.json` の startCommand が `$PORT` を使う）。手動設定不要。
- **値はこの文書に書かない。** Railway Variables と 1Password にのみ保管。
- コード上の定義箇所: `SECRET_KEY` main.py L31 / `DATABASE_URL` L37 / `RESET_DB` L46 / `SUPER_ADMIN_KEY` L3018。

## デプロイの仕組み

- `main` ブランチは branch protection 済: **CI（`test` ジョブ）が緑でないと PR をマージできない**（strict=false / enforce_admins=false なのでオーナーは緊急時に上書き可）。
- 通常フロー: feature ブランチで実装 → push → PR → CI 緑 → マージ → **Railway が main の HEAD を追従して自動デプロイ**。
- CI（`.github/workflows/ci.yml`）の内容: py3.11 で `py_compile`（構文）+ `alembic upgrade head`（マイグレーション）+ `pytest`（logger/middleware/exception handler/health）。
- 構文エラー入りコードは `py_compile` ステップで CI が赤 → マージ不可（2026-05-27 実証済）。

## ロールバック手順

1. **Railway ダッシュボードを開く** → cabax プロジェクト → Deployments タブ
2. **直前の正常デプロイを特定** — ステータス Success の最新 1 つ前
3. **「Redeploy」/「Rollback」を押下**
4. **復旧確認**

   ```bash
   curl https://web-production-d70f.up.railway.app/health/deep
   ```

   `{"status":"ok","database":"ok"}` / 200 が返れば復旧。

> **未実施の宿題:** 上記ロールバックの**実機演習**（小さな commit をデプロイ→1つ前へ Redeploy→/health/deep で 200 確認）は Railway ダッシュボード操作が要るため未実施。一度本番でない時間帯に通しで試しておくこと。

## 障害時の確認順序

1. **UptimeRobot のアラート内容を確認**（どの監視が落ちたか）
2. **Railway logs を確認**（Web UI または `railway logs`）。構造化 JSON ログなので:
   - `status_code` フィールドで 5xx を抽出
   - `exception` フィールドで stacktrace
   - `request_id` で 1 リクエストを前後まで突合（レスポンスの `X-Request-ID` ヘッダと一致）
3. **`/health/deep` で DB 生死確認**
   - `200`（database: ok）→ アプリ OK。外部要因（ネットワーク / CDN）の可能性
   - `503`（database: fail）→ DB 不達 → 次へ
4. **Supabase 状態確認**
   - https://status.supabase.com
   - プロジェクトが pause していないか（Free は 7日無アクセスで自動停止。日次バックアップ cron がアクセスを兼ねる）
5. **直前デプロイが疑わしければロールバック**（上記手順）

## バックアップ

- 日次自動: `.github/workflows/backup.yml` が UTC 18:30（JST 03:30）に走る（暗号化 dump を Cloudflare R2 へ）。cron は main ブランチでのみ発火。
- 復元手順: `docs/runbook-restore.md`

## 監視

- UptimeRobot が `https://web-production-d70f.up.railway.app/health/deep` を 5 分間隔で監視、2 回連続失敗で `otokonoko0678@gmail.com` に通知。

## 障害連絡フロー

オーナー（otokonoko0678@gmail.com）に Email で自動通知。
店舗運用が止まる類の障害（注文・会計が打てない）は即時ロールバック判断。
