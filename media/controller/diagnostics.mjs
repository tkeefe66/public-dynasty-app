const TYPES = new Set(['Error', 'TypeError', 'SyntaxError', 'TimeoutError', 'AbortError',
  'RailwayError', 'RailwayAuthError', 'RailwayConnectionError', 'RailwayGraphQLError',
  'ExecInterruptedError', 'ExecNotStartedError', 'ExecControlUnsupportedError',
  'SandboxNotFoundError', 'SandboxFailedError', 'SandboxTemplateBuildError', 'SandboxTimeoutError']);
const CODES = new Set(['EACCES', 'ENOENT', 'ENOSPC', 'EIO', 'ECONNRESET', 'ECONNREFUSED',
  'ETIMEDOUT', 'ENOTFOUND', 'EAI_AGAIN', 'UND_ERR_CONNECT_TIMEOUT', 'UND_ERR_SOCKET',
  'WORKER_START_FAILED', 'WORKER_DRAIN_FAILED', 'MISSING_CONFIGURATION']);
const VARIABLES = new Set(['RAILWAY_TOKEN', 'RAILWAY_ENVIRONMENT_ID', 'RECAP_WORKER_CHECKPOINT',
  'RECAP_WORKER_IMAGE', 'MEDIA_API_URL', 'MEDIA_CONTROL_API_URL', 'MEDIA_WORKER_TOKEN', 'ELEVENLABS_API_KEY']);

// Never serialize messages, stacks, response bodies, commands, or arbitrary provider fields.
export function failureEvent(error, context) {
  const code = CODES.has(error?.code) ? error.code : CODES.has(error?.cause?.code) ? error.cause.code : undefined;
  const number = value => Number.isInteger(value) ? value : undefined;
  return { event: 'recap_controller_failure', operation: context.operation, phase: context.phase,
    error_type: TYPES.has(error?.name) ? error.name : 'UnknownError', code,
    configuration_key: VARIABLES.has(error?.variable) ? error.variable : undefined,
    http_status: number(error?.status), close_code: number(error?.closeCode),
    exit_code: number(error?.exitCode), timed_out: error?.timedOut === true || undefined,
    next_step: context.operation.startsWith('cloud.')
      ? 'Reconcile the retained VM identity on the next scheduled run; do not repeat creation or narration. Check Railway connectivity and credentials if failures persist.'
      : context.operation.startsWith('store.')
        ? 'Check the mounted state volume and permissions; preserve its contents before retrying reconciliation.'
        : 'Check required controller configuration and demand API availability; reconcile retained state before launching work.',
  };
}

export function observed(adapter, prefix, context) {
  return new Proxy(adapter, { get(target, key) {
    const value = target[key];
    if (typeof value !== 'function') return value;
    return async (...args) => {
      context.operation = `${prefix}.${String(key)}`;
      const result = await value.apply(target, args);
      if (prefix === 'store') context.phase = (key === 'read' ? result : args[0])?.phase ?? 'idle';
      return result;
    };
  } });
}
