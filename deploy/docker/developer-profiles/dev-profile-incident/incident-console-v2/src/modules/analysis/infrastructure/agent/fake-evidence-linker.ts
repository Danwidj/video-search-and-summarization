// SPDX-License-Identifier: Apache-2.0

// In-memory EvidenceLinker for tests. It returns the scripted result (the last one repeating; an
// Error entry is thrown), or no groups when unscripted.

import type { EvidenceLinker, LinkResult } from '@/modules/analysis/infrastructure/agent/evidence-linker';
import type { VideoAnalysisInput } from '@/modules/analysis/infrastructure/agent/incident-synthesizer';

export class FakeEvidenceLinker implements EvidenceLinker {
  readonly calls: VideoAnalysisInput[][] = [];

  private readonly script: Array<LinkResult | Error>;

  constructor(script: Array<LinkResult | Error> = []) {
    this.script = script;
  }

  async link(videos: VideoAnalysisInput[], _signal: AbortSignal): Promise<LinkResult> {
    const call = this.calls.push(videos) - 1;
    const scripted = this.script[Math.min(call, this.script.length - 1)];
    if (scripted instanceof Error) throw scripted;
    return scripted ?? { kind: 'linked', groups: [] };
  }
}
