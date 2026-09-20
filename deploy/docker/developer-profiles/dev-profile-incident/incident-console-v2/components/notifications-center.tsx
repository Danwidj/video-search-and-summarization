// SPDX-License-Identifier: Apache-2.0

'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';

interface Notice { id: number; incident_id: string; model_run_id: string; severity: number; created_at: string; acknowledged: boolean }

export function NotificationsCenter() {
  const [items, setItems] = useState<Notice[]>([]); const [error, setError] = useState('');
  const load = () => fetch('/api/notifications', { cache: 'no-store' }).then((r) => r.json()).then((p: { notifications?: Notice[]; error?: string }) => { if (!p.notifications) throw new Error(p.error); setItems(p.notifications); }).catch((e: Error) => setError(e.message));
  useEffect(() => { void load(); const timer = window.setInterval(load, 30000); return () => window.clearInterval(timer); }, []);
  async function acknowledge(id?: number) { await fetch('/api/notifications', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(id ? { id } : { all: true }) }); void load(); }
  return <div className="mx-auto max-w-4xl px-6 py-10 lg:px-12"><div className="flex items-end justify-between"><div><p className="font-mono text-xs uppercase tracking-[.2em] text-moss">Attention queue</p><h1 className="mt-2 text-4xl font-semibold">Notifications</h1></div>{items.some((n) => !n.acknowledged) && <button className="action bg-white" onClick={() => void acknowledge()} type="button">Acknowledge all</button>}</div>{error && <p className="mt-8 text-clay">{error}</p>}<div className="mt-8 space-y-3">{items.length === 0 && !error ? <p className="rounded-2xl border border-dashed border-ink/15 p-10 text-center text-ink/50">No notifications yet.</p> : items.map((n) => <article className={`flex flex-col gap-4 rounded-2xl border p-5 sm:flex-row sm:items-center sm:justify-between ${n.acknowledged ? 'border-ink/8 bg-white/50' : 'border-clay/25 bg-white'}`} key={n.id}><div><p className="font-semibold">Severity {n.severity} report verified</p><p className="mt-1 text-xs text-ink/45">{new Date(n.created_at).toLocaleString()} · {n.incident_id}</p></div><div className="flex gap-3"><Link className="text-sm font-semibold text-moss" href={`/reports/${encodeURIComponent(n.incident_id)}?run=${encodeURIComponent(n.model_run_id)}`}>Open report</Link>{!n.acknowledged && <button className="text-sm text-ink/50" onClick={() => void acknowledge(n.id)} type="button">Acknowledge</button>}</div></article>)}</div></div>;
}
