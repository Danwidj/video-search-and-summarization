// SPDX-License-Identifier: Apache-2.0

// The chip style for each reason kind the agent returns (I23): place and event type are strong, time and differences soft.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { describe, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { reasonChipStyle } = await import('../src/sections/suggestions/reason-chips.ts');

describe('reasonChipStyle', () => {
  test('maps every kind the agent returns to an icon group and a strength', () => {
    const expected = {
      same_event_type: ['type', true],
      different_event_type: ['type', false],
      same_place: ['place', true],
      similar_place: ['place', true],
      different_place: ['place', false],
      place_unknown: ['place', false],
      time_overlap: ['time', false],
      time_apart: ['time', false],
    };
    for (const [kind, [group, strong]] of Object.entries(expected)) assert.deepEqual(reasonChipStyle(kind), { group, strong }, kind);
  });

  test('a kind from a newer agent is a soft chip with the generic icon', () => {
    assert.deepEqual(reasonChipStyle('same_camera'), { group: 'other', strong: false });
  });
});
