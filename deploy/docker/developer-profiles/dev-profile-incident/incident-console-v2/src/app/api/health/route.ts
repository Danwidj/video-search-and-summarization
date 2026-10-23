// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbHealth } from '@/lib/adapters/supabase';
import { getServiceConfiguration, isR2Configured } from '@/lib/env';
import { GatewayClient } from '@/lib/gateway/client';

export const dynamic = 'force-dynamic';

export async function GET() {
  const config = getServiceConfiguration();
  const agentConfigured = Boolean(config.agentUrl);
  const gatewayConfigured = Boolean(config.gatewayUrl);
  const r2Configured = isR2Configured(config);

  const [agentReachable, gatewayReachable, database] = await Promise.all([
    config.agentUrl
      ? fetch(`${config.agentUrl.replace(/\/$/, '')}/health`, { cache: 'no-store' })
          .then((response) => response.ok)
          .catch(() => false)
      : Promise.resolve(false),
    config.gatewayUrl ? new GatewayClient(config.gatewayUrl).health() : Promise.resolve(false),
    getDbHealth(config).checkHealth(),
  ]);

  const gatewayReady = config.analysisMode === 'agent' ? true : gatewayReachable;
  const ready = agentReachable && gatewayReady && database.reachable && r2Configured;

  return NextResponse.json(
    {
      status: ready ? 'ready' : 'degraded',
      services: {
        agent: { configured: agentConfigured, reachable: agentReachable },
        gateway: { configured: gatewayConfigured, reachable: gatewayReachable },
        postgrest: database,
        r2: { configured: r2Configured },
      },
    },
    { status: ready ? 200 : 503 },
  );
}
