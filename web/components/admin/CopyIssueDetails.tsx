import { useState } from 'react';
import { secondary } from './GenerationShared';

export function CopyIssueDetails({ report, busy }: { report: string; busy: boolean }) {
  const [status, setStatus] = useState('');
  const [fallback, setFallback] = useState(false);
  return <div>
    <button className={secondary} disabled={busy} onClick={async () => {
      setStatus(''); setFallback(false);
      try { await navigator.clipboard.writeText(report); setStatus('Issue details copied. Paste them into your Codex chat.'); }
      catch { setFallback(true); }
    }}>Copy issue details</button>
    {status && <p role="status" className="mt-3 max-w-xl text-prose">{status}</p>}
    {fallback && <label className="mt-3 block max-w-xl text-prose">Automatic copying is unavailable. Select and copy these issue details:<textarea className="mt-2 min-h-32 w-full rounded-sm border border-rule bg-surface p-3" readOnly value={report} onFocus={event => event.target.select()} /></label>}
  </div>;
}
