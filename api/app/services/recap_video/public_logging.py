"""Share URL paths carry credentials even on anonymous GETs."""
import logging
import re
import traceback

PATTERN = re.compile(r'(/(?:api/public|share)/analyst/)[^/?\s\"\'<>]+')


def redact(value):
    if isinstance(value, str):
        return PATTERN.sub(r'\1[redacted]', value)
    if isinstance(value, tuple):
        return tuple(redact(v) for v in value)
    if isinstance(value, dict):
        return {k:redact(v) for k,v in value.items()}
    if value is not None and not isinstance(value,(int,float,bool)) and PATTERN.search(str(value)):
        return redact(str(value))
    return value


class SharePathFilter(logging.Filter):
    def filter(self, record):
        record.msg, record.args = redact(record.msg), redact(record.args)
        if record.exc_info:
            record.exc_text = redact(''.join(traceback.format_exception(*record.exc_info)))
        return True


def install():
    for logger in (logging.getLogger(name) for name in ('uvicorn.access','uvicorn.error','httpx','httpcore')):
        if not any(isinstance(item, SharePathFilter) for item in logger.filters):
            logger.addFilter(SharePathFilter())
    for handler in logging.getLogger().handlers:
        if not any(isinstance(item, SharePathFilter) for item in handler.filters):
            handler.addFilter(SharePathFilter())
