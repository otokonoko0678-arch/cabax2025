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
