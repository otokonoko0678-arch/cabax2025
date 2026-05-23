"""共通テスト fixture。

main.py は import 時に SUPER_ADMIN_KEY 未設定だと RuntimeError を投げるため、
main を import する前に必須 env をセットしておく。
テスト DB は一時ファイル SQLite。in-memory はコネクション間でテーブルが
見えない問題があるため避ける。
"""
import os
import tempfile
import pytest

# --- main.py を import する前に必須 env をセット ---
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only")
# SUPER_ADMIN_KEY はデフォルト無し。未設定だと main.py が import 時に raise する。
os.environ.setdefault("SUPER_ADMIN_KEY", "test-super-admin-for-pytest")
_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix=".db", prefix="cabax-test-")
os.close(_fd)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB_PATH}")

from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """import 時に main を読み込むことで、上書きした env を確実に拾わせる。

    raise_server_exceptions=False で 5xx を例外として再raiseせず、レスポンスとして返す
    （exception handler の振る舞いをテストするため必須）。

    注意: `with TestClient(app)` の時点で main.py の @app.on_event("startup") が走り、
    インラインの列追加マイグレーションが実行される。Base.metadata.create_all を先に
    呼んでおけば startup 側は基本 no-op になる想定。
    """
    from main import app, Base, engine
    Base.metadata.create_all(bind=engine)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    Base.metadata.drop_all(bind=engine)
