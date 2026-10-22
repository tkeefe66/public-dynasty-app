import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { GenerationApproval } from '../components/admin/GenerationApproval';

it('shows replacement dollar ceiling and original charges before paid approval',()=>{
  const approve=vi.fn();
  render(<GenerationApproval preview={{id:'preview',digest:'digest',max_calls:4,expires_at:Date.now()/1000+900,
    prior_cost_microusd:404826,maximum_additional_microusd:2429952,cost_scope:'script_only_narration_not_included',
    items:[{key:'candidate',label:'Week 6',league_id:'synthetic',feature:'recap_video',event:'6',max_calls:4,
      max_tokens_per_call:8192,model:'saved-model',hold:'manual_approval_required',blocked_by:[]}]}}
    leagues={[]} busy={false} onApprove={approve} onBack={vi.fn()}/>);
  expect(screen.getByText('Maximum additional script cost: $2.429952.')).toBeInTheDocument();
  expect(screen.getByText(/Previous script requests already cost \$0.404826/)).toBeInTheDocument();
  expect(screen.getByText(/Narration is excluded/)).toBeInTheDocument();
  expect(screen.queryByText(/not a dollar quote/)).not.toBeInTheDocument();
  expect(approve).not.toHaveBeenCalled();
});
