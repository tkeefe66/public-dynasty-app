"""Share URL paths carry credentials even on anonymous GETs."""
import logging
import re
import traceback
from app.services.route_normalize import redact_share_path

PATTERN = re.compile(r'(/(?:api/public|share)/analyst/)[^/?\s\"\'<>]+')


def redact(value):
    if isinstance(value, str):
        return redact_share_path(value)
    if isinstance(value, (tuple, list)):
        return type(value)(redact(v) for v in value)
    if isinstance(value, dict):
        return {k:redact(v) for k,v in value.items()}
    if value is not None and not isinstance(value,(int,float,bool)) and redact_share_path(str(value)) != str(value):
        return redact(str(value))
    return value


class SharePathFilter(logging.Filter):
    def filter(self, record):
        record.msg, record.args = redact(record.msg), redact(record.args)
        if record.exc_info:
            record.exc_text = redact(''.join(traceback.format_exception(*record.exc_info)))
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


def install():
    for logger in (logging.getLogger(name) for name in ('uvicorn.access','uvicorn.error','httpx','httpcore')):
        if not any(isinstance(item, SharePathFilter) for item in logger.filters):
            logger.addFilter(SharePathFilter())
    for handler in logging.getLogger().handlers:
        if not any(isinstance(item, SharePathFilter) for item in handler.filters):
            handler.addFilter(SharePathFilter())
