"use client";

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { GenerationControl } from './GenerationControl';
import styles from './AdminWorkspace.module.css';

const sections = [
  { id: 'writing', label: 'AI writing' },
  { id: 'leagues', label: 'Leagues' },
  { id: 'users', label: 'Users' },
  { id: 'budget', label: 'Monthly LLM budget' },
] as const;
type Section = typeof sections[number]['id'];
function sectionFromUrl(): Section {
  const value = new URLSearchParams(window.location.search).get('tab');
  return sections.find(section => section.id === value)?.id ?? 'writing';
}

export function AdminWorkspace({ counts, backup, leagues, users, budget }: {
  counts: { leagues: number | null; users: number | null };
  backup: ReactNode; leagues: ReactNode; users: ReactNode; budget: ReactNode;
}) {
  const [section, setSection] = useState<Section>('writing');
  const [busy, setBusy] = useState(false);
  const [budgetVisited, setBudgetVisited] = useState(false);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  useEffect(() => {
    const sync = () => setSection(sectionFromUrl());
    sync();
    window.addEventListener('popstate', sync);
    return () => window.removeEventListener('popstate', sync);
  }, []);
  useEffect(() => { if (section === 'budget') setBudgetVisited(true); }, [section]);
  function select(next: Section) {
    if (busy || next === section) return;
    const url = new URL(window.location.href);
    url.searchParams.set('tab', next);
    window.history.pushState(null, '', url);
    setSection(next);
  }
  return <section className={styles.workspace}>
    <header className={styles.header}><div><h1>Admin</h1><p>Manage your writing, leagues, and people.</p></div>{backup}</header>
    <div role="tablist" aria-label="Admin sections" className={styles.tabs}>
      {sections.map((item, index) => <button key={item.id} ref={element => { tabs.current[index] = element; }} role="tab" id={`admin-tab-${item.id}`} aria-controls={`admin-panel-${item.id}`} aria-selected={section === item.id} tabIndex={section === item.id ? 0 : -1} disabled={busy} onClick={() => select(item.id)} onKeyDown={event => {
        const target = event.key === 'Home' ? 0 : event.key === 'End' ? sections.length - 1 : event.key === 'ArrowRight' ? (index + 1) % sections.length : event.key === 'ArrowLeft' ? (index + sections.length - 1) % sections.length : null;
        if (target === null) return;
        event.preventDefault(); select(sections[target].id); tabs.current[target]?.focus();
      }}>{item.label}{(item.id === 'leagues' || item.id === 'users') && <span>{counts[item.id]}</span>}</button>)}
    </div>
    {/* Keep the single AI controller mounted so changing Admin tabs cannot reset
        mutation locks or the selected recap league and episode. */}
    <div role="tabpanel" id={`admin-panel-${section === 'budget' ? 'budget' : 'writing'}`} aria-labelledby={`admin-tab-${section === 'budget' ? 'budget' : 'writing'}`} tabIndex={0} hidden={section !== 'writing' && section !== 'budget'}>
      <GenerationControl adminSection={section === 'budget' ? 'budget' : 'writing'} onOpenBudget={() => select('budget')} onBusyChange={setBusy} budgetContent={budgetVisited || section === 'budget' ? budget : null} />
    </div>
    <div role="tabpanel" id={`admin-panel-${section === 'budget' ? 'writing' : 'budget'}`} aria-labelledby={`admin-tab-${section === 'budget' ? 'writing' : 'budget'}`} hidden />
    <div role="tabpanel" id="admin-panel-leagues" aria-labelledby="admin-tab-leagues" tabIndex={0} hidden={section !== 'leagues'}>{leagues}</div>
    <div role="tabpanel" id="admin-panel-users" aria-labelledby="admin-tab-users" tabIndex={0} hidden={section !== 'users'}>{users}</div>
  </section>;
}
