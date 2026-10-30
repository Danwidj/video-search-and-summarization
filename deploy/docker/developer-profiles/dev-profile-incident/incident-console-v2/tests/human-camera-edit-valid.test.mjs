// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

await import('../src/modules/contract/infrastructure/loader.ts');
const { validateReport } = await import('../src/modules/contract/domain/validate.ts');
const { saveIncidentHumanEdit } = await import('../src/modules/reports/application/save-human-edit/incident.ts');

const full = JSON.parse(readFileSync(join(process.cwd(), '..', 'contracts', 'fixtures', 'valid', 'full-report.json'), 'utf8'));
const overview = { title: 't', type: 'assault', severity_level: 3, description: 'd', location: null };

const edit = (report, description) => ({
  incident: {
    type: report.incident.type,
    start_timestamp: report.incident.start_timestamp,
    end_timestamp: report.incident.end_timestamp,
    description,
    severity_level: report.incident.severity_level,
  },
  entities: report.entities.map((item) => ({ ...item, source_id: item.entity_id, image: null })),
  instruments: report.instruments.map((item) => ({ ...item, source_id: item.instrument_id, image: null })),
  assets: report.assets.map((item) => ({ ...item, source_id: item.asset_id, image: null })),
});

async function save(parentReport) {
  let saved;
  const repo = {
    getIncident: async () => ({ officialRevisionId: 1, videos: [{ videoId: 'a.mp4', storageKey: 'k/a.mp4' }] }),
    getRevision: async () => ({
      revision: { revisionId: 5, videoNames: ['a.mp4'] },
      envelope: { overview, cameras: [{ video: 'a.mp4', report: parentReport }] },
      evidence: [],
    }),
    saveHumanRevision: async (row) => {
      saved = row;
      return {};
    },
  };
  await saveIncidentHumanEdit(
    repo,
    { incidentId: 1, parentId: 5, createdBy: 'x', note: null, target: { camera: 'a.mp4', edit: edit(full, 'Edited summary.') } },
    async () => [],
  );
  return saved.payload.cameras[0].report;
}

test('a camera saved from an edit still passes incident-contract-v4', async () => {
  const report = await save(full);
  assert.equal(report.incident.description, 'Edited summary.');
  assert.equal('duration' in report.incident, false);
  validateReport(report);
});

test('a stale incident.duration on the parent camera is dropped', async () => {
  const report = await save({ ...full, incident: { ...full.incident, duration: 8 } });
  assert.equal('duration' in report.incident, false);
  validateReport(report);
});
