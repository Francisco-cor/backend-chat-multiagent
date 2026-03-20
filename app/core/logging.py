import json
import logging
from datetime import datetime, timezone

# Keys that belong to LogRecord internals — excluded from the "extra" pass-through.
_LOG_RECORD_BUILTIN_KEYS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


class JSONFormatter(logging.Formatter):
    """
    Emits each log record as a single-line JSON object.
    Compatible with log aggregators (Datadog, Loki, CloudWatch, etc.).
    Includes request_id when RequestIDFilter is attached to the handler.
    """

    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            entry["stack_info"] = self.formatStack(record.stack_info)
        # Pass through any extra={} fields supplied by the caller
        for key, val in record.__dict__.items():
            if key not in _LOG_RECORD_BUILTIN_KEYS and not key.startswith("_") and key not in entry:
                entry[key] = val
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_logging(json_logs: bool = True) -> None:
    """
    Configure root logger. Set JSON_LOGS=false in .env for plain-text output
    (useful during local development).
    """
    from app.core.request_id import RequestIDFilter

    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter() if json_logs else logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(request_id)s] %(name)s: %(message)s"
    ))
    handler.addFilter(RequestIDFilter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
