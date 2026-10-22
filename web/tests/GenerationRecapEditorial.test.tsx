import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { GenerationRecapEditorial } from '../components/admin/GenerationRecapEditorial';
const request=vi.fn();
vi.mock('@/lib/api',()=>({generationRequest:(...args:unknown[])=>request(...args)}));
const run=vi.fn(async(action:()=>Promise<unknown>)=>{await action();});
const source={operation_id:'script',script:{opening:'Opening',closing:'Closing',article_digest:'article',premises:[{premise:'Office comedy',punchline:'Late meeting',owner_ids:['owner'],callback_reason:''}],segments:[{id:'segment',text:'Team scored ten.',claim_ids:['score'],owner_ids:['owner'],matchup_ids:['matchup'],spoken_numbers:[{claim_id:'score',field:'points',exact:'10',spoken:'ten'}]}]},claims:{claims:[{id:'score',values:{points:'10',margin:'2'},spoken_values:{points:'ten',margin:'two'}}]},review:{issues:['Check score wording']}};
const props={episodeId:'episode',operationId:'script',busy:false,run};
beforeEach(()=>{request.mockReset();run.mockClear();request.mockImplementation(async(path:string)=>path.includes('editorial-source')?structuredClone(source):{preview_id:'preview',digest:'digest',script_digest:'script-digest',narration_maximum_microusd:100000});});
async function open(){fireEvent.click(screen.getByRole('button',{name:'Edit saved script'}));await screen.findByLabelText('Opening');}
function review(){for(const input of screen.getAllByRole('checkbox'))fireEvent.click(input);fireEvent.change(screen.getByLabelText('Reason for correction'),{target:{value:'Reviewed against saved article and facts.'}});}
it('edits saved text without spending and requires exact preview before approval',async()=>{
  // Mutation: editing starts paid work or approval submits the mutable script instead of the preview digest.
  render(<GenerationRecapEditorial {...props}/>);await open();
  fireEvent.change(screen.getByLabelText('Segment 1'),{target:{value:'Corrected ten points.'}});review();
  expect(run).not.toHaveBeenCalled();expect(request).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button',{name:'Prepare free preview'}));
  const approve=await screen.findByRole('button',{name:'Approve corrected script'});
  expect(request).toHaveBeenCalledWith('/recap-episodes/episode/editorial-preview',expect.objectContaining({script:expect.objectContaining({segments:[expect.objectContaining({text:'Corrected ten points.',owner_ids:['owner']})]})}));
  expect(run).not.toHaveBeenCalled();fireEvent.click(approve);
  await waitFor(()=>expect(request).toHaveBeenCalledWith('/recap-episodes/episode/editorial-approve',{preview_id:'preview',preview_digest:'digest',reason:'Reviewed against saved article and facts.'}));
});
it('invalidates prepared approval when text changes',async()=>{
  // Mutation: an old preview remains approvable after editing.
  render(<GenerationRecapEditorial {...props}/>);await open();review();fireEvent.click(screen.getByRole('button',{name:'Prepare free preview'}));await screen.findByRole('button',{name:'Approve corrected script'});
  fireEvent.change(screen.getByLabelText('Opening'),{target:{value:'Changed opening'}});
  expect(screen.queryByRole('button',{name:'Approve corrected script'})).not.toBeInTheDocument();
});
it('ignores source returned after episode selection changes',async()=>{
  // Mutation: a previous episode source overwrites the current editor.
  let finish!:(value:unknown)=>void;request.mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
  const view=render(<GenerationRecapEditorial {...props}/>);fireEvent.click(screen.getByRole('button',{name:'Edit saved script'}));
  view.rerender(<GenerationRecapEditorial {...props} episodeId="new-episode"/>);
  await act(async()=>{finish(source);});expect(screen.queryByLabelText('Opening')).not.toBeInTheDocument();
});

it('selects exact decimal string claim fields and preserves premise metadata',async()=>{
  // Mutation: numeric references exclude string decimals or premise edits discard owner metadata.
  render(<GenerationRecapEditorial {...props}/>);await open();
  fireEvent.change(screen.getByLabelText('Number reference 1'),{target:{value:JSON.stringify(['score','margin'])}});
  fireEvent.change(screen.getByLabelText('Premise 1'),{target:{value:'New premise'}});review();
  fireEvent.click(screen.getByRole('button',{name:'Prepare free preview'}));
  await screen.findByRole('button',{name:'Approve corrected script'});
  expect(request).toHaveBeenCalledWith('/recap-episodes/episode/editorial-preview',expect.objectContaining({script:expect.objectContaining({premises:[expect.objectContaining({premise:'New premise',owner_ids:['owner']})],segments:[expect.objectContaining({spoken_numbers:[{claim_id:'score',field:'margin',exact:'2',spoken:'two'}]})]})}));
});

it('shows saved article as readable text for agreement review',async()=>{
  // Mutation: article evidence is omitted or exposed only as raw JSON.
  request.mockResolvedValue({...source,source:{published_article:{markdown:'Saved article: Team won by two points.'}}});
  render(<GenerationRecapEditorial {...props}/>);await open();
  fireEvent.click(screen.getByText('Read saved article'));
  const article=screen.getByText('Saved article: Team won by two points.');
  expect(article).toBeVisible();expect(article.tagName).not.toBe('PRE');
});
