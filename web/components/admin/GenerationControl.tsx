"use client";

import { useEffect, useRef, useState } from "react";
import { generationRequest } from "@/lib/api";
import { FEATURE_LABELS, GenerationFeature, GenerationOverview, GenerationPage, GenerationRecord, GenerationSeries } from "@/lib/generation";
import { GenerationRecovery } from './GenerationRecovery';
import { GenerationRecapWorkspace } from './GenerationRecapWorkspace';
import styles from './GenerationStudio.module.css';
import { GenerationSettings } from "./GenerationSettings";
import { GenerationBulkReview } from "./GenerationBulkReview";
import { GenerationRecords } from "./GenerationRecords";
import { ActionForm, money, readable, RunAction, secondary, controlClass } from "./GenerationShared";

const emptyPage: GenerationPage<GenerationRecord> = { records: [], next_offset: null };
const pauseReasons: Record<string, string> = {
  activation_required: "AI has not completed its safety activation.",
  app_paused: "AI writing is paused in the shared settings.",
  owner_paused: "You paused AI writing.", manual_pause: "You paused AI writing.",
};

export function GenerationControl() {
  const [overview, setOverview] = useState<GenerationOverview | null>(null);
  const [leagues, setLeagues] = useState<GenerationSeries[]>([]);
  const [stopped, setStopped] = useState(emptyPage);
  const [held, setHeld] = useState(emptyPage);
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [action, setAction] = useState("");
  const [view, setView] = useState('content');
  const [contentType, setContentType] = useState<GenerationFeature | ''>('');
  const [series, setSeries] = useState('');
  const [workView, setWorkView] = useState('review');
  const [budgetSeriesId, setBudgetSeriesId] = useState<string>();
  const [budgetEpisodeId, setBudgetEpisodeId] = useState<string>();
  const [budgetRequestId, setBudgetRequestId] = useState(0);

  const mutationLock = useRef(false);

  const filterQuery = `${series ? `&series_id=${encodeURIComponent(series)}` : ''}${contentType ? `&feature=${contentType}` : ''}`;
  useEffect(() => {
    let current = true;
    setLoading(true); setError(""); setStopped(emptyPage); setHeld(emptyPage);
    async function registry() {
      const result: GenerationSeries[] = [];
      let offset: number | null = 0;
      while (offset !== null) {
        const page: GenerationPage<GenerationSeries> = await generationRequest(`/leagues?limit=100&offset=${offset}`);
        if (!current) return [];
        result.push(...page.records); offset = page.next_offset;
      }
      return result;
    }
    Promise.all([
      generationRequest<GenerationOverview>(), registry(),
      generationRequest<GenerationPage<GenerationRecord>>(`/records/jobs?limit=25&state=needs_attention${filterQuery}`),
      generationRequest<GenerationPage<GenerationRecord>>(`/records/jobs?limit=25&state=held${filterQuery}`),
    ]).then(([summary, registered, failed, paused]) => {
      if (current) { setOverview(summary); setLeagues(registered); setStopped(failed); setHeld(paused); }
    }).catch(err => { if (current) setError(err.message || "AI controls could not load. Reload to try again."); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [version, filterQuery]);

  const run: RunAction = async (callback, message, reload = true) => {
    if (mutationLock.current) throw new Error("Another change is being saved. Wait for it to finish.");
    mutationLock.current = true; setBusy(true); setNotice("");
    try { await callback(); setNotice(message); if (reload) setVersion(v => v + 1); }
    finally { mutationLock.current = false; setBusy(false); }
  };
  const blocked = busy || loading;
  const breakers = overview ? JSON.parse(overview.control.breakers_json || "{}") as Record<string, { open?: boolean }> : {};
  const eligibleLeagues = leagues.filter(l => l.lifecycle === "active" && !l.hold && !l.effective.policy.paused && !l.effective.blocked_by.length);
  const globallyPaused = !!overview && (overview.emergency_paused || !!overview.control.hold || !!overview.control.provider_hold || (overview.effective.policy.paused && !eligibleLeagues.length));
  const enabledModes = eligibleLeagues.flatMap(l => Object.entries(l.effective.policy.features).filter(([name, f]) => !f.paused && !breakers[name]?.open).map(([, f]) => f.mode));
  const automatic = enabledModes.includes("automatic"), manual = enabledModes.includes("manual");
  const heading = globallyPaused ? "AI is paused" : automatic ? "Automatic writing is enabled" : manual ? "Waiting for your approval" : "AI writing is off";
  const reviewRows = [...stopped.records, ...held.records].filter((row, index, all) => all.findIndex(r => r.id === row.id) === index);
  function openRecapBudget(seriesId: string, episodeId?: string) {
    setBudgetSeriesId(seriesId); setBudgetEpisodeId(episodeId); setBudgetRequestId(value => value + 1); setView("spend");
  }

  const contentTypes: { value: GenerationFeature | ''; label: string; description: string }[] = [
    { value: '', label: 'All work', description: 'Writing and data refreshes' },
    { value: 'recap_video', label: 'Weekly recap', description: 'Scripts, media and publication' },
    { value: 'analyst', label: 'Weekly Analyst', description: 'Weekly league coverage' },
    { value: 'trade_story', label: 'Trade stories', description: 'Every move, with context' },
    { value: 'gm_rating_blurb', label: 'GM profiles', description: 'The managers behind the moves' },
    { value: 'franchise_blurb', label: 'Franchise outlooks', description: 'Where each team is headed' },
  ];
  const scopeName = leagues.find(league => league.id === series)?.name || 'All leagues';
  function openRecapEpisode(seriesId: string) {
    setSeries(seriesId); setContentType('recap_video'); setWorkView('episodes'); setView('content');
  }
  async function loadMore(state: 'needs_attention' | 'held') {
    const page = state === 'held' ? held : stopped;
    if (page.next_offset === null) return;
    setBusy(true); setError('');
    try {
      const more = await generationRequest<GenerationPage<GenerationRecord>>(`/records/jobs?limit=25&state=${state}&offset=${page.next_offset}${filterQuery}`);
      const update = state === 'held' ? setHeld : setStopped;
      update(old => ({ records: [...old.records, ...more.records], next_offset: more.next_offset }));
    } catch (err) { setError(err instanceof Error ? err.message : 'More review work could not load. Try again.'); }
    finally { setBusy(false); }
  }
  return <section className={styles.studio} aria-labelledby="generation-title">
    <header className={styles.header}>
      <div><h2 id="generation-title">AI writing</h2><p>Your leagues’ writing, from first draft to publication.</p></div>
      <div className={styles.headerActions}><button className={secondary} disabled={blocked} onClick={() => setVersion(v => v + 1)}>Reload status</button><button className={secondary} disabled={blocked} onClick={() => setAction(action === 'pause' ? '' : 'pause')}>Pause all AI writing</button></div>
    </header>
    {error && <p role="alert" className="mb-4 text-prose text-neg-strong">{error}</p>}
    {notice && <p role="status" className="mb-4 text-prose text-pos-strong">{notice}</p>}
    {loading && <p role="status" className="mb-4 text-prose text-dim">Checking AI status…</p>}
    {overview && <>
      <div className={styles.status}><div><h3>{heading}</h3><span>{overview.jobs.needs_attention || 0} stopped · {overview.jobs.held || 0} held · Across all leagues</span></div><button disabled={busy} onClick={() => setView('spend')}>Tracked AI spend: <strong className="font-mono">{money(overview.known_cost_microusd)}</strong></button></div>
      {overview.emergency_paused && <p className={styles.warning}>The deployment safety switch is on. Turn off the emergency pause in Railway before activating AI here.</p>}
      {globallyPaused && overview.effective.blocked_by.length > 0 && <ul className={styles.warning}>{overview.effective.blocked_by.map(reason => <li key={reason}>{pauseReasons[reason] || `Writing is blocked: ${readable(reason)}.`}</li>)}</ul>}
      {(overview.providers || []).filter(provider => provider.hold || provider.cooldown_until > Date.now() / 1000).map(provider => <p key={provider.provider + ':' + provider.account_key} className={styles.warning}>{provider.provider} / {provider.account_key} is blocked: {provider.hold ? readable(provider.hold) : 'rate limited'}. Review this account under Recovery.</p>)}
      {(Object.keys(FEATURE_LABELS) as GenerationFeature[]).filter(f => breakers[f]?.open).map(f => <p key={f} className={styles.warning}>{FEATURE_LABELS[f]} is stopped after repeated failures. Review the failed work, then reset its safety stop under Recovery.</p>)}
      {overview.unknown_cost_attempts > 0 && <p className="mb-4 text-prose text-warn-strong">{overview.unknown_cost_attempts} requests still have unknown cost. Review AI requests and costs under Recovery.</p>}
      {action === 'pause' && <ActionForm title="Pause all AI writing" description="Block new paid requests across every league. Requests already sent may still finish and incur charges. Data refreshes continue separately." submitLabel="Confirm pause" busy={blocked} onCancel={() => setAction('')} onSubmit={reason => run(() => generationRequest('/control', { action: 'pause', feature: '', expected_revision: overview.control.revision, reason, workers_stopped: false }), 'AI writing paused across all leagues.')} />}
      <nav className={styles.nav} aria-label="AI writing views">{Object.entries({ content: 'Content', rules: 'Writing rules', spend: 'Spend & limits', activity: 'Activity', recovery: 'Recovery' }).map(([key, label]) => <button key={key} aria-current={view === key ? 'page' : undefined} disabled={busy} onClick={() => setView(key)}>{label}</button>)}</nav>
      {view === 'content' && <>
        <div className={styles.scope}><div><h3 className={styles.sectionTitle}>Content studio</h3><p className="mt-1 text-prose text-dim">Choose a content type to review its work.</p></div><label>Content for league<select className={controlClass} disabled={blocked} value={series} onChange={event => setSeries(event.target.value)}><option value="">All leagues</option>{leagues.map(league => <option key={league.id} value={league.id}>{league.name || 'Unnamed league'}</option>)}</select></label></div>
        <div className={styles.types} aria-label="Content workspaces">{contentTypes.map(type => <button key={type.value} aria-label={`${type.label} workspace`} aria-pressed={contentType === type.value} disabled={blocked} onClick={() => { setContentType(type.value); if (type.value === 'recap_video') setWorkView('episodes'); else if (workView === 'episodes') setWorkView('review'); }}>{type.label}<span>{type.description}</span></button>)}</div>
        <div className={styles.workNav} aria-label="Content tasks">
          {contentType === 'recap_video' && <button aria-pressed={workView === 'episodes'} disabled={busy} onClick={() => setWorkView('episodes')}>Episodes</button>}
          <button aria-pressed={workView === 'review'} disabled={busy} onClick={() => setWorkView('review')}>Review problems</button><button aria-pressed={workView === 'approvals'} disabled={busy} onClick={() => setWorkView('approvals')}>Approve writing</button><button aria-pressed={workView === 'saved'} disabled={busy} onClick={() => setWorkView('saved')}>Saved content</button>
        </div>
        <div className={styles.columns}>
          <div className={styles.main}>
            {workView === 'episodes' && <><h3>Weekly recap</h3><GenerationRecapWorkspace key={series} leagues={leagues} busy={blocked} run={run} version={version} scopeSeries={series} budgetSeriesId={budgetSeriesId} initialEpisodeId={budgetEpisodeId} onRecapBudget={openRecapBudget} /></>}
            {workView === 'review' && <section role="region" aria-labelledby="generation-review-title"><h3 id="generation-review-title">Needs your review</h3><p className="mt-2 text-prose text-dim">{contentTypes.find(type => type.value === contentType)?.label} · {scopeName}</p>
              {!loading && !error && !reviewRows.length && <p className={styles.empty}>No stopped or held work in this workspace. Choose Approve writing to review new or historical content.</p>}
              <GenerationBulkReview key={filterQuery} rows={reviewRows} leagues={leagues} busy={blocked} run={run} version={version} onRecapBudget={openRecapBudget} onRecapEpisode={openRecapEpisode} featureFilter={contentType || undefined} scopeSeries={series} hasMore={stopped.next_offset !== null || held.next_offset !== null} />
              {stopped.next_offset !== null && <button className={secondary} disabled={blocked} onClick={() => loadMore('needs_attention')}>Load more stopped work</button>}{held.next_offset !== null && <button className={secondary} disabled={blocked} onClick={() => loadMore('held')}>Load more paused work</button>}
            </section>}
            {workView === 'approvals' && <section role="region" aria-label="Manual content and catch-up"><h3>Approve writing</h3><GenerationRecords key={`approvals:${filterQuery}`} leagues={leagues} busy={blocked} run={run} version={version} initialKind="candidates" featureFilter={contentType || undefined} scopeSeries={series} onRecapBudget={openRecapBudget} /></section>}
            {workView === 'saved' && <><h3>Saved content</h3><GenerationRecords key={`saved:${filterQuery}`} leagues={leagues} busy={blocked} run={run} version={version} initialKind="artifacts" featureFilter={contentType || undefined} scopeSeries={series} onRecapBudget={openRecapBudget} /></>}
          </div>
          <aside className={styles.aside}><section><h3>Writing rules</h3><p>{globallyPaused ? 'New paid writing is blocked. Resolve the pause before approving more work.' : 'Automatic covers new eligible events. Manual and historical work needs your approval.'}</p><button className={secondary} disabled={busy} onClick={() => setView('rules')}>Manage writing rules</button></section><section><h3>Spend & limits</h3><dl><div><dt>Tracked across all leagues</dt><dd>{money(overview.known_cost_microusd)}</dd></div><div><dt>Unknown request costs</dt><dd>{overview.unknown_cost_attempts}</dd></div></dl><p>Excludes earlier spending and unrecorded charges.</p><button className={secondary} disabled={busy} onClick={() => { if (series) openRecapBudget(series); else setView('spend'); }}>Review spending limits</button></section></aside>
        </div>
      </>}
      {view === 'rules' && <div className={styles.main}><h3>Writing rules</h3><GenerationSettings leagues={leagues} busy={blocked} run={run} version={version} /></div>}
      {view === 'spend' && <div className={styles.main}><div className={styles.summary}><div><h3>Tracked AI spend</h3><p>All time, across all leagues. Excludes earlier spending and unrecorded charges. Recap limits below include reserved and carry-forward obligations.</p></div><strong>{money(overview.known_cost_microusd)}</strong></div><GenerationRecapWorkspace leagues={leagues} busy={blocked} run={run} version={version} budgetSeriesId={budgetSeriesId} budgetRequestId={budgetRequestId} initialEpisodeId={budgetEpisodeId} budgets /></div>}
      {view === 'activity' && <div className={styles.main}><h3>Recent activity</h3><p className="mt-2 text-prose text-dim">What ran, when it ran, and how it ended.</p><GenerationRecords leagues={leagues} busy={blocked} run={run} version={version} onRecapBudget={openRecapBudget} onRecapEpisode={openRecapEpisode} /></div>}
      {view === 'recovery' && <div className={styles.main}><h3>Recovery & records</h3><p className="mt-2 text-prose text-dim">Provider receipts, delivery, and change history. Review the evidence before changing execution controls.</p><GenerationRecovery overview={overview} leagues={leagues} busy={blocked} run={run} version={version} /></div>}
    </>}
  </section>;
}
