import { useEffect, useRef, useState } from 'react';
import { CampaignPreview, FEATURE_LABELS, GenerationSeries } from '@/lib/generation';
import { Button } from '@/components/furniture/Button';
import { leagueName, problemExplanation, secondary } from './GenerationShared';

/** Shared final paid gate for new content and replacements. */
export function GenerationApproval({ preview, leagues, busy, onApprove, onBack }: {
  preview: CampaignPreview; leagues: GenerationSeries[]; busy: boolean;
  onApprove: () => Promise<void>; onBack: () => void;
}) {
  const region = useRef<HTMLDivElement>(null);
  const [now, setNow] = useState(Date.now());
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    region.current?.focus();
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [preview.id]);
  const expired = now >= preview.expires_at * 1000;
  const blockedItems = preview.items.filter(item => item.blocked_by.length);
  return <div ref={region} role="region" aria-label="Review writing request" tabIndex={-1} className="mt-5 border-t border-rule pt-4 text-prose focus:outline-none">
    <h4 className="font-display text-name font-bold">Review writing request</h4>
    <p className="mt-2">{preview.items.length} content {preview.items.length === 1 ? 'item' : 'items'} · At most {preview.max_calls} AI requests.</p>
    <p className="mt-1 max-w-2xl text-dim">Starting this writing can incur charges. This is a request limit, not a dollar quote. Saved work and current permissions are checked again when you approve.</p>
    <ul className="mt-3 divide-y divide-rule">{preview.items.map(item => <li key={item.key} className="py-3">
      <strong>{item.label} · {FEATURE_LABELS[item.feature]}</strong>
      <p className="text-dim">{leagueName(item, leagues)} · Up to {item.max_calls} requests</p>
      <p className="text-dim">Model: <span>{item.model}</span></p>
      {item.blocked_by.map(reason => <p key={reason} className="mt-1 text-neg-strong">{problemExplanation({ reason, state: 'held' })}</p>)}
    </li>)}</ul>
    {!!preview.skipped && <p className="mt-2 text-dim">{Object.values(preview.skipped).reduce((sum, count) => sum + count, 0)} items skipped because they are completed, already in progress, or unavailable.</p>}
    {!preview.items.length && <p className="mt-2">There is no available writing in this request. Go back and choose other content.</p>}
    {!!blockedItems.length && <p className="mt-2 text-neg-strong">Approval is blocked. Resolve the issues shown above, then go back and review again.</p>}
    {expired ? <p role="alert" className="mt-2 text-neg-strong">This review expired. Go back and review the request again before approving.</p> : <p className="mt-2 text-dim">Review expires at {new Date(preview.expires_at * 1000).toLocaleTimeString()}.</p>}
    {error && <p role="alert" className="mt-2 text-neg-strong">{error}</p>}
    <div className="sticky bottom-0 z-10 mt-3 flex flex-wrap gap-3 border-t border-rule bg-surface py-3">
      <Button className="px-4 py-2" disabled={busy || sending || expired || !preview.items.length || !!blockedItems.length} onClick={async () => {
        if (sending || busy || Date.now() >= preview.expires_at * 1000) return;
        setSending(true); setError('');
        try { await onApprove(); }
        catch (err) { setError(err instanceof Error ? err.message : 'Writing could not start. Go back and review again.'); }
        finally { setSending(false); }
      }}>{sending ? 'Starting writing…' : 'Approve & start writing'}</Button>
      <button className={secondary} disabled={busy || sending} onClick={onBack}>Back to selection</button>
    </div>
  </div>;
}
