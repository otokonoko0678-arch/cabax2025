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
        # 例外の内容。ここに無いと extra={"error": ...} が黙って捨てられ、
        # ログには "health_deep_db_fail" のような見出しだけが残って原因が追えない。
        "error",
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
