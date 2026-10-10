import { useEffect, useRef, useState } from 'react';
import { generationRequest } from '@/lib/api';
import { RecapEpisodeSummary, RecapEpisodeView } from '@/lib/generation';
import { ActionProps, controlClass, money, readable, secondary, TechnicalDetails } from './GenerationShared';

const labels: Record<string,string> = {
  reassign_worker:'Reassign recovery worker', resume_recovered_audio:'Resume free work with recovered audio',
  review_publish:'Review finished preview', resume_free:'Resume free work', reconcile_request:'Reconcile request',
  bounded_replacement:'Review bounded replacement', skip_video:'Skip video', restore_access:'Restore edition access',
  disable_future_sharing:'Disable future sharing', prepare_preview:'Prepare episode preview', renew_preflight:'Renew free voice verification', review_correction:'Review correction',
};
const explanations: Record<string,string> = {
  recap_facts_changed:'Week facts changed; public edition withdrawn. Review corrected facts before proposing paid repair.',
  recap_dependency_changed:'Earlier results changed; later article and media withdrawn because their context may depend on those results. Review the affected context.',
  recap_dependency_inventory_changed:'An earlier period was discovered after this episode. Review its historical context before restoring publication.',
  speech_verification_failed:'Spoken words differ from the approved script. Inspect exact evidence; spelling review may resume free checks using the same narration.',
  input_revision_required:'Saved media failed its content or timing checks. Review the measured evidence before resuming free work.',
  media_calibration_required:'Exact account, voice, rate, full performance and runtime calibration still need explicit approval. Synthetic checks do not enable automation.',
  media_calibration_changed:'Voice, provider, source or renderer changed. Requalification is required.',
};
interface Preview { digest: string; article: { markdown: string }; media: unknown }
export function episodeLabel(row: RecapEpisodeSummary) {
  return `${row.round ? `Round ${row.round} · Week ${row.week}` : `Week ${row.week}`} · ${row.season}`;
}
interface Replacement { digest: string; requests: number; maximum_microusd: number; original_requests: unknown }
const checks = { factual_coverage:'Facts and every league member', performance:'Complete voice performance', physical_phone:'Physical phone playback', message_preview:'Real message preview' };

