// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useState } from 'react';
import { Badge } from '@/components/ui/badge';

type OverallStatus = 'checking' | 'ready' | 'degraded';

export function HealthStrip() {
  const [status, setStatus] = useState<OverallStatus>('checking');

  useEffect(() => {
    const controller = new AbortController();

    fetch('/api/health', { cache: 'no-store', signal: controller.signal })
      .then((response) => response.json() as Promise<{ status?: OverallStatus }>)
      .then((payload) => setStatus(payload.status === 'ready' ? 'ready' : 'degraded'))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === 'AbortError')) setStatus('degraded');
      });

    return () => controller.abort();
  }, []);

  const label = status === 'checking' ? 'Checking services' : status === 'ready' ? 'Systems ready' : 'Setup needed';

  return (
    <Badge
      variant="outline"
      className="gap-2 rounded-full border-ink/10 bg-white/70 px-3 py-1.5 text-xs font-semibold text-foreground shadow-none"
    >
      <span className={`h-2 w-2 rounded-full ${status === 'ready' ? 'bg-signal' : status === 'checking' ? 'bg-amber-400' : 'bg-clay'}`} />
      {label}
    </Badge>
  );
}
