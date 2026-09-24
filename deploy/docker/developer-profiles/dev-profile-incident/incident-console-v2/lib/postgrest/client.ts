// SPDX-License-Identifier: Apache-2.0

export class PostgrestClient {
  private readonly restUrl: string;
  private readonly serviceRoleKey: string;

  constructor(baseUrl: string, serviceRoleKey: string) {
    this.restUrl = `${baseUrl.replace(/\/$/, '')}/rest/v1`;
    this.serviceRoleKey = serviceRoleKey;
  }

  private headers(): HeadersInit {
    return {
      apikey: this.serviceRoleKey,
      Authorization: `Bearer ${this.serviceRoleKey}`,
      'Content-Type': 'application/json',
    };
  }

  async health(signal?: AbortSignal): Promise<boolean> {
    try {
      const response = await fetch(`${this.restUrl}/videos?select=id&limit=1`, {
        headers: this.headers(),
        cache: 'no-store',
        signal,
      });
      return response.ok;
    } catch {
      return false;
    }
  }

  private async request(path: string, init: RequestInit = {}): Promise<unknown> {
    let response: Response;
    try {
      response = await fetch(`${this.restUrl}${path}`, {
        ...init,
        headers: { ...this.headers(), Prefer: 'return=representation', ...init.headers },
        cache: 'no-store',
      });
    } catch (error) {
      throw new Error(`Could not reach PostgREST: ${error instanceof Error ? error.message : String(error)}`);
    }
    if (!response.ok) {
      const detail = (await response.text()).slice(0, 500);
      throw new Error(`PostgREST returned HTTP ${response.status}: ${detail}`);
    }
    if (response.status === 204) return null;
    const text = await response.text();
    return text ? (JSON.parse(text) as unknown) : null;
  }

  async upsert(table: string, rows: Record<string, unknown> | Array<Record<string, unknown>>, onConflict?: string) {
    const query = onConflict ? `?on_conflict=${encodeURIComponent(onConflict)}` : '';
    return this.request(`/${table}${query}`, {
      method: 'POST',
      headers: { Prefer: 'resolution=merge-duplicates,return=representation' },
      body: JSON.stringify(rows),
    });
  }

  async deleteWhere(table: string, filters: Record<string, string>): Promise<void> {
    const query = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => query.set(key, `eq.${value}`));
    await this.request(`/${table}?${query}`, { method: 'DELETE' });
  }

  async updateWhere(table: string, filters: Record<string, string>, values: Record<string, unknown>) {
    const query = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => query.set(key, `eq.${value}`));
    return this.request(`/${table}?${query}`, { method: 'PATCH', body: JSON.stringify(values) });
  }

  async insertIncident(parameters: Record<string, unknown>): Promise<void> {
    await this.request('/rpc/insert_incident', { method: 'POST', body: JSON.stringify(parameters) });
  }

  async selectOne(table: string, filters: Record<string, string>, select = '*'): Promise<Record<string, unknown> | null> {
    const query = new URLSearchParams({ select, limit: '1' });
    Object.entries(filters).forEach(([key, value]) => query.set(key, `eq.${value}`));
    const result = await this.request(`/${table}?${query}`);
    if (!Array.isArray(result) || result.length === 0) return null;
    return result[0] as Record<string, unknown>;
  }


  async selectMany(
    table: string,
    options: { filters?: Record<string, string>; select?: string; order?: string; limit?: number } = {},
  ): Promise<Array<Record<string, unknown>>> {
    const query = new URLSearchParams({ select: options.select || '*' });
    Object.entries(options.filters || {}).forEach(([key, value]) => query.set(key, `eq.${value}`));
    if (options.order) query.set('order', options.order);
    if (options.limit) query.set('limit', String(options.limit));
    const result = await this.request(`/${table}?${query}`);
    return Array.isArray(result) ? (result as Array<Record<string, unknown>>) : [];
  }
}
