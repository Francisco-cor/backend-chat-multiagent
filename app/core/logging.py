import json
import logging
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """
    Emits each log record as a single-line JSON object.
    Compatible with log aggregators (Datadog, Loki, CloudWatch, etc.).
    """

    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            entry["stack_info"] = self.formatStack(record.stack_info)
        # Include any extra fields passed via logger.info("msg", extra={"key": val})
        for key, val in record.__dict__.items():
            if key not in logging.LogRecord.__dict__ and not key.startswith("_"):
                entry[key] = val
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure_logging(json_logs: bool = True) -> None:
    """
    Configure root logger. Set JSON_LOGS=false in .env for plain-text output
    (useful during local development).
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter() if json_logs else logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
