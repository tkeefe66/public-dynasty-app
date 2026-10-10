import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { GenerationRecapEpisode } from '../components/admin/GenerationRecapEpisode';

const request=vi.fn();
vi.mock('@/lib/api',()=>({generationRequest:(...args:unknown[])=>request(...args)}));
const run=vi.fn(async(action:()=>Promise<unknown>)=>{await action();});
const changed=vi.fn();
const episode={episode_id:'episode',season:2026,week:4,lifecycle:'speech_check',hold:''};
const detail={episode,revision:'a'.repeat(64),authority_revision:2,media_id:null,
  stage:{id:'speech',kind:'speech_check',state:'held',generation:3,reason:'speech_verification_failed',result_json:'{"report":{"issues":["spoken_score_mismatch"]}}'},
  stages:[],attempts:[],qualification:{passed:2,required:3,automatic:false,reason:'reviewed_episodes_required'},
  reason:'speech_verification_failed',actions:['resume_free','skip_video','disable_future_sharing']};
beforeEach(()=>{request.mockReset();run.mockClear();changed.mockClear();request.mockImplementation(async(path:string)=>path.includes('?')?{records:[episode]}:detail);});

it('selects actual episode and names exact stage evidence and free action',async()=>{
  // Mutation: omit selected episode callback/budget binding or show generic paid Retry.
  render(<GenerationRecapEpisode seriesId="series" busy={false} run={run} version={0} onEpisodeChange={changed}/>);
  expect(await screen.findByText('2 of 3 reviewed episodes passed')).toBeInTheDocument();
  expect(screen.getByText(/spoken_score_mismatch/)).toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Resume free work'})).toBeInTheDocument();
  expect(screen.queryByRole('button',{name:/Retry/})).not.toBeInTheDocument();
  expect(changed).toHaveBeenCalledWith('episode', 'Week 4 · 2026');
});

it('submits free recovery with exact episode and generation fences',async()=>{
  // Mutation: recovery submits no state fence or purchases replacement from a free button.
  render(<GenerationRecapEpisode seriesId="series" busy={false} run={run} version={0} onEpisodeChange={changed}/>);
  fireEvent.click(await screen.findByRole('button',{name:'Resume free work'}));
  fireEvent.change(screen.getByLabelText('Reason for episode action'),{target:{value:'Fixed local renderer dependency'}});
  fireEvent.click(screen.getByRole('button',{name:'Confirm free recovery'}));
  await waitFor(()=>expect(request).toHaveBeenCalledWith('/recap-episodes/episode/actions',expect.objectContaining({action:'resume_free',expected_revision:'a'.repeat(64),stage_id:'speech',expected_generation:3})));
  expect(request.mock.calls.some(([path])=>String(path).endsWith('/replacement'))).toBe(false);
});

it('discards old league responses before changing selected episode',async()=>{
  // Mutation: slow earlier league load overwrites current episode/budget selection.
  let finish:(value:unknown)=>void=()=>{};
  request.mockImplementation((path:string)=>path.includes('series_id=old')?new Promise(resolve=>{finish=resolve;}):Promise.resolve(path.includes('?')?{records:[]}:detail));
  const view=render(<GenerationRecapEpisode seriesId="old" busy={false} run={run} version={0} onEpisodeChange={changed}/>);
  view.rerender(<GenerationRecapEpisode seriesId="new" busy={false} run={run} version={0} onEpisodeChange={changed}/>);
  await screen.findByText('No saved recap episodes for this league.');
  finish({records:[episode]});
  await waitFor(()=>expect(screen.queryByText('Week 4 · 2026')).not.toBeInTheDocument());
  expect(changed).not.toHaveBeenCalledWith('episode');
});
