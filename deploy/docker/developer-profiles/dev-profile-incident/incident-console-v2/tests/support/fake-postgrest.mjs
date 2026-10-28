// SPDX-License-Identifier: Apache-2.0

// A small in-memory PostgREST for adapter contract tests: eq, neq, is.null,
// like and in filters, order, limit, upsert with on_conflict, delete, identity
// ids for the tables named in `identity`, and RPCs and read-only views
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
  return [...list.slice(1, -1).matchAll(/"((?:[^"\\]|\\.)*)"|([^,]+)/g)].map(([, quoted, bare]) =>
    (quoted ?? bare).replace(/\\(.)/g, '$1'),
  );
}

/** `col.desc,other.asc.nullslast` -> rows sorted by it (nulls last). */
function sorted(rows, order) {
  if (!order) return rows;
  const keys = order.split(',').map((part) => {
    const [column, ...flags] = part.split('.');
    return { column, sign: flags.includes('desc') ? -1 : 1 };
  });
  return [...rows].sort((a, b) => {
    for (const { column, sign } of keys) {
      const [x, y] = [a[column], b[column]];
      if (x === y) continue;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return sign * (x < y ? -1 : 1);
    }
    return 0;
  });
}

function matches(row, params) {
  return [...params].every(([key, value]) => {
    if (CONTROL.has(key)) return true;
    if (value.startsWith('eq.')) return String(row[key]) === value.slice(3);
    if (value.startsWith('neq.')) return String(row[key]) !== value.slice(4);
    if (value === 'is.null') return row[key] === null || row[key] === undefined;
    if (value.startsWith('like.')) return likePattern(value.slice(5)).test(String(row[key] ?? ''));
    if (value.startsWith('in.')) return inValues(value.slice(3)).includes(String(row[key]));
    throw new Error(`fake PostgREST does not support the filter ${key}=${value}`);
  });
}

/**
 * tables: { name: rows[] }. rpc: { name: (args, store) => result }; an RPC
 * refuses like a RAISE EXCEPTION by throwing { message }. views: { name:
 * (store) => rows }, computed on every read. identity: { table: column }, a
 * column the database numbers on insert (an insert returns the stored rows). requests: { method, path, body }
 * in order.
 */
export function fakePostgrest(tables, { rpc = {}, views = {}, identity = {} } = {}) {
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
    store[path] ??= [];
    const rows = store[path];
    if (method === 'GET') {
      const found = sorted(
        rows.filter((row) => matches(row, parsed.searchParams)),
        parsed.searchParams.get('order'),
      );
      const limit = Number(parsed.searchParams.get('limit') || found.length);
      return json(found.slice(0, limit));
    }
    if (method === 'DELETE') {
      store[path] = rows.filter((row) => !matches(row, parsed.searchParams));
      return new Response(null, { status: 204 });
    }
    if (method === 'POST') {
      const keys = (parsed.searchParams.get('on_conflict') || '').split(',').filter(Boolean);
      const incoming = [].concat(JSON.parse(String(init.body)));
      const results = [];
      for (const row of incoming) {
        const index = keys.length ? rows.findIndex((existing) => keys.every((key) => existing[key] === row[key])) : -1;
        // resolution=ignore-duplicates keeps the existing row (insertIfAbsent); otherwise the conflict merges.
        if (index >= 0 && String(init.headers?.Prefer ?? '').includes('ignore-duplicates')) results.push(rows[index]);
        else if (index >= 0) {
          rows[index] = { ...rows[index], ...row };
          results.push(rows[index]);
        } else {
          const column = identity[path];
          const stored =
            column && row[column] === undefined
              ? { ...row, [column]: Math.max(0, ...rows.map((existing) => existing[column])) + 1 }
              : { ...row };
          rows.push(stored);
          results.push(stored);
        }
      }
      return json(results);
    }
    return json({ message: `unsupported ${method}` }, 405);
  };
  return { fetch, store, requests };
}
