import { useState } from 'react';
import { generationRequest } from '@/lib/api';
import { FEATURE_LABELS, GenerationFeature, GenerationOverview, GenerationSeries } from '@/lib/generation';
import { GenerationRecords } from './GenerationRecords';
import { ActionForm, ActionProps, readable, secondary, summaryClass, TechnicalDetails } from './GenerationShared';

export function GenerationRecovery({ overview, leagues, busy, run, version }: ActionProps & { overview: GenerationOverview; leagues: GenerationSeries[]; version: number }) {
  const [action, setAction] = useState('');
  const [providerKey, setProviderKey] = useState('');
  const [feature, setFeature] = useState('');
  const blocked = busy;
  const breakers = JSON.parse(overview.control.breakers_json || '{}') as Record<string, { open?: boolean }>;
  return <div>
          <details className="mt-3"><summary className={summaryClass}>Activation and recovery</summary><p className="max-w-2xl text-prose text-dim">Use after resolving a provider or deployment problem. Activation requires a configured deployment ID, stopped legacy workers, and completed receipt checks. Missed work stays held for separate approval.</p>
            {!overview.execution_epoch_configured && <p className="mt-2 text-prose text-warn-strong">Setup required in Railway: configure the generation execution epoch before activation.</p>}
            <div className="mt-3 flex flex-wrap gap-2"><button className={secondary} disabled={blocked || !overview.execution_epoch_configured || overview.emergency_paused} onClick={() => setAction("activate")}>Activate AI execution</button>
              {(Object.keys(FEATURE_LABELS) as GenerationFeature[]).filter(f => breakers[f]?.open).map(f => <button key={f} className={secondary} disabled={blocked} onClick={() => { setFeature(f); setAction("reset_breaker"); }}>Reset {FEATURE_LABELS[f]} safety stop</button>)}
            </div>
            {(overview.providers || []).map(provider => <div key={provider.provider + ":" + provider.account_key} className="mt-3 text-prose">
              <p>{provider.provider} / {provider.account_key}: {provider.hold ? readable(provider.hold) : provider.cooldown_until > Date.now() / 1000 ? "Rate limited" : "Available"}</p>
              {(provider.hold || provider.cooldown_until > Date.now() / 1000) && <button className={secondary} disabled={blocked} onClick={() => setProviderKey(provider.provider + ":" + provider.account_key)}>Review {provider.provider} / {provider.account_key} recovery</button>}
              {providerKey === provider.provider + ":" + provider.account_key && <ActionForm title={`Reset ${provider.provider} / ${provider.account_key}`} description="Resolve this account's failed or uncertain requests first. Resetting does not authorize a replacement take." submitLabel="Reset provider account" busy={blocked} onCancel={() => setProviderKey("")} onSubmit={reason => run(() => generationRequest("/provider/reset", { provider: provider.provider, account_key: provider.account_key, expected_revision: provider.revision, reason }), "Provider account controls updated.")} />}
            </div>)}
            {action && action !== "pause" && <ActionForm key={action + feature} title="Update AI recovery controls" description="Confirm the underlying problem is resolved. Existing policy limits still apply after this change." submitLabel="Confirm recovery" busy={blocked} requireStopped={action === "activate"} onCancel={() => setAction("")} onSubmit={(reason, workersStopped) => run(() => generationRequest("/control", { action, feature: action === "reset_breaker" ? feature : "", expected_revision: overview.control.revision, reason, workers_stopped: workersStopped }), "Recovery controls updated. Check AI status above.")} />}
            <TechnicalDetails value={overview} label="Control state and deployment details" />
          </details>
          <GenerationRecords leagues={leagues} busy={blocked} run={run} version={version} initialKind="attempts" advanced />
  </div>;
}
