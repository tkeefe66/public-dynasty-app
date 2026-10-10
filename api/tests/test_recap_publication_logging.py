import logging
import importlib


def test_share_paths_are_credentials_in_access_logs_and_telemetry():
    # Mutation: access log or Sentry breadcrumb retains a usable edition token.
    module = importlib.import_module('app.services.recap_video.public_logging')
    token = 'a'*43
    record = logging.LogRecord('uvicorn.access',20,'',0,'%s - "%s %s HTTP/%s" %d',
        ('client','GET',f'/api/public/analyst/{token}/media/b/video.mp4','1.1',200),None)
    module.SharePathFilter().filter(record)
    assert token not in record.getMessage()
    assert '/api/public/analyst/[redacted]/media/b/video.mp4' in record.getMessage()
    from httpx import URL
    record = logging.LogRecord('httpx',20,'',0,'HTTP Request: GET %s',
        (URL(f'https://example.test/api/public/analyst/{token}'),),None)
    module.SharePathFilter().filter(record)
    assert token not in record.getMessage()
    from app.services.oauth_telemetry import before_send
    assert before_send({'request':{'url':f'https://example.test/share/analyst/{token}'}},None) is None
    value = before_send({'breadcrumbs':{'values':[{'url':f'/api/public/analyst/{token}'},{'message':'safe'}]}},None)
    assert value['breadcrumbs']['values'] == [{'message':'safe'}]