export function GenerationRecapEpisode({ seriesId, version, busy, run, onEpisodeChange, selectionOnly = false, onRecapBudget, initialEpisodeId }: ActionProps & {
  seriesId:string; version:number; onEpisodeChange:(episodeId:string | undefined, label?:string)=>void; selectionOnly?:boolean; initialEpisodeId?:string;
}) {
  const [records,setRecords]=useState<RecapEpisodeSummary[]>([]);
  const [selected,setSelected]=useState('');
  const [view,setView]=useState<RecapEpisodeView | null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [action,setAction]=useState('');
  const [reason,setReason]=useState('');
  const [preview,setPreview]=useState<Preview | null>(null);
  const [replacement,setReplacement]=useState<Replacement | null>(null);
  const [evidence,setEvidence]=useState<Record<string,string>>({});
  const [disposition,setDisposition]=useState('');
  const [reload,setReload]=useState(0);
  const [entity,setEntity]=useState('');
  const [canonical,setCanonical]=useState('');
  const [alias,setAlias]=useState('');
  const [reusable,setReusable]=useState(false);
  const [attempt,setAttempt]=useState('');
  const previewRequest=useRef(0);
  const callback=useRef(onEpisodeChange);
  callback.current=onEpisodeChange;
  useEffect(()=>{
    let current=true;
    setRecords([]);setSelected('');setView(null);setLoading(true);setAction('');callback.current(undefined);
    generationRequest<{records:RecapEpisodeSummary[]}>(`/recap-episodes?series_id=${encodeURIComponent(seriesId)}`).then(value=>{
      if(!current)return;
      const rows=value.records || [];
      const initial=initialEpisodeId ? rows.find(row=>row.episode_id===initialEpisodeId) : rows[0];
      setRecords(rows);setSelected(initial?.episode_id || '');callback.current(initial?.episode_id, initial ? episodeLabel(initial) : undefined);
      if(!initial){setLoading(false);if(initialEpisodeId)setError('The selected episode is no longer available. Choose an episode to inspect its limits.');}
    }).catch(err=>{if(current){setError(err.message || 'Episodes could not load. Reload status.');setLoading(false);}});
    return()=>{current=false;};
  },[seriesId,initialEpisodeId]);
  useEffect(()=>{
    if(!selected)return;
    if(selectionOnly){setLoading(false);return;}
    let current=true;
    previewRequest.current+=1;
    setLoading(true);setError('');setView(null);setAction('');setPreview(null);setReplacement(null);
    generationRequest<RecapEpisodeView>(`/recap-episodes/${selected}`).then(value=>{if(current)setView(value);})
      .catch(err=>{if(current)setError(err.message || 'Episode evidence could not load. Reload status.');})
      .finally(()=>{if(current)setLoading(false);});
    return()=>{current=false;};
  },[selected,version,reload,selectionOnly]);
  const blocked=busy || loading;
  async function open(next:string) {
    const request=++previewRequest.current;
    setAttempt(view?.attempts.find(a=>['unknown','abandoned','received'].includes(a.state))?.id || '');
    setAction(next);setError('');setReason('');setEvidence({});setDisposition('');setPreview(null);setReplacement(null);
    setEntity('');setCanonical('');setAlias('');setReusable(false);
    if(!view)return;
    try {
      if(next==='review_publish') {const result=await generationRequest<Preview>(`/recap-episodes/${selected}/preview`,{expected_revision:view.authority_revision,media_id:view.media_id});if(request===previewRequest.current)setPreview(result);}
      if(next==='bounded_replacement') {const result=await generationRequest<Replacement>(`/recap-episodes/${selected}/replacement`);if(request===previewRequest.current)setReplacement(result);}
    } catch(err) {if(request===previewRequest.current)setError(err instanceof Error?err.message:'Current preview could not load. Reload status.');}
  }
  async function submit() {
    if(!view || blocked)return;
    setError('');
    try {
      await run(async()=>{
        if(action==='review_publish' && preview) return generationRequest(`/recap-episodes/${selected}/approve`,{
          expected_revision:view.authority_revision,media_id:view.media_id,preview_digest:preview.digest,checks:evidence,reason,
        });
        if(action==='bounded_replacement' && replacement) return generationRequest(`/recap-episodes/${selected}/replacement`,{
          preview_digest:replacement.digest,maximum_microusd:replacement.maximum_microusd,disposition_evidence:disposition,reason,
        });
        return generationRequest(`/recap-episodes/${selected}/actions`,{action,expected_revision:view.revision,reason,
          stage_id:view.stage?.id || '',expected_generation:view.stage?.generation || 0,
          attempt_id:attempt,worker_id:action==='reassign_worker'?view.configured_worker_id || '':'',
          ...(alias?{spellings:[{entity_kind:entity.split(':')[0],entity_id:entity.slice(entity.indexOf(':')+1),canonical_token:canonical,aliases:[alias],reusable}]}:{}),
        });
      },action==='review_publish'?'Reviewed edition selected for publication.':'Episode action recorded.');
      setReload(value=>value+1);
    }catch(err){setError(err instanceof Error?err.message:'Action failed. Reload current evidence before trying again.');}
  }
  return <section className="mt-5 border-t border-rule pt-4" aria-label="Recap episode recovery">
    <h4 className="font-display text-name font-bold">Weekly recap episode</h4>
    {records.length>0 && <label className="mt-3 block text-prose">Episode<select className={controlClass+' mt-1'} value={selected} disabled={blocked}
      onChange={event=>{const row=records.find(row=>row.episode_id===event.target.value);setSelected(event.target.value);callback.current(event.target.value,row ? episodeLabel(row) : undefined);}}>
      {!selected && <option value="">Choose an episode</option>}
      {records.map(row=><option key={row.episode_id} value={row.episode_id}>{episodeLabel(row)}</option>)}
    </select></label>}
    {loading && <p role="status" className="mt-3 text-prose text-dim">Loading saved episode evidence…</p>}
    {!loading && !records.length && <p className="mt-3 text-prose text-dim">No saved recap episodes for this league.</p>}
    {error && <p role="alert" className="mt-3 text-prose text-neg-strong">{error}</p>}
    {!selectionOnly && <button type="button" className={secondary+' mt-3'} disabled={blocked || !selected} onClick={()=>setReload(n=>n+1)}>Reload episode status</button>}
    {!selectionOnly && view && <>
      <p className="mt-3 text-prose font-semibold">{view.qualification.passed} of {view.qualification.required} reviewed episodes passed</p>
      <p className="mt-1 text-prose text-dim">{view.qualification.automatic?'Standing automatic publication is active for this league and season.':explanations[view.qualification.reason] || 'Finished previews require explicit review.'}</p>
      <p className="mt-3 text-prose">Stage: {readable(view.stage?.kind || view.episode.lifecycle)}{view.stage?` · ${readable(view.stage.state)}`:''}</p>
      {view.reason && <p className="mt-1 max-w-prose text-prose text-warn-strong">{explanations[view.reason] || (view.reason.startsWith('recap_budget_') ? 'A recap spending limit is holding this episode. Review its limits and outstanding charges.' : readable(view.reason))}</p>}
      {view.reason.startsWith('recap_budget_') && <><p className="mt-2 text-prose">Video needs {money(view.needed_microusd || 0)}; {view.budget?.balances.video_episode_microusd?.remaining_microusd == null?'remaining budget needs accounting review':money(view.budget.balances.video_episode_microusd.remaining_microusd)+' remains in this episode'}.</p>{onRecapBudget ? <button className={secondary + ' mt-2'} onClick={() => onRecapBudget(seriesId,selected)}>Edit recap limits</button> : <a href="#generation-recap-budgets" className="inline-flex min-h-tap items-center text-prose underline">Edit recap limits</a>}</>}
      {view.stage?.result_json && <TechnicalDetails value={JSON.parse(view.stage.result_json)} label="Exact failed evidence"/>}
      {view.attempts.some(a=>a.cost_microusd===null) && <p className="mt-2 text-prose text-warn-strong">Narration response or charge unresolved. Reserved and uncertain costs remain included in this episode’s spending limits.</p>}
      {view.recovery_requests?.map(request=><p key={request.id} className="mt-2 text-prose text-dim">History lookup · {readable(request.state)} · {readable(request.error || 'Waiting for original worker')}<span className="block break-all text-caption">Attempt {request.attempt_id} · Worker {request.worker_id}</span></p>)}
      <div className="mt-3 flex flex-wrap gap-2">{view.actions.map(item=><button key={item} type="button" className={secondary} disabled={blocked} onClick={()=>void open(item)}>{labels[item] || readable(item)}</button>)}</div>
      {action && <form className="mt-4 border-t border-rule pt-4" onSubmit={event=>{event.preventDefault();void submit();}}>
        <h5 className="text-prose font-semibold">{labels[action]}</h5>
        {action==='resume_free' && <><p className="mt-2 text-prose text-dim">Recheck existing narration, then rebuild only free media work. Original script, audio, transcripts and receipts remain saved.</p>
          {view.stage?.kind==='speech_check' && <details className="mt-2"><summary className="min-h-tap cursor-pointer py-2 text-prose">Review an exceptional name spelling</summary>
            <p className="text-prose text-dim">Only the same person’s spelling may be accepted. Wrong scores, missing words or changed meaning require a separate decision.</p>
            <label className="mt-2 block text-prose">Person in this episode<select className={controlClass} value={entity} onChange={e=>setEntity(e.target.value)}><option value="">Choose a person</option>{view.speech_entities?.map(person=><option key={person.kind+':'+person.id} value={person.kind+':'+person.id}>{person.name} · {person.kind}</option>)}</select></label>
            <label className="mt-2 block text-prose">Correct name token<input className={controlClass} value={canonical} onChange={e=>setCanonical(e.target.value)}/></label>
            <label className="mt-2 block text-prose">Reviewed transcript spelling<input className={controlClass} value={alias} onChange={e=>setAlias(e.target.value)}/></label>
            <label className="mt-2 flex min-h-tap items-center gap-2 text-prose"><input type="checkbox" checked={reusable} onChange={e=>setReusable(e.target.checked)}/>Allow this exact person and spelling in later episodes this season</label>
          </details>}</>}
        {action==='bounded_replacement' && <><p className="mt-2 text-prose text-warn-strong">Approves a new complete narration take under the original episode limits. Original uncertain charges remain reserved. No script purchase is included.</p>
          {replacement && <><p className="mt-2 text-prose font-semibold">{replacement.requests} requests · maximum {money(replacement.maximum_microusd)}</p><TechnicalDetails value={replacement.original_requests} label="Original request identities and charges"/>
            <label className="mt-2 block text-prose">Why no unique original result can be recovered<textarea className={controlClass} required minLength={20} maxLength={4000} value={disposition} onChange={e=>setDisposition(e.target.value)}/></label></>}
        </>}
        {action==='review_publish' && preview && <>
          <video controls playsInline preload="metadata" className="mt-3 w-full" src={`/api/admin/generation/recap-episodes/${selected}/preview/${view.media_id}/video.mp4`}><track kind="captions" srcLang="en" label="English" src={`/api/admin/generation/recap-episodes/${selected}/preview/${view.media_id}/captions.vtt`}/></video>
          <p className="mt-3 whitespace-pre-wrap text-prose">{preview.article.markdown}</p>
          <p className="mt-3 text-prose text-dim">Record actual review evidence for each gate. Emulation or synthetic output does not establish physical phone or message-preview acceptance.</p>
          {Object.entries(checks).map(([key,label])=><label key={key} className="mt-3 block text-prose">{label}<textarea className={controlClass+' mt-1'} required minLength={20} maxLength={2000} value={evidence[key] || ''} onChange={e=>setEvidence(old=>({...old,[key]:e.target.value}))}/></label>)}
        </>}
        {action==='skip_video' && <p className="mt-2 text-prose text-dim">Stops unfinished media work and retains a valid article. Requests already sent keep their charges and reservations.</p>}
        {action==='disable_future_sharing' && <p className="mt-2 text-prose text-dim">Stops links for future episodes. Existing edition access is unchanged.</p>}
        {action==='restore_access' && <p className="mt-2 text-prose text-dim">Explicitly restores this edition’s link only. It does not approve new media, future links or paid work.</p>}
        {action==='resume_recovered_audio' && <p className="mt-2 text-prose text-dim">Verify every recovered audio chunk against its saved request and hash, then run free speech, timing and media checks. Uncertain charges stay reserved. Publication still requires review.</p>}
        {['reconcile_request','reassign_worker'].includes(action) && <label className="mt-2 block text-prose">Exact saved attempt<select className={controlClass} value={attempt} onChange={e=>setAttempt(e.target.value)}>{view.attempts.map(item=><option key={item.id} value={item.id}>{item.id} · {readable(item.state)} · {item.worker_id}</option>)}</select></label>}
        {action==='reassign_worker' && <p className="mt-2 text-prose text-warn-strong">Transfer this attempt’s recovery ownership to configured worker {view.configured_worker_id}. Revoke previous recovery leases; preserve receipts and charges.</p>}
        {action==='reconcile_request' && <p className="mt-2 text-prose text-dim">Reconciles saved evidence. Missing responses require exact request/history retrieval by the original worker. This action never resends narration.</p>}
        <label className="mt-3 block text-prose">Reason for episode action<input className={controlClass+' mt-1'} required maxLength={1000} value={reason} onChange={e=>setReason(e.target.value)}/></label>
        <div className="mt-3 flex flex-wrap gap-2"><button type="submit" className={secondary} disabled={blocked || !reason.trim() || (!!alias && (!entity || !canonical)) || (action==='review_publish' && !preview) || (action==='bounded_replacement' && !replacement)}>
          {action==='resume_free'?'Confirm free recovery':action==='review_publish'?'Review and publish':action==='bounded_replacement'?'Approve bounded replacement':'Confirm '+(labels[action] || action).toLowerCase()}</button>
          <button type="button" className={secondary} onClick={()=>setAction('')}>Cancel</button></div>
      </form>}
    </>}
  </section>;
}
