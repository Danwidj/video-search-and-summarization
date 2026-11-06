// SPDX-License-Identifier: Apache-2.0

// The console talks to the agent over node:http (not fetch, see HttpIncidentAgent), so a test cannot stub the agent
// with globalThis.fetch alone. This starts a local server that hands each agent request to whatever globalThis.fetch is
// at that moment, under the address the tests assert on (http://agent.test:8000), and returns the address to put in
// INCIDENT_AGENT_BASE_URL. The server does not keep the test run open.
import http from 'node:http';

export const STUBBED_AGENT_ORIGIN = 'http://agent.test:8000';

export async function agentBridge() {
  const server = http.createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const answer = await globalThis.fetch(`${STUBBED_AGENT_ORIGIN}${req.url}`, {
      method: req.method,
      headers: req.headers,
      body: Buffer.concat(chunks).toString('utf8'),
    });
    res.writeHead(answer.status, { 'Content-Type': answer.headers.get('content-type') ?? 'application/json' });
    res.end(await answer.text());
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  server.unref();
  return `http://127.0.0.1:${server.address().port}`;
}
