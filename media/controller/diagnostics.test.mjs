import { test } from 'node:test';
import assert from 'node:assert/strict';
import { failureEvent } from './diagnostics.mjs';

test('diagnostics allow only known types and codes, numeric statuses and configuration keys', () => {
  // Mutation: spreading an SDK error or using its message exposes credentials and response bodies.
  const error = { name: 'secret-name', code: 'secret-code', message: 'secret-message',
    stack: 'secret-stack', responseBody: 'secret-body', status: 'secret-status',
    variable: 'secret-variable', cause: { code: 'ECONNRESET', message: 'secret-cause' } };
  const event = failureEvent(error, { operation: 'cloud.create', phase: 'creating' });
  assert.doesNotMatch(JSON.stringify(event), /secret/);
  assert.equal(event.error_type, 'UnknownError');
  assert.equal(event.code, 'ECONNRESET');
  assert.equal(event.http_status, undefined);
  const auth = failureEvent({ name: 'RailwayGraphQLError', status: 401 }, { operation: 'cloud.find', phase: 'creating' });
  assert.equal(auth.http_status, 401);
  const config = failureEvent({ code: 'MISSING_CONFIGURATION', variable: 'RAILWAY_TOKEN' },
    { operation: 'configuration', phase: 'unknown' });
  assert.equal(config.configuration_key, 'RAILWAY_TOKEN');
});
