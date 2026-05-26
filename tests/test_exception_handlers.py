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
