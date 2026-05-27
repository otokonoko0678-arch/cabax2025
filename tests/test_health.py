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
