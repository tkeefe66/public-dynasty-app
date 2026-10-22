import { useEffect, useRef, useState } from 'react';
import { generationRequest } from '@/lib/api';
import { ActionProps, controlClass, money, secondary } from './GenerationShared';

interface NumberReference { claim_id:string; field:string; exact:unknown; spoken:string }
interface Segment { id:string; text:string; spoken_numbers:NumberReference[]; [key:string]:unknown }
interface Premise { premise:string; punchline:string; owner_ids:string[]; callback_reason?:string }
interface Script { opening:string; closing:string; segments:Segment[]; premises:(string|Premise)[]; [key:string]:unknown }
interface Source { operation_id:string; script:Script; source?:{published_article?:{markdown?:string}}; claims:{claims:{id:string; values:Record<string,unknown>; spoken_values?:Record<string,string>}[]}; review?:{issues?:unknown[]} }
interface Preview { preview_id:string; digest:string; script_digest:string; narration_maximum_microusd:number }
const checks={facts:'I checked every factual claim.',article_agreement:'I compared the script with the saved article.',coverage:'I checked every league member and matchup is covered.',spoken_numbers:'I checked every spoken number against its source.',premise_variety:'I reviewed the variety of comic premises.'};

export function GenerationRecapEditorial({episodeId,operationId,busy,run,onApproved}:Pick<ActionProps,'busy'|'run'> & {episodeId:string;operationId:string;onApproved?:()=>void}) {
  const [source,setSource]=useState<Source|null>(null);
  const [script,setScript]=useState<Script|null>(null);
  const [review,setReview]=useState<Record<string,boolean>>({});
  const [reason,setReason]=useState('');
  const [preview,setPreview]=useState<Preview|null>(null);
  const [pending,setPending]=useState(false);
  const [error,setError]=useState('');
  const request=useRef(0);
  useEffect(()=>{request.current+=1;setSource(null);setScript(null);setReview({});setReason('');setPreview(null);setPending(false);setError('');return()=>{request.current+=1;};},[episodeId,operationId]);
  function invalidate(){request.current+=1;setPreview(null);setError('');}
  function edit(next:Script){invalidate();setScript(next);setReview({});}
  async function load(){
    const token=++request.current;setPending(true);setError('');
    try{const value=await generationRequest<Source>(`/recap-episodes/${episodeId}/editorial-source?operation_id=${encodeURIComponent(operationId)}`);if(token===request.current){setSource(value);setScript(value.script);}}
    catch(err){if(token===request.current)setError(err instanceof Error?err.message:'Saved script could not load. Reload episode status and try again.');}
    finally{if(token===request.current)setPending(false);}
  }
  async function prepare(){
    if(!script || !ready || blocked)return;
    const token=++request.current;setPending(true);setError('');setPreview(null);
    try{const value=await generationRequest<Preview>(`/recap-episodes/${episodeId}/editorial-preview`,{operation_id:operationId,script,checks:review,reason});if(token===request.current)setPreview(value);}
    catch(err){if(token===request.current)setError(err instanceof Error?err.message:'Correction did not pass validation. Review the script and try again.');}
    finally{if(token===request.current)setPending(false);}
  }
  async function approve(){
    if(!preview || blocked)return;
    const token=++request.current;setPending(true);setError('');
    try{await run(()=>generationRequest(`/recap-episodes/${episodeId}/editorial-approve`,{preview_id:preview.preview_id,preview_digest:preview.digest,reason}),'Corrected script approved. Publication still requires separate review.');if(token===request.current){setPreview(null);onApproved?.();}}
    catch(err){if(token===request.current){setPreview(null);setError(err instanceof Error?err.message:'Approval failed. Prepare a fresh preview before trying again.');}}
    finally{if(token===request.current)setPending(false);}
  }
  const blocked=busy || pending;
  const ready=Object.keys(checks).every(key=>review[key]) && !!reason.trim();
  return <section className="mt-4 border-t border-rule pt-4" aria-label="Correct saved video script">
    <h5 className="font-display text-name font-bold">Correct saved video script</h5>
    <p className="mt-2 text-prose">Edit and validate the saved script for free. No new AI script requests. Approval can authorize narration within the displayed limit; member-only publication requires separate review.</p>
    {!script && <button type="button" className={secondary+' mt-3'} disabled={blocked} onClick={()=>void load()}>Edit saved script</button>}
    {pending && <p role="status" className="mt-2 text-prose">Checking saved script…</p>}
    {error && <p role="alert" className="mt-2 text-prose text-neg-strong">{error}</p>}
    {script && source && <>
      {source.source?.published_article?.markdown && <details className="mt-3"><summary className="min-h-tap cursor-pointer py-2 text-prose font-semibold">Read saved article</summary><p className="max-w-prose whitespace-pre-wrap text-prose">{source.source.published_article.markdown}</p></details>}
      {!!source.review?.issues?.length && <div className="mt-3 text-prose"><p className="font-semibold">Saved review findings</p><ul className="list-disc pl-5">{source.review.issues.map((issue,index)=><li key={index}>{typeof issue==='string'?issue:issue && typeof issue==='object'?Object.entries(issue).filter(([,value])=>typeof value==='string').map(([key,value])=>`${key.replaceAll('_',' ')}: ${value}`).join(' · '):String(issue)}</li>)}</ul></div>}
      <fieldset disabled={blocked} className="mt-3 space-y-3">
        <label className="block text-prose">Opening<textarea rows={4} className={controlClass} value={script.opening} onChange={e=>edit({...script,opening:e.target.value})}/></label>
        {script.segments.map((segment,index)=><div key={segment.id} className="border-t border-rule pt-3">
          <label className="block text-prose">Segment {index+1}<textarea rows={6} className={controlClass} value={segment.text} onChange={e=>edit({...script,segments:script.segments.map((item,i)=>i===index?{...item,text:e.target.value}:item)})}/></label>
          {!!segment.spoken_numbers?.length && <details className="mt-2"><summary className="min-h-tap cursor-pointer py-2 text-prose">Check number references</summary>{segment.spoken_numbers.map((number,numberIndex)=><label key={numberIndex} className="mt-2 block text-prose">Number reference {numberIndex+1}<select className={controlClass} value={JSON.stringify([number.claim_id,number.field])} onChange={e=>{
            const [claimId,field]=JSON.parse(e.target.value) as [string,string];const claim=source.claims.claims.find(item=>item.id===claimId);if(!claim)return;
            edit({...script,segments:script.segments.map((item,i)=>i===index?{...item,spoken_numbers:item.spoken_numbers.map((ref,j)=>j===numberIndex?{...ref,claim_id:claimId,field,exact:claim.values[field],spoken:claim.spoken_values?.[field] || String(claim.values[field])}:ref)}:item)});
          }}><option value={JSON.stringify([number.claim_id,number.field])}>{number.claim_id} · {number.field}: {String(number.exact)} → {number.spoken}</option>{source.claims.claims.flatMap(claim=>Object.entries(claim.values).filter(([field])=>!!claim.spoken_values?.[field]).map(([field,value])=><option key={claim.id+field} value={JSON.stringify([claim.id,field])}>{claim.id} · {field}: {String(value)} → {claim.spoken_values?.[field]}</option>))}</select></label>)}</details>}
        </div>)}
        <label className="block text-prose">Closing<textarea rows={4} className={controlClass} value={script.closing} onChange={e=>edit({...script,closing:e.target.value})}/></label>
        {!!script.premises?.length && <div><p className="text-prose font-semibold">Comic premises</p>{script.premises.map((premise,index)=><div key={index} className="mt-2 flex items-start gap-2">{typeof premise==='string'?<label className="flex-1 text-prose">Premise {index+1}<textarea className={controlClass} value={premise} onChange={e=>edit({...script,premises:script.premises.map((item,i)=>i===index?e.target.value:item)})}/></label>:<div className="flex-1 space-y-2">{(['premise','punchline','callback_reason'] as const).map(field=><label key={field} className="block text-prose">{field==='premise'?`Premise ${index+1}`:field==='punchline'?`Punchline ${index+1}`:`Reason for callback ${index+1}`}<textarea className={controlClass} value={premise[field] || ''} onChange={e=>edit({...script,premises:script.premises.map((item,i)=>i===index?{...premise,[field]:e.target.value}:item)})}/></label>)}</div>}<button type="button" className={secondary} onClick={()=>edit({...script,premises:script.premises.filter((_,i)=>i!==index)})}>Remove premise {index+1}</button></div>)}</div>}
        <p className="text-prose text-dim">Confirm these checks after your final edit. Changing script text resets the checks.</p>
        {Object.entries(checks).map(([key,label])=><label key={key} className="flex min-h-tap items-center gap-2 text-prose"><input type="checkbox" checked={!!review[key]} onChange={e=>{invalidate();setReview(old=>({...old,[key]:e.target.checked}));}}/>{label}</label>)}
        <label className="block text-prose">Reason for correction<textarea className={controlClass} maxLength={1000} value={reason} onChange={e=>{invalidate();setReason(e.target.value);}}/></label>
      </fieldset>
      <button type="button" className={secondary+' mt-3'} disabled={blocked || !ready} onClick={()=>void prepare()}>Prepare free preview</button>
      {preview && <div className="mt-4 border border-rule-strong p-3"><p className="text-prose font-semibold">No script requests · narration maximum {money(preview.narration_maximum_microusd)}</p><p className="mt-2 text-prose">Approve this exact corrected script and allow narration under existing spending caps. This does not publish the episode.</p><button type="button" className={secondary+' mt-3'} disabled={blocked || !ready || !Number.isFinite(preview.narration_maximum_microusd)} onClick={()=>void approve()}>Approve corrected script</button></div>}
    </>}
  </section>;
}
