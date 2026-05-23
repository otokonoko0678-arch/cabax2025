# Cabax バックアップ復元 Runbook

最終検証日: 2026-05-23

## 概要

本番 DB（Supabase Postgres）が破損・消失した場合の復元手順。日次自動バックアップが Cloudflare R2 に暗号化されて保存されている前提。

- バックアップ生成: `.github/workflows/backup.yml` （GitHub Actions cron、UTC 18:30 = JST 03:30 毎日）
- 保管場所: R2 バケット `cabax-backups`、`daily/` 14日保持・`weekly/` 60日保持（日曜分のみ昇格）
- 暗号化: age（公開鍵で暗号化、秘密鍵で復号）

## 必要なもの

| 項目 | 入手元 |
|------|--------|
| age 秘密鍵ファイル | ローカル `~/cabax-age.key` または 1Password（バックアップした金庫） |
| R2 認証情報 | Cloudflare R2 → Manage R2 API Tokens で再発行可（Access Key ID / Secret / Endpoint） |
| Supabase の新規プロジェクト or 別 DB | 本番を上書きしないために必須 |
| pg_restore 17 系 | `brew install postgresql@17` （実体は `/opt/homebrew/opt/postgresql@17/bin/pg_restore`、keg-only） |
| rclone | `brew install rclone` |
| age | `brew install age` |

**重要**: 本番 Supabase の接続文字列を直接渡さないこと。誤って `pg_restore --dbname=<本番URL>` を実行すると、本番に追記される/破損する。**必ず別プロジェクトを用意してから作業する**。

## 手順

### 0. 事前準備

- age 秘密鍵が手元にあるか確認（無ければ復号不能、即詰み）。1Password の cabax-age 項目から復元
- rclone config が `~/.config/rclone/rclone.conf` にあるか確認。無ければ R2 認証情報を入れて作成：

  ```ini
  [r2]
  type = s3
  provider = Cloudflare
  access_key_id = <Access Key ID>
  secret_access_key = <Secret Access Key>
  endpoint = <Endpoint URL>
  acl = private
  no_check_bucket = true
  ```

### 1. 対象 dump 特定

```bash
rclone ls r2:cabax-backups/daily/ | sort
```

最新の `cabax-<TS>.dump.age` を控える。事前検証の場合は何でもよい。

### 2. 取得 + 復号

```bash
cd /tmp
rclone copy r2:cabax-backups/daily/cabax-<TS>.dump.age .
age -d -i ~/cabax-age.key -o cabax-restore.dump cabax-<TS>.dump.age
file cabax-restore.dump  # → "PostgreSQL custom database dump" と出れば OK
```

### 3. 復元先 DB の用意

**本番を絶対に上書きしないこと**。以下のどちらか：

- **本番障害からの復旧用**: Supabase ダッシュボードで新規プロジェクトを作成（`cabax-restore-<日付>` 等の名前）→ Database → Connection string（**Direct connection, port 5432**、pooler の 6543 ではない）を取得 → `RESTORE_DATABASE_URL` にセット
- **検証目的のみ**: ローカル postgres 17 を起動して新規 DB を作る：

  ```bash
  brew services start postgresql@17
  until /opt/homebrew/opt/postgresql@17/bin/pg_isready -q; do sleep 1; done
  /opt/homebrew/opt/postgresql@17/bin/psql -d postgres \
    -c "CREATE DATABASE cabax_restore_test;"
  ```
  
  → `RESTORE_DATABASE_URL="postgresql://user@localhost:5432/cabax_restore_test"`

### 4. 復元実行

```bash
/opt/homebrew/opt/postgresql@17/bin/pg_restore \
  --dbname="$RESTORE_DATABASE_URL" \
  --no-owner --no-privileges \
  /tmp/cabax-restore.dump
```

**Supabase 固有の extension エラー（`pg_graphql`/`supabase_vault`）はローカル復元時のみ出る警告**。`pg_restore: 警告: リストア中に無視されたエラー数: N` と出ても exit 0 なら成功。Supabase ⇄ Supabase の復元なら出ない。

### 5. アプリ接続確認

```bash
cd ~/cabax-deploy
source .venv/bin/activate
DATABASE_URL="$RESTORE_DATABASE_URL" \
SECRET_KEY="restore-temp" \
SUPER_ADMIN_KEY="restore-temp" \
uvicorn main:app --host 127.0.0.1 --port 8766
```

別ターミナルで：

```bash
curl http://127.0.0.1:8766/health
# → {"status":"healthy","timestamp":"..."}
```

200 が返れば DB 接続 OK = 復元成功。

ログイン画面（admin.html / order.html）は **本番ユーザーのハッシュ済 PIN/パスワードがそのまま入っている**ため、本番認証情報を知っている人のみログイン可能。これは復元成功の証拠であって失敗ではない。

### 6. 本番切替（本番復旧時のみ）

検証用復元ではなく実際の障害復旧なら、復元先プロジェクトを本番に昇格：

1. Railway → cabax → Variables → `DATABASE_URL` を復元先 Supabase プロジェクトの connection string に差し替え
2. Railway がデプロイ再開 → `/health/deep`（実装後）で DB 接続確認
3. 旧本番プロジェクトはまだ削除しない（戻し用に1週間保持）

### 7. クリーンアップ（検証用復元の場合）

```bash
# uvicorn を Ctrl+C で停止
/opt/homebrew/opt/postgresql@17/bin/psql -d postgres \
  -c "DROP DATABASE cabax_restore_test;"
rm /tmp/cabax-restore.dump /tmp/cabax-<TS>.dump.age
brew services stop postgresql@17
```

検証用に作った Supabase プロジェクトがあれば、Supabase ダッシュボードで削除。

復号後の dump は機密情報（顧客・キャスト本名・売上）を含む。検証完了後は必ず削除する。

## 過去の地雷メモ（2026-05-23 検証時）

- **Supabase は PG 17 に upgrade 済**。pg_dump/pg_restore は 17 系必須。16 だと version mismatch で abort
- **GitHub Actions runner は postgresql-client-16 が pre-installed**。`apt install postgresql-client-17` してもデフォルトの `pg_dump` は 16 を呼ぶ → workflow ではフルパス `/usr/lib/postgresql/17/bin/pg_dump` を使用
- **homebrew の postgresql@17 は keg-only**。`/opt/homebrew/bin/pg_restore` は libpq の方を指してる可能性。フルパス `/opt/homebrew/opt/postgresql@17/bin/pg_restore` を使う
- **rclone は upload 時にバケット存在チェック（CreateBucket 呼び出し）を試みる**。R2 トークンが Object Read & Write のみだと 403 → `no_check_bucket = true` を config に追加
- **R2 endpoint URL は1行に収まっている必要あり**。nano で編集時に画面折り返しを Enter で確定すると改行が入り rclone 設定パースエラー

## 再検証タイミング

- スキーマ変更（alembic migration）を入れた直後
- Supabase の PostgreSQL メジャーバージョンが上がった直後（pg_dump/pg_restore の対応 version 更新が必要）
- 半年以上検証していないとき（鍵紛失や手順陳腐化のリスクを潰すため）

「バックアップがある」と「復元できる」は別物。年単位で復元検証をスキップすると、バックアップがあっても復旧不能になる。
