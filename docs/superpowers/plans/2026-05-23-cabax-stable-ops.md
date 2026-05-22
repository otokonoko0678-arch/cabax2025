# Cabax 運用安定化パック 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 安定運用フェーズに必要な「壊れた時に追える / 壊れたまま本番に上がらない / データを失わない」基盤を、構造改修なしで導入する。

**Architecture:** 既存の `main.py` 一枚岩構造を維持したまま、横断関心（observability / error handling / health）を最小モジュールで追加する。ops/infra（CI / backup / 監視 / Tailwind / runbook）は GitHub Actions と外部サービスで実装。

**Tech Stack:** FastAPI 0.104.1 / SQLAlchemy 2.0.23 / Supabase Postgres / Railway / GitHub Actions / Cloudflare R2 / Tailwind v3 / pytest（新規導入） / UptimeRobot

**Source spec:** `docs/superpowers/specs/2026-05-23-cabax-stable-ops-design.md`

---

## ファイル構成（新規・変更）

**新規作成:**
- `logger.py` — structured JSON logger（spec項目1）
- `tests/__init__.py`
- `tests/conftest.py` — FastAPI TestClient fixture
- `tests/test_logger.py`
- `tests/test_middleware_logging.py`
- `tests/test_exception_handlers.py`
- `tests/test_health.py`
- `.github/workflows/ci.yml` — push/PR時テスト（spec項目4）
- `.github/workflows/backup.yml` — 日次pg_dump→R2（spec項目2）
- `tailwind.config.js`
- `input.css`
- `package.json`
- `static/css/app.css`（ビルド成果物、git管理）
- `docs/runbook-restore.md`（spec項目2）
- `docs/runbook-deploy.md`（spec項目7）

**変更:**
- `main.py` — middleware追加（L612-619 CORS の下）、exception_handler追加、`/health` を deep に強化、3229行のうち**新規追加のみ**で既存ルートには触らない
- `requirements.txt` — `pip freeze` の完全ピン版に置換
- `static/admin.html` L7 — CDN→link rel
- `static/order.html` L7 — 同上
- `static/super-admin.html` L7 — 同上
- `.gitignore` — `node_modules/` 追記

---

## Foundation: pytest セットアップ

### Task F1: pytest と httpx をインストールして固定

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: dev依存を追加**

`requirements.txt` の末尾に追加：

```
pytest==8.3.4
httpx==0.27.2
```

- [ ] **Step 2: インストールして固定**

```bash
cd ~/cabax-deploy
source .venv/bin/activate
pip install -r requirements.txt
```

- [ ] **Step 3: 動作確認**

```bash
python -c "import pytest, httpx; print(pytest.__version__, httpx.__version__)"
```

Expected: `8.3.4 0.27.2`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add pytest and httpx for test suite"
```

### Task F2: テストディレクトリと共通fixture

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `pytest.ini`

- [ ] **Step 1: `tests/__init__.py` を空ファイルで作成**

```bash
mkdir -p tests && touch tests/__init__.py
```

- [ ] **Step 2: `pytest.ini` を作成**

```ini
[pytest]
testpaths = tests
addopts = -v --tb=short
```

- [ ] **Step 3: `tests/conftest.py` を作成**

```python
"""共通テスト fixture。テスト用 DB は in-memory SQLite を使い、main.py の DATABASE_URL を上書きする。"""
import os
import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """import 時に main を読み込むことで、上書きした env を確実に拾わせる。

    raise_server_exceptions=False で 5xx を例外として再raiseせず、レスポンスとして返す
    （exception handler の振る舞いをテストするため必須）。
    """
    from main import app, Base, engine
    Base.metadata.create_all(bind=engine)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    Base.metadata.drop_all(bind=engine)
```

- [ ] **Step 4: スモーク確認**

```bash
pytest tests/ -v
```

Expected: `no tests ran` または `collected 0 items`（テストファイル未作成、エラー無し）

- [ ] **Step 5: Commit**

```bash
git add tests/ pytest.ini
git commit -m "chore: add pytest config and test fixtures"
```

---

## Task Group 1: Structured logging（spec項目1）

### Task 1.1: logger.py — JSON formatter のテスト

**Files:**
- Create: `tests/test_logger.py`

- [ ] **Step 1: 失敗テストを書く**

```python
import json
import logging
from logger import get_logger, JSONFormatter


def test_json_formatter_emits_required_fields(caplog):
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="cabax", level=logging.INFO, pathname="x", lineno=1,
        msg="hello", args=(), exc_info=None
    )
    record.request_id = "abc-123"
    record.store_id = 7
    record.user_id = 42
    record.method = "GET"
    record.path = "/api/casts"
    record.status_code = 200
    record.duration_ms = 12.5

    output = formatter.format(record)
    parsed = json.loads(output)

    assert parsed["request_id"] == "abc-123"
    assert parsed["store_id"] == 7
    assert parsed["user_id"] == 42
    assert parsed["method"] == "GET"
    assert parsed["path"] == "/api/casts"
    assert parsed["status_code"] == 200
    assert parsed["duration_ms"] == 12.5
    assert parsed["level"] == "INFO"
    assert "timestamp" in parsed


def test_json_formatter_handles_missing_optional_fields():
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="cabax", level=logging.INFO, pathname="x", lineno=1,
        msg="hello", args=(), exc_info=None
    )
    output = formatter.format(record)
    parsed = json.loads(output)

    assert parsed["store_id"] is None
    assert parsed["user_id"] is None
    assert parsed["request_id"] is None


