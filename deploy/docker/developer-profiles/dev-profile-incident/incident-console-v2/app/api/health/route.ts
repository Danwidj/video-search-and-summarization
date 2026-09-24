// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getServiceConfiguration, isR2Configured, isSupabaseConfigured } from '@/lib/env';
import { GatewayClient } from '@/lib/gateway/client';
import { PostgrestClient } from '@/lib/postgrest/client';

export const dynamic = 'force-dynamic';

export async function GET() {
  const config = getServiceConfiguration();
  const agentConfigured = Boolean(config.agentUrl);
  const gatewayConfigured = Boolean(config.gatewayUrl);
  const supabaseConfigured = isSupabaseConfigured(config);
  const r2Configured = isR2Configured(config);

  const [agentReachable, gatewayReachable, postgrestReachable] = await Promise.all([
    config.agentUrl
      ? fetch(`${config.agentUrl.replace(/\/$/, '')}/health`, { cache: 'no-store' })
          .then((response) => response.ok)
          .catch(() => false)
      : Promise.resolve(false),
    config.gatewayUrl ? new GatewayClient(config.gatewayUrl).health() : Promise.resolve(false),
    config.supabaseUrl && config.supabaseServiceRoleKey
      ? new PostgrestClient(config.supabaseUrl, config.supabaseServiceRoleKey).health()
      : Promise.resolve(false),
  ]);

  const gatewayReady = config.analysisMode === 'agent' ? true : gatewayReachable;
  const ready = agentReachable && gatewayReady && postgrestReachable && r2Configured;

  return NextResponse.json(
    {
      status: ready ? 'ready' : 'degraded',
      services: {
        agent: { configured: agentConfigured, reachable: agentReachable },
        gateway: { configured: gatewayConfigured, reachable: gatewayReachable },
        postgrest: { configured: supabaseConfigured, reachable: postgrestReachable },
        r2: { configured: r2Configured },
      },
    },
    { status: ready ? 200 : 503 },
  );
}
