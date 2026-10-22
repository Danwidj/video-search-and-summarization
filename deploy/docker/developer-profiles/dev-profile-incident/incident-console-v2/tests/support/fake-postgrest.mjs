// SPDX-License-Identifier: Apache-2.0

// A small in-memory PostgREST for adapter contract tests: eq, like and in filters,
// limit, upsert with on_conflict (merging, or ignoring duplicates when the
// request prefers resolution=ignore-duplicates), delete, and RPCs and read-only views
// supplied by the test. Every request is recorded. Embedded selects and
// cascades are not modelled.

const CONTROL = new Set(['select', 'limit', 'offset', 'on_conflict', 'order']);

/** PostgREST like-pattern (`*` / `%` any run, `_` one char, `\` escapes) as a RegExp. */
function likePattern(pattern) {
  let source = '';
  for (let index = 0; index < pattern.length; index += 1) {
    const character = pattern[index];
    if (character === '\\') source += pattern[++index].replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    else if (character === '*' || character === '%') source += '.*';
    else if (character === '_') source += '.';
    else source += character.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }
  return new RegExp(`^${source}$`, 's');
}

/** The values of a PostgREST in-filter list, `("a","b\"c")` or `(a,b)`. */
function inValues(list) {
  return [...list.slice(1, -1).matchAll(/"((?:[^"\\]|\\.)*)"|([^,]+)/g)].map(([, quoted, bare]) => (quoted ?? bare).replace(/\\(.)/g, '$1'));
}

function matches(row, params) {
  return [...params].every(([key, value]) => {
    if (CONTROL.has(key)) return true;
    if (value.startsWith('eq.')) return String(row[key]) === value.slice(3);
    if (value.startsWith('like.')) return likePattern(value.slice(5)).test(String(row[key] ?? ''));
    if (value.startsWith('in.')) return inValues(value.slice(3)).includes(String(row[key]));
    throw new Error(`fake PostgREST does not support the filter ${key}=${value}`);
  });
}

/**
 * tables: { name: rows[] }. rpc: { name: (args, store) => result }; an RPC
 * refuses like a RAISE EXCEPTION by throwing { message }. views: { name:
 * (store) => rows }, computed on every read. requests: { method, path, body }
 * in order.
 */
export function fakePostgrest(tables, { rpc = {}, views = {} } = {}) {
  const store = Object.fromEntries(Object.entries(tables).map(([name, rows]) => [name, rows.map((row) => ({ ...row }))]));
  const requests = [];
  const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  const fetch = async (url, init = {}) => {
    const parsed = new URL(String(url));
    const path = parsed.pathname.replace('/rest/v1/', '');
    const method = init.method || 'GET';
    requests.push({ method, path, body: init.body ? JSON.parse(String(init.body)) : undefined });
    if (path.startsWith('rpc/')) {
      const handler = rpc[path.slice(4)];
      if (!handler) return json({ message: `unknown function ${path}` }, 404);
      try {
        return json(handler(JSON.parse(String(init.body)), store) ?? null);
      } catch (error) {
        return json({ code: 'P0001', message: error.message }, 400);
      }
    }
    if (views[path]) {
      if (method !== 'GET') return json({ message: `cannot ${method} the view ${path}` }, 405);
      const found = views[path](store).filter((row) => matches(row, parsed.searchParams));
      return json(found.slice(0, Number(parsed.searchParams.get('limit') || found.length)));
    }
    const rows = (store[path] ??= []);
    if (method === 'GET') {
      const found = rows.filter((row) => matches(row, parsed.searchParams));
      const limit = Number(parsed.searchParams.get('limit') || found.length);
      return json(found.slice(0, limit));
    }
    if (method === 'DELETE') {
      store[path] = rows.filter((row) => !matches(row, parsed.searchParams));
      return new Response(null, { status: 204 });
    }
    if (method === 'POST') {
      const keys = (parsed.searchParams.get('on_conflict') || '').split(',').filter(Boolean);
      const ignoreDuplicates = (new Headers(init.headers).get('prefer') || '').includes('resolution=ignore-duplicates');
      const incoming = [].concat(JSON.parse(String(init.body)));
      for (const row of incoming) {
        const index = keys.length ? rows.findIndex((existing) => keys.every((key) => existing[key] === row[key])) : -1;
        if (index >= 0 && ignoreDuplicates) continue;
        if (index >= 0) rows[index] = { ...rows[index], ...row };
        else rows.push({ ...row });
      }
      return json(incoming);
    }
    return json({ message: `unsupported ${method}` }, 405);
  };
  return { fetch, store, requests };
}