def test_json_formatter_includes_exception_on_error(caplog):
    formatter = JSONFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        record = logging.LogRecord(
            name="cabax", level=logging.ERROR, pathname="x", lineno=1,
            msg="failed", args=(), exc_info=sys.exc_info()
        )

    output = formatter.format(record)
    parsed = json.loads(output)
    assert "exception" in parsed
    assert "ValueError: boom" in parsed["exception"]
```

- [ ] **Step 2: 失敗確認**

```bash
pytest tests/test_logger.py -v
```

Expected: `ModuleNotFoundError: No module named 'logger'`

### Task 1.2: logger.py の実装

**Files:**
- Create: `logger.py`

- [ ] **Step 1: 最小実装**

```python
"""Structured JSON logger for Cabax.

Railway logs 上で `grep store_id=3` のような検索ができるよう、
1リクエスト 1行 の JSON を stdout に出す。
"""
import json
import logging
import sys
import traceback
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    OPTIONAL_FIELDS = (
        "request_id",
        "store_id",
        "user_id",
        "method",
        "path",
        "status_code",
        "duration_ms",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        for field in self.OPTIONAL_FIELDS:
            payload[field] = getattr(record, field, None)
        if record.exc_info:
            payload["exception"] = "".join(traceback.format_exception(*record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def get_logger(name: str = "cabax") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
```

- [ ] **Step 2: テストPass確認**

```bash
pytest tests/test_logger.py -v
```

Expected: `3 passed`

- [ ] **Step 3: Commit**

```bash
git add logger.py tests/test_logger.py
git commit -m "feat: add structured JSON logger"
```

### Task 1.3: logging middleware のテスト

**Files:**
- Create: `tests/test_middleware_logging.py`

- [ ] **Step 1: 失敗テストを書く**

```python
"""logging middleware の振る舞いをテストする。

ポイント:
- request_id がレスポンスヘッダ X-Request-ID で返る
- store_id をトークンから抽出する
- 未認証エンドポイントでも middleware が例外を投げない
- duration_ms が記録される

caplog は LogRecord を直接保持する。フォーマット済み JSON 文字列ではなく、
`record.request_id` 等の extra で渡した属性を直接見る。
"""
import logging


def _cabax_records(caplog):
    return [r for r in caplog.records if r.name == "cabax"]


def test_middleware_emits_log_with_request_id(client, caplog):
    caplog.set_level(logging.INFO, logger="cabax")
    response = client.get("/health")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers

    rid = response.headers["X-Request-ID"]
    matching = [
        r for r in _cabax_records(caplog)
        if getattr(r, "request_id", None) == rid
    ]
    assert matching, "request_id を持つログ行が見つからない"
    r = matching[0]
    assert r.path == "/health"
    assert r.method == "GET"
    assert r.status_code == 200
    assert isinstance(r.duration_ms, (int, float))


def test_middleware_handles_unauthenticated_endpoint_without_error(client, caplog):
    caplog.set_level(logging.INFO, logger="cabax")
    response = client.get("/health")
    assert response.status_code == 200
    records = _cabax_records(caplog)
    assert any(
        getattr(r, "store_id", None) is None and getattr(r, "user_id", None) is None
        for r in records
    )


def test_middleware_handles_invalid_token_without_500(client, caplog):
    caplog.set_level(logging.INFO, logger="cabax")
    response = client.get(
        "/api/casts",
        headers={"Authorization": "Bearer garbage.token.value"},
    )
    # 不正トークンは middleware では捌かず、ルートの verify_token で 401/403 になる
    assert response.status_code in (401, 403)
    records = _cabax_records(caplog)
    assert any(getattr(r, "store_id", None) is None for r in records)


def test_5xx_logged_as_error(client, caplog):
    """exception handler 未導入の段階では、middleware の finally 節で
    status_code=500 として ERROR ログを残せていれば OK。"""
    caplog.set_level(logging.INFO, logger="cabax")
    from main import app

    @app.get("/__force_500__")
    def boom():
        raise RuntimeError("intentional")

    response = client.get("/__force_500__")
    # raise_server_exceptions=False のため、5xx は例外で再raiseされず response として返る
    assert response.status_code == 500
    error_records = [r for r in _cabax_records(caplog) if r.levelno >= logging.ERROR]
    assert error_records, "5xx は ERROR レベルで記録されるべき"
```

- [ ] **Step 2: 失敗確認**

```bash
pytest tests/test_middleware_logging.py -v
```

Expected: 全テスト FAIL（middleware 未実装）

### Task 1.4: logging middleware の実装

**Files:**
- Modify: `main.py` — L619 の CORSMiddleware ブロックの直後（L620 以降に挿入）

- [ ] **Step 1: import を追加**

`main.py` 冒頭の import 群（L7〜L24 あたり）の末尾に追加：

```python
import time
import uuid
from logger import get_logger
```

- [ ] **Step 2: middleware を追加**

`main.py` で `app.add_middleware(CORSMiddleware, ...)` ブロック（L613-619）の**直後**に以下を挿入：

```python
log = get_logger("cabax")


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id

    store_id = None
    user_id = None
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        try:
            payload = jwt.decode(auth.split(" ", 1)[1], SECRET_KEY, algorithms=[ALGORITHM])
            store_id = payload.get("store_id")
            user_id = payload.get("sub") or payload.get("user_id")
        except Exception:
            pass  # 不正トークンは middleware では無視。認証は各ルートで弾く

    start = time.perf_counter()
    status_code = 500
    exception = None
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
    except Exception as e:
        exception = e
        raise
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        if status_code >= 500 or exception is not None:
            level = logging.ERROR
        elif status_code >= 400:
            level = logging.WARNING
        else:
            level = logging.INFO
        log.log(
            level,
            "request",
            extra={
                "request_id": request_id,
                "store_id": store_id,
                "user_id": user_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": duration_ms,
            },
            exc_info=exception is not None and (type(exception), exception, exception.__traceback__),
        )

    return response
```

`logging` import を冒頭に追加：

```python
import logging
```

- [ ] **Step 3: テストPass確認**

```bash
pytest tests/test_middleware_logging.py -v
```

Expected: `4 passed`

- [ ] **Step 4: 既存ルートが壊れていないか確認**

```bash
pytest tests/ -v
```

Expected: 全 passed

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_middleware_logging.py
git commit -m "feat: add structured logging middleware with request_id"
```

---

## Task Group 2: Supabase バックアップ自前構築（spec項目2）

> **このグループはほぼ ops 作業のため TDD ではなく実機検証で進める。**

### Task 2.1: Cloudflare R2 バケット作成

**外部作業（Cloudflare ダッシュボード）:**

- [ ] **Step 1: R2 バケット作成**

Cloudflare ダッシュボード → R2 → Create Bucket:
- Name: `cabax-backups`
- Location hint: `Asia-Pacific (APAC)`

- [ ] **Step 2: API トークン発行**

R2 → Manage R2 API Tokens → Create API Token:
- Permission: `Object Read & Write`
- Specify bucket: `cabax-backups`
- TTL: なし

発行された Access Key ID / Secret Access Key / Endpoint URL（例: `https://<account>.r2.cloudflarestorage.com`）を **GitHub Secrets に保管**（次タスク）。

- [ ] **Step 3: ライフサイクルルール設定**

R2 バケット → Settings → Object lifecycle rules:
- Rule 1: `prefix: daily/` → Delete after 14 days
- Rule 2: `prefix: weekly/` → Delete after 60 days

### Task 2.2: 暗号化鍵の生成

- [ ] **Step 1: age key を生成**

```bash
brew install age
age-keygen -o ~/cabax-age.key
cat ~/cabax-age.key
```

公開鍵（`# public key: age1...` 行）と秘密鍵（`AGE-SECRET-KEY-1...` 行）を控える。

- [ ] **Step 2: 鍵管理**

- 公開鍵（age1...）: GitHub Secrets `BACKUP_AGE_PUBLIC_KEY` に登録（バックアップ暗号化に使う）
- 秘密鍵（AGE-SECRET-KEY-1...）: **GitHub Secrets には絶対に置かない**。1Password などローカル金庫に保管。復元時のみローカルで使う

### Task 2.3: GitHub Secrets を登録

- [ ] **Step 1: リポジトリ Settings → Secrets and variables → Actions**

以下を登録：
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_ENDPOINT_URL`
- `R2_BUCKET` = `cabax-backups`
- `BACKUP_AGE_PUBLIC_KEY` = `age1...`
- `DATABASE_URL` = 本番 Supabase の接続文字列（pooler ではなく direct connection の方を使う。`pg_dump` は pooler 経由だと一部失敗する）

### Task 2.4: backup.yml ワークフロー

**Files:**
- Create: `.github/workflows/backup.yml`

- [ ] **Step 1: ワークフロー作成**

```yaml
name: Daily DB Backup

on:
  schedule:
    - cron: "30 18 * * *"  # 03:30 JST
  workflow_dispatch:

jobs:
  backup:
    runs-on: ubuntu-latest
    steps:
      - name: Install pg_dump (matching Supabase version)
        run: |
          sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
          wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -
          sudo apt-get update
          sudo apt-get install -y postgresql-client-15

      - name: Install age
        run: |
          curl -L https://github.com/FiloSottile/age/releases/download/v1.2.0/age-v1.2.0-linux-amd64.tar.gz | tar xz
          sudo mv age/age /usr/local/bin/

      - name: Install rclone
        run: |
          curl https://rclone.org/install.sh | sudo bash

      - name: Dump database
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
        run: |
          TS=$(date -u +%Y%m%dT%H%M%SZ)
          echo "TS=$TS" >> $GITHUB_ENV
          pg_dump "$DATABASE_URL" \
            --no-owner --no-privileges \
            --format=custom \
            --file="cabax-$TS.dump"
          ls -lh "cabax-$TS.dump"

      - name: Encrypt dump
        env:
          AGE_PUBKEY: ${{ secrets.BACKUP_AGE_PUBLIC_KEY }}
        run: |
          age -r "$AGE_PUBKEY" -o "cabax-${TS}.dump.age" "cabax-${TS}.dump"
          rm "cabax-${TS}.dump"
          ls -lh "cabax-${TS}.dump.age"

      - name: Configure rclone
        env:
          R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
          R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
          R2_ENDPOINT_URL: ${{ secrets.R2_ENDPOINT_URL }}
        run: |
          mkdir -p ~/.config/rclone
          cat > ~/.config/rclone/rclone.conf <<EOF
          [r2]
          type = s3
          provider = Cloudflare
          access_key_id = ${R2_ACCESS_KEY_ID}
          secret_access_key = ${R2_SECRET_ACCESS_KEY}
          endpoint = ${R2_ENDPOINT_URL}
          acl = private
          EOF

      - name: Upload to R2 (daily)
        env:
          R2_BUCKET: ${{ secrets.R2_BUCKET }}
        run: |
          rclone copy "cabax-${TS}.dump.age" "r2:${R2_BUCKET}/daily/"

      - name: Promote to weekly on Sundays (UTC)
        if: github.event_name == 'schedule'
        env:
          R2_BUCKET: ${{ secrets.R2_BUCKET }}
        run: |
          DOW=$(date -u +%u)
          if [ "$DOW" = "7" ]; then
            rclone copy "cabax-${TS}.dump.age" "r2:${R2_BUCKET}/weekly/"
          fi
```

- [ ] **Step 2: ローカル commit**

```bash
git add .github/workflows/backup.yml
git commit -m "ci: add daily encrypted DB backup to Cloudflare R2"
git push
```

- [ ] **Step 3: 手動実行**

GitHub → Actions → "Daily DB Backup" → Run workflow → main ブランチを選択して実行。

- [ ] **Step 4: 成功確認**

- Actions ログで全ステップ green
- Cloudflare R2 → `cabax-backups/daily/` に `cabax-YYYYMMDDTHHMMSSZ.dump.age` が存在
- ファイルサイズが 0 ではない

### Task 2.5: 復元検証 + runbook 作成

**Files:**
- Create: `docs/runbook-restore.md`

- [ ] **Step 1: 別 Supabase プロジェクトを作成**

Supabase ダッシュボード → New project:
- Name: `cabax-restore-test`
- Region: 本番と同じ
- Plan: Free でよい（検証目的）

新プロジェクトの connection string（direct, not pooler）を控える。

- [ ] **Step 2: R2 から dump を取得し復号**

```bash
cd /tmp
rclone copy r2:cabax-backups/daily/cabax-LATEST.dump.age .  # LATESTは最新のタイムスタンプに置換
age -d -i ~/cabax-age.key -o cabax-restore.dump cabax-LATEST.dump.age
ls -lh cabax-restore.dump
```

- [ ] **Step 3: 新プロジェクトに復元**

```bash
pg_restore \
  --dbname="<新プロジェクトの connection string>" \
  --no-owner --no-privileges \
  --verbose \
  cabax-restore.dump
```

- [ ] **Step 4: cabax-deploy をローカルで復元先 DB に向けて起動**

```bash
cd ~/cabax-deploy
DATABASE_URL="<新プロジェクトの connection string>" \
SECRET_KEY="dummy-for-restore-test" \
uvicorn main:app --host 0.0.0.0 --port 8001
```

別ターミナルで:

```bash
curl http://localhost:8001/health
open http://localhost:8001/static/admin.html
```

ログイン画面が表示されることを確認。ログインまで通れば理想。

- [ ] **Step 5: 新プロジェクトを削除**（本番費用と混在させない）

Supabase → cabax-restore-test → Settings → Delete project

- [ ] **Step 6: runbook 作成**

```markdown
# Restore Runbook

最終検証: 2026-05-23（実装時）

## 前提
- R2 バケット: `cabax-backups`
- 暗号化鍵: ローカル `~/cabax-age.key`
- pg_dump/pg_restore 15+ が必要

## 手順

1. **対象 dump 特定**

   ```bash
   rclone ls r2:cabax-backups/daily/ | sort
   ```

2. **取得 + 復号**

   ```bash
   cd /tmp
   rclone copy r2:cabax-backups/daily/<file>.dump.age .
   age -d -i ~/cabax-age.key -o cabax-restore.dump <file>.dump.age
   ```

3. **復元先 DB 用意**

   本番 DB を上書きしないこと。必ず新規 Supabase プロジェクトか別 DB を作る。

4. **復元実行**

   ```bash
   pg_restore --dbname="<restore_target>" --no-owner --no-privileges --verbose cabax-restore.dump
   ```

5. **アプリ接続確認**

   ```bash
   DATABASE_URL="<restore_target>" SECRET_KEY=dummy uvicorn main:app --port 8001
   curl http://localhost:8001/health/deep
   ```

   `/health/deep` が 200 を返せば DB 接続 OK。

## 注意

- スキーマ変更（alembic migration）を入れた直後は、この runbook の検証を再実行する。
- 復元後の `cabax-restore.dump` は機密情報を含む。検証完了後は `shred -u cabax-restore.dump`。
```

- [ ] **Step 7: Commit**

```bash
git add docs/runbook-restore.md
git commit -m "docs: add backup restore runbook with verified procedure"
```

---

## Task Group 3: グローバル exception_handler + rollback（spec項目3）

### Task 3.1: SQLAlchemyError ハンドラのテスト

**Files:**
- Create: `tests/test_exception_handlers.py`

- [ ] **Step 1: 失敗テストを書く**

```python
"""グローバル exception handler のテスト。

ポイント:
- SQLAlchemyError → 503
- get_db() の except 節で rollback が呼ばれる（連鎖失敗防止）
- 一般 Exception → 500
- HTTPException はハンドラを通さずステータスを尊重
"""
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException


def test_sqlalchemy_error_returns_503(client):
    from main import app

    @app.get("/__force_db_error__")
    def force():
        raise SQLAlchemyError("simulated outage")

    response = client.get("/__force_db_error__")
    assert response.status_code == 503
    body = response.json()
    assert "もう一度" in body["detail"]
    assert "request_id" in body


def test_get_db_rolls_back_on_sqlalchemy_error(client):
    """get_db() の except 節で rollback が呼ばれることを直接検証する。

    main.py の get_db() がジェネレータなので、yield 後に SQLAlchemyError を
    `throw()` で投入し、rollback が呼ばれることを確認する。
    """
    from unittest.mock import MagicMock, patch
    from main import get_db

    fake_session = MagicMock()
    with patch("main.SessionLocal", return_value=fake_session):
        gen = get_db()
        next(gen)  # yield まで進める
        try:
            gen.throw(SQLAlchemyError("boom"))
        except SQLAlchemyError:
            pass
        fake_session.rollback.assert_called_once()
        fake_session.close.assert_called_once()


def test_generic_exception_returns_500(client):
    from main import app

    @app.get("/__force_runtime__")
    def boom():
        raise RuntimeError("intentional")

    response = client.get("/__force_runtime__")
    assert response.status_code == 500
    assert "request_id" in response.json()


def test_http_exception_passes_through(client):
    from main import app

    @app.get("/__not_found__")
    def nf():
        raise HTTPException(status_code=404, detail="missing")

    response = client.get("/__not_found__")
    assert response.status_code == 404
    assert response.json()["detail"] == "missing"
```

- [ ] **Step 2: 失敗確認**

```bash
pytest tests/test_exception_handlers.py -v
```

Expected: 全 FAIL（handler 未実装、500 のまま返る）

### Task 3.2: get_db の rollback 確実化 + ハンドラ実装

**Files:**
- Modify: `main.py` — L583-588 の `get_db()`
- Modify: `main.py` — middleware 追加箇所の直後

- [ ] **Step 1: import 追加**

`main.py` 冒頭に：

```python
from sqlalchemy.exc import SQLAlchemyError
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
```

- [ ] **Step 2: `get_db()` を rollback 込みに置換**

`main.py` L583-588 を以下に置換：

```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    except SQLAlchemyError:
        db.rollback()
        raise
    finally:
        db.close()
```

- [ ] **Step 3: グローバル exception handler を追加**

`main.py` の logging middleware の**直後**に追加：

```python
@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    request_id = getattr(request.state, "request_id", None)
    log.error(
        "sqlalchemy_error",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
        },
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=503,
        content={
            "detail": "データベースが一時的に不調です。もう一度お試しください。",
            "request_id": request_id,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # HTTPException は FastAPI が先に拾うのでここには来ない
    request_id = getattr(request.state, "request_id", None)
    log.error(
        "unhandled_exception",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
        },
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "サーバー内部エラーが発生しました。",
            "request_id": request_id,
        },
    )
```

- [ ] **Step 4: テストPass確認**

```bash
pytest tests/test_exception_handlers.py -v
```

Expected: `4 passed`

- [ ] **Step 5: 既存テストが壊れていないか**

```bash
pytest tests/ -v
```

Expected: 全 passed

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_exception_handlers.py
git commit -m "feat: add global exception handlers with mandatory rollback"
```

### Task 3.3: 会計系トランザクションの原子性監査

**Files:**
- Modify: `main.py` — checkout / billing 系 API のうち、複数 commit を分けているものを 1 トランザクションにまとめる

- [ ] **Step 1: 会計系 API を特定**

```bash
cd ~/cabax-deploy
grep -n "checkout\|payment\|会計\|お会計\|charge" main.py | head -40
```

- [ ] **Step 2: 各エンドポイント内の `db.commit()` 出現回数を確認**

```bash
awk '/^@app\.(post|put|delete)/{name=$0} /db\.commit/{print name; print "  L"NR": "$0}' main.py | grep -A1 -i "checkout\|payment\|charge"
```

- [ ] **Step 3: 中間 commit を排除**

会計系ルート（特に checkout / payment / charge を含むもの）で `db.commit()` が**ループ内**または**複数回**現れているものを抽出し、関数の**最後にだけ** `db.commit()` が来るように修正する。途中の `db.flush()` は許容。

例（仮）:

```python
# Before:
for order in orders:
    order.status = "paid"
    db.commit()                    # ← 途中commit
session.checkout_time = now
db.commit()

# After:
for order in orders:
    order.status = "paid"
db.flush()                         # 必要なら
session.checkout_time = now
db.commit()                        # 終端で1回だけ
```

修正対象は実装時にコードを読みながら特定する。修正が不要だった場合（既に終端 commit のみ）はその旨を commit メッセージに残す。

- [ ] **Step 4: 動作確認**

```bash
pytest tests/ -v
```

Expected: 既存テスト全 passed

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "fix: ensure checkout/payment routes commit atomically"
```

---

## Task Group 4: GitHub Actions CI + 依存ピン（spec項目4）

### Task 4.1: requirements.txt の完全ピン

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: 現環境を freeze**

```bash
cd ~/cabax-deploy
source .venv/bin/activate
pip freeze > requirements.full.txt
cat requirements.full.txt
```

- [ ] **Step 2: 内容を確認して置換**

`requirements.full.txt` には推移的依存も全部入る。これを `requirements.txt` に上書き。

```bash
mv requirements.full.txt requirements.txt
```

- [ ] **Step 3: クリーン環境で再現性検証**

```bash
python -m venv /tmp/verify-pin && source /tmp/verify-pin/bin/activate
pip install -r requirements.txt
python -c "import main"  # SECRET_KEY などが必要なら適宜 env 指定
deactivate && rm -rf /tmp/verify-pin
```

- [ ] **Step 4: Commit**

```bash
source ~/cabax-deploy/.venv/bin/activate
git add requirements.txt
git commit -m "chore: pin all dependencies including transitive"
```

### Task 4.2: CI ワークフロー

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: ワークフロー作成**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_USER: cabax
          POSTGRES_PASSWORD: cabax
          POSTGRES_DB: cabax_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    env:
      DATABASE_URL: postgresql+psycopg2://cabax:cabax@localhost:5432/cabax_test
      SECRET_KEY: ci-test-secret-key
      SUPER_ADMIN_KEY: ci-test-super-admin

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Syntax check (py_compile)
        run: |
          python -m py_compile $(git ls-files '*.py')

      - name: Alembic migration check
        run: |
          alembic upgrade head

      - name: Run pytest
        run: |
          pytest tests/ -v
```

- [ ] **Step 2: Commit + push**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions workflow with syntax/migration/test checks"
git push
```

- [ ] **Step 3: CI が緑になることを確認**

GitHub → Actions タブで初回実行が緑。fail した場合は alembic/env.py の env 解決周りやテスト fixture を調整。

### Task 4.3: 構文エラーで CI が落ちることを確認

- [ ] **Step 1: わざと壊す**

```bash
git checkout -b test-ci-failure
echo "def broken(:" >> main.py
git add main.py
git commit -m "test: intentional syntax error"
git push -u origin test-ci-failure
```

- [ ] **Step 2: CI が fail することを GitHub Actions で確認**

PR を作って Actions の `py_compile` ステップで fail することを目視。

- [ ] **Step 3: ブランチを破棄**

```bash
git checkout main
git branch -D test-ci-failure
git push origin --delete test-ci-failure
```

### Task 4.4: Railway デプロイゲート切り替え

**外部作業（Railway ダッシュボード）:**

- [ ] **Step 1: Railway の自動デプロイ設定を確認**

Railway → cabax プロジェクト → Settings → Source → Branch Triggers。

- [ ] **Step 2: GitHub の Required Status Check を有効化**

GitHub → リポジトリ → Settings → Branches → Branch protection rules → main:
- Require status checks to pass before merging: ✓
- Status checks: `test`（CI ジョブ名）

これにより main ブランチへの push は CI 通過が必須になる（Railway は main の HEAD を見るので、間接的に CI 通過後のみデプロイされる）。

- [ ] **Step 3: 動作確認**

意図的に CI で落ちる PR を作り、main にマージできないことを確認 → ブランチ破棄。

---

## Task Group 5: Healthcheck 強化 + 外部監視（spec項目5）

### Task 5.1: /health/deep のテスト

**Files:**
- Create: `tests/test_health.py`

- [ ] **Step 1: 失敗テストを書く**

```python
"""ヘルスチェックの分離テスト。

/health は浅い（プロセス生存のみ）、/health/deep は DB 込み。
"""
from unittest.mock import patch
from sqlalchemy.exc import OperationalError


def test_health_shallow_returns_200(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_health_deep_returns_200_when_db_reachable(client):
    response = client.get("/health/deep")
    assert response.status_code == 200
    body = response.json()
    assert body.get("database") == "ok"


def test_health_deep_returns_503_when_db_unreachable(client):
    from main import app, get_db

    def failing_db():
        raise OperationalError("conn", "params", Exception("simulated"))
        yield  # never reached

    original = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = failing_db
    try:
        response = client.get("/health/deep")
        assert response.status_code == 503
    finally:
        if original:
            app.dependency_overrides[get_db] = original
        else:
            app.dependency_overrides.pop(get_db, None)
```

- [ ] **Step 2: 失敗確認**

```bash
pytest tests/test_health.py -v
```

Expected: `test_health_deep_*` が FAIL（/health/deep 未実装）。

### Task 5.2: /health/deep の実装

**Files:**
- Modify: `main.py` — 既存 `/health` 付近

- [ ] **Step 1: 既存 `/health` の位置を確認**

```bash
grep -n "@app.get(\"/health\"" main.py
```

- [ ] **Step 2: 直後に `/health/deep` を追加**

```python
@app.get("/health/deep")
def health_deep(db: Session = Depends(get_db)):
    from sqlalchemy import text
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}
    except Exception as e:
        log.error("health_deep_db_fail", extra={"error": str(e)})
        return JSONResponse(status_code=503, content={"status": "fail", "database": "fail"})
```

- [ ] **Step 3: テストPass確認**

```bash
pytest tests/test_health.py -v
```

Expected: `3 passed`

- [ ] **Step 4: Commit**

```bash
git add main.py tests/test_health.py
git commit -m "feat: add /health/deep with DB check"
```

### Task 5.3: UptimeRobot 設定

**外部作業（UptimeRobot ダッシュボード）:**

- [ ] **Step 1: アカウント準備**

uptimerobot.com で無料アカウント作成（既存なら流用）。

- [ ] **Step 2: モニター作成**

New Monitor:
- Type: HTTP(s)
- Friendly Name: `Cabax /health/deep`
- URL: `https://web-production-d70f.up.railway.app/health/deep`
- Monitoring Interval: 5 minutes
- Monitor Timeout: 30 seconds
- HTTP Method: GET
- Expected Status Codes: 200

- [ ] **Step 3: アラート連絡先**

Notification Settings:
- Email: `otokonoko0678@gmail.com`
- 連続失敗回数: 2

LINE / Discord も使うなら Webhook で追加（任意）。

- [ ] **Step 4: アラート発火確認**

```bash
# Railway ダッシュボードで cabax サービスを一時 stop
# → 10分以内に email が届くことを確認
# → 確認後 restart
```

---

## Task Group 6: Tailwind CDN → CLI 化（spec項目6）

### Task 6.1: Node 環境と Tailwind v3 のインストール

**Files:**
- Create: `package.json`
- Modify: `.gitignore`

- [ ] **Step 1: package.json 作成**

```json
{
  "name": "cabax-static",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "build:css": "tailwindcss -i ./input.css -o ./static/css/app.css --minify",
    "watch:css": "tailwindcss -i ./input.css -o ./static/css/app.css --watch"
  },
  "devDependencies": {
    "tailwindcss": "^3.4.17"
  }
}
```

- [ ] **Step 2: インストール**

```bash
cd ~/cabax-deploy
npm install
ls node_modules/tailwindcss/package.json
node -e "console.log(require('./node_modules/tailwindcss/package.json').version)"
```

Expected: `3.4.x`

- [ ] **Step 3: .gitignore に node_modules 追加**

`.gitignore`（無ければ作る）に追加：

```
node_modules/
```

- [ ] **Step 4: Commit**

```bash
git add package.json .gitignore
git commit -m "chore: add tailwind v3 dev dependency"
```

### Task 6.2: tailwind.config.js と input.css

**Files:**
- Create: `tailwind.config.js`
- Create: `input.css`

- [ ] **Step 1: 動的 className の調査**

```bash
cd ~/cabax-deploy
grep -nE 'className.*\$\{|class.*\$\{|\\\`(bg|text|border)-' static/*.html | head -40
```

完全な文字列リテラル（例: `'bg-red-500'`）は自動検出される。連結（例: `` `bg-${color}-500` ``）は safelist に入れる必要あり。出力を見てパターンを抽出。

- [ ] **Step 2: tailwind.config.js を作成**

```javascript
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./static/admin.html",
    "./static/order.html",
    "./static/super-admin.html",
  ],
  safelist: [
    // 動的に組み立てられるクラス（Step 1 の調査結果に応じて埋める）
    // 例: { pattern: /bg-(red|green|blue|yellow|gray)-(100|200|300|400|500|600|700)/ },
    // 例: { pattern: /text-(red|green|blue|yellow|gray)-(500|600|700|800)/ },
    // 調査で見つかった具体的なパターンに置換すること。空でも CSS は出るが画面が崩れる。
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
```

- [ ] **Step 3: input.css 作成**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 4: 初回ビルド**

```bash
mkdir -p static/css
npm run build:css
ls -lh static/css/app.css
```

Expected: `app.css` が数十〜数百 KB で生成される。

### Task 6.3: HTML から CDN 参照を置換

**Files:**
- Modify: `static/admin.html` L7
- Modify: `static/order.html` L7
- Modify: `static/super-admin.html` L7

- [ ] **Step 1: 3 ファイルとも置換**

各ファイル L7 の以下：

```html
<script src="https://cdn.tailwindcss.com"></script>
```

を以下に置換：

```html
<link rel="stylesheet" href="/static/css/app.css">
```

- [ ] **Step 2: ローカルで起動して目視確認**

```bash
cd ~/cabax-deploy
source .venv/bin/activate
DATABASE_URL=sqlite:///./cabax.db SECRET_KEY=test uvicorn main:app --port 8002
```

ブラウザで以下を開き、見た目が崩れていないか確認：
- `http://localhost:8002/static/admin.html`
- `http://localhost:8002/static/order.html`
- `http://localhost:8002/static/super-admin.html`

崩れている箇所があれば、`tailwind.config.js` の `safelist` にクラスを追加 → `npm run build:css` → 再確認。

- [ ] **Step 3: 全画面の主要操作を踏む**

admin: ダッシュボード / キャスト一覧 / メニュー / 出勤 / 経費 タブを切り替えて崩れがないか
order: テーブル選択 / 注文入力 / 会計 の主要フロー

- [ ] **Step 4: Commit**

```bash
git add tailwind.config.js input.css static/css/app.css static/admin.html static/order.html static/super-admin.html
git commit -m "feat: replace Tailwind CDN with local CLI build (v3)"
```

### Task 6.4: ビルド成果物を CI に組み込む

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: CI に Tailwind ビルド step を追加**

`.github/workflows/ci.yml` の `Run pytest` の直前に追加：

```yaml
      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm

      - name: Install npm deps
        run: npm ci

      - name: Build CSS
        run: npm run build:css

      - name: Verify CSS is committed (no drift)
        run: |
          if ! git diff --quiet static/css/app.css; then
            echo "static/css/app.css is out of sync. Run 'npm run build:css' and commit."
            git diff static/css/app.css | head -50
            exit 1
          fi
```

これでビルド成果物の commit 漏れを CI が検知。

- [ ] **Step 2: package-lock.json も commit**

```bash
git add package-lock.json .github/workflows/ci.yml
git commit -m "ci: verify Tailwind build output is in sync"
git push
```

---

## Task Group 7: Runbook + 環境変数棚卸し（spec項目7）

### Task 7.1: 環境変数の棚卸し

**Files:**
- Create: `docs/runbook-deploy.md`

- [ ] **Step 1: コードから env var を抽出**

```bash
cd ~/cabax-deploy
grep -hE "os\.getenv|os\.environ" main.py logger.py 2>/dev/null | sort -u
```

- [ ] **Step 2: Railway の現行 Variables と突合**

Railway → cabax → Variables を開き、上記コードに出てくる名前と一致するか確認。差分があれば調整（コードで使われていない不要なものは削除、コードで使われているが Railway に無いものは追加）。

### Task 7.2: runbook-deploy.md 作成

**Files:**
- Create: `docs/runbook-deploy.md`

- [ ] **Step 1: 内容を書く**

```markdown
# Deploy / Recovery Runbook

最終更新: 2026-05-23

## 必須環境変数（Railway Variables）

| 名前 | 用途 | 必須 |
|------|------|------|
| `DATABASE_URL` | Supabase Postgres 接続文字列（direct, not pooler） | ✓ |
| `SECRET_KEY` | JWT 署名鍵。流出時はトークン全失効のため即ローテーション | ✓ |
| `SUPER_ADMIN_KEY` | super-admin 画面の API キー | ✓ |
| `RESET_DB` | 起動時 DB リセット（テスト時のみ true、本番では未設定または false） | – |

**値はこの文書に書かない。** Railway Variables と 1Password にのみ保管。

## デプロイの仕組み

- `main` ブランチへの push → GitHub Actions CI（`.github/workflows/ci.yml`）が走る
- CI 緑 → Railway が自動デプロイ（main の HEAD を追従）
- CI 赤 → main マージ自体がブロックされるため本番には届かない（Required status checks）

## ロールバック手順

1. **Railway ダッシュボードを開く**
   - cabax プロジェクト → Deployments タブ
2. **直前の正常デプロイを特定**
   - ステータス Success の最新 1 つ前を選ぶ
3. **Redeploy をクリック**
   - 「Redeploy」または「Rollback」ボタンを押下
4. **`/health/deep` で復旧確認**

   ```bash
   curl https://web-production-d70f.up.railway.app/health/deep
   ```

   200 / `{"status":"ok","database":"ok"}` が返れば復旧。

## 障害時の確認順序

1. **UptimeRobot のアラート内容を確認**（どの監視が落ちたか）
2. **Railway logs を確認**

   ```bash
   # Railway CLI（要インストール）
   railway logs --service cabax | tail -200
   ```

   または Web UI から直接。`status_code` フィールドで 5xx を抽出、`exception` フィールドで stacktrace を確認。

3. **`/health/deep` で DB 生死確認**

   - `200` → アプリ OK、外部要因（CDN / ネットワーク）の可能性
   - `503` → DB 不達 → 次へ

4. **Supabase ステータス確認**
   - https://status.supabase.com
   - プロジェクトダッシュボードで pause 状態になっていないか

5. **直前のデプロイが原因と疑わしければロールバック**（上記手順）

## バックアップ

- 日次自動: `.github/workflows/backup.yml` が UTC 18:30（JST 03:30）に走る
- 復元: `docs/runbook-restore.md`

## 障害連絡フロー

オーナー（otokonoko0678@gmail.com）に Email / LINE で自動通知。
店舗運用が止まる類の障害（注文・会計が打てない）は即時ロールバック判断。
```

- [ ] **Step 2: ロールバック実機演習**

何でもよいので小さな commit（例：runbook 内のコメント変更）を main にマージ → Railway がデプロイ完了 → 直前の commit に Redeploy する操作を実行 → `/health/deep` が引き続き 200 を返すことを確認。

- [ ] **Step 3: Commit**

```bash
git add docs/runbook-deploy.md
git commit -m "docs: add deploy/recovery runbook with verified rollback"
git push
```

---

## 完了の定義（spec再掲）

以下すべて満たした状態：

- [ ] `pytest tests/` が緑（logger / middleware / exception handler / health/deep）
- [ ] CI が緑、構文エラー入りの PR は CI で fail することを 1 回実証
- [ ] Railway デプロイが main の CI 緑通過時のみ走る
- [ ] GitHub Actions の Daily Backup が緑で、R2 に暗号化 dump が出力されている
- [ ] `docs/runbook-restore.md` に「復元 → アプリ接続 → 画面表示」まで通ったログ or スクショ添付
- [ ] `docs/runbook-deploy.md` に env 一覧 + ロールバック実機検証済みの記録
- [ ] UptimeRobot の test alert が email に届くことを実証
- [ ] 3 つの HTML から `cdn.tailwindcss.com` が消え、`static/css/app.css` 経由で表示
- [ ] `/health/deep` が `SELECT 1` を実行し、DB 落ちで 503 を返す

---

## 注記

- **TDD カバレッジ:** コードレベル（logger, middleware, exception handlers, health/deep）は TDD。ops/infra（CI workflow, backup workflow, R2 設定, UptimeRobot, Tailwind ビルド, runbook）は実機/外部サービスでの検証。これは spec の「ユニットテストの大量導入はスコープ外」と整合。
- **`main.py` の構造には触らない:** 既存 3229 行の API ルートは順序・実装ともに維持。追加するのは middleware と exception_handler のみ。
- **失敗時のロールバック方針:** いずれのタスク群も他と独立してコミット可能。途中で詰まったら、そのグループだけ revert して他は維持できる構造。
