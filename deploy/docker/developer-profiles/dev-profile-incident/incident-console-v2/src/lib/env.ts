// SPDX-License-Identifier: Apache-2.0

export interface ServiceConfiguration {
  analysisMode: 'gateway' | 'agent';
  agentUrl?: string;
  /** Seconds an agent-mode analysis may run (INCIDENT_ANALYSIS_TIMEOUT_SECONDS); undefined means the default, 600. */
  analysisTimeoutSeconds?: number;
  gatewayUrl?: string;
  vlmModel: string;
  supabaseUrl?: string;
  supabaseServiceRoleKey?: string;
  r2AccountId?: string;
  r2AccessKey?: string;
  r2SecretKey?: string;
  r2Bucket?: string;
}

function optionalEnvironmentValue(name: string): string | undefined {
  const value = process.env[name]?.trim();
  return value || undefined;
}

/** A positive, finite number of seconds, else undefined (a blank or bad value leaves the default). */
function positiveSeconds(name: string): number | undefined {
  const value = Number(optionalEnvironmentValue(name));
  return Number.isFinite(value) && value > 0 ? value : undefined;
}

export function getServiceConfiguration(): ServiceConfiguration {
  const rawMode = optionalEnvironmentValue('ANALYSIS_MODE')?.toLowerCase();
  const analysisMode: 'gateway' | 'agent' = rawMode === 'agent' ? 'agent' : 'gateway';

  return {
    analysisMode,
    agentUrl: optionalEnvironmentValue('INCIDENT_AGENT_BASE_URL'),
    analysisTimeoutSeconds: positiveSeconds('INCIDENT_ANALYSIS_TIMEOUT_SECONDS'),
    gatewayUrl: optionalEnvironmentValue('VLM_GATEWAY_URL'),
    vlmModel: optionalEnvironmentValue('VLM_MODEL') || 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning',
    supabaseUrl: optionalEnvironmentValue('INCIDENT_SUPABASE_URL'),
    supabaseServiceRoleKey: optionalEnvironmentValue('INCIDENT_SUPABASE_SERVICE_ROLE_KEY'),
    r2AccountId: optionalEnvironmentValue('R2_ACCOUNT_ID'),
    r2AccessKey: optionalEnvironmentValue('R2_ACCESS_KEY'),
    r2SecretKey: optionalEnvironmentValue('R2_SECRET_KEY'),
    r2Bucket: optionalEnvironmentValue('R2_BUCKET'),
  };
}

/** Flag INCIDENT_EVIDENCE_PROPOSALS_ENABLED (off unless 1, true, yes or on), read on every call so a restart is the only change needed. */
export function isEvidenceProposalsEnabled(): boolean {
  return /^(1|true|yes|on)$/i.test(optionalEnvironmentValue('INCIDENT_EVIDENCE_PROPOSALS_ENABLED') ?? '');
}

/** Flag INCIDENT_CHAT_STEPS_ENABLED (off unless 1, true, yes or on), read on every request. */
export function isChatStepsEnabled(req?: Request): boolean {
  const header = req?.headers.get('x-chat-steps')?.trim().toLowerCase();
  if (header === '1' || header === 'true' || header === 'yes' || header === 'on') return true;
  return /^(1|true|yes|on)$/i.test(optionalEnvironmentValue('INCIDENT_CHAT_STEPS_ENABLED') ?? '');
}

export function isSupabaseConfigured(config: ServiceConfiguration): boolean {
  return Boolean(config.supabaseUrl && config.supabaseServiceRoleKey);
}

export function isR2Configured(config: ServiceConfiguration): boolean {
  return Boolean(config.r2AccountId && config.r2AccessKey && config.r2SecretKey && config.r2Bucket);
}

/** The configuration an analysis needs (its mode's model URL and Supabase); throws naming what is missing. */
export function requireAnalysisConfiguration(config: ServiceConfiguration = getServiceConfiguration()): ServiceConfiguration {
  if (config.analysisMode === 'agent') {
    if (!config.agentUrl) throw new Error('INCIDENT_AGENT_BASE_URL is not configured');
  } else {
    if (!config.gatewayUrl) throw new Error('VLM_GATEWAY_URL is not configured');
  }
  if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
  return config;
}
