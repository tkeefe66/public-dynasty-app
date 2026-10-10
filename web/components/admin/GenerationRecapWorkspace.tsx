import { useEffect, useState } from 'react';
import { GenerationSeries } from '@/lib/generation';
import { GenerationRecapEpisode } from './GenerationRecapEpisode';
import { GenerationRecapBudget } from './GenerationRecapBudget';
import { ActionProps, controlClass } from './GenerationShared';

export function GenerationRecapWorkspace({ leagues, busy, run, version, budgetSeriesId, budgetRequestId, budgets = false, onRecapBudget, scopeSeries, initialEpisodeId }: ActionProps & {
  leagues: GenerationSeries[]; version: number; budgetSeriesId?: string; budgetRequestId?: number; budgets?: boolean; scopeSeries?: string; initialEpisodeId?: string;
}) {
  const [localSeries, setSeries] = useState(budgetSeriesId || '');
  const series = scopeSeries ?? localSeries;
  const [episodeId, setEpisodeId] = useState<string>();
  const [label, setLabel] = useState<string>();
  useEffect(() => { if (budgetSeriesId) setSeries(budgetSeriesId); }, [budgetSeriesId, budgetRequestId]);
  useEffect(() => {
    if (budgets && budgetSeriesId && series === budgetSeriesId) {
      const panel = document.getElementById('generation-recap-budgets');
      panel?.focus(); panel?.scrollIntoView?.({ block: 'start' });
    }
  }, [budgets, budgetSeriesId, budgetRequestId, series]);
  const selected = leagues.find(league => league.id === series);
  return <div>
    {scopeSeries === undefined && <label className="block max-w-lg text-prose">{budgets ? 'Recap limits for league' : 'Recap episode for league'}
      <select className={controlClass + ' mt-2'} value={series} disabled={busy} onChange={event => { setSeries(event.target.value); setEpisodeId(undefined); setLabel(undefined); }}>
        <option value="">Choose a league</option>
        {leagues.map(league => <option key={league.id} value={league.id}>{league.name || 'Unnamed league'}</option>)}
      </select>
    </label>}
    {!selected && <p className="mt-5 text-prose text-dim">Select an individual league above to {budgets ? 'view and edit its recap spending limits.' : 'review its saved episodes and finished previews.'}</p>}
    {selected && <>
      <GenerationRecapEpisode key={'episode:' + selected.id} seriesId={selected.id} busy={busy} run={run} version={version} selectionOnly={budgets} initialEpisodeId={series === budgetSeriesId ? initialEpisodeId : undefined} onRecapBudget={onRecapBudget} onEpisodeChange={(id, name) => { setEpisodeId(id); setLabel(name); }} />
      {budgets && <GenerationRecapBudget key={'budget:' + selected.id} seriesId={selected.id} episodeId={episodeId} episodeLabel={label} busy={busy} run={run} version={version} />}
    </>}
  </div>;
}
