// SPDX-License-Identifier: Apache-2.0

import { AnalysisWorkspace } from '@/components/analysis-workspace';
import { AppHeader } from '@/components/app-header';

const stages = ['Upload secured', 'Video understood', 'Evidence structured', 'Report ready'];

export default function HomePage() {
  return (
    <main className="min-h-screen overflow-hidden bg-canvas text-ink">
      <div className="ambient ambient-one" />
      <div className="ambient ambient-two" />

      <AppHeader active="analyze" />

      <section className="relative z-10 mx-auto grid max-w-[1440px] gap-12 px-6 pb-20 pt-10 lg:grid-cols-[0.88fr_1.12fr] lg:px-12 lg:pt-20">
        <div className="max-w-xl self-center">
          <p className="mb-5 font-mono text-xs font-semibold uppercase tracking-[0.24em] text-moss">
            From footage to facts
          </p>
          <h1 className="text-balance text-5xl font-semibold leading-[0.98] tracking-[-0.055em] sm:text-6xl xl:text-7xl">
            Understand the incident, not the interface.
          </h1>
          <p className="mt-7 max-w-lg text-lg leading-8 text-ink/65">
            Drop in a video. Incident Studio will identify the critical sequence, organize the evidence, and prepare a
            report people can act on.
          </p>

          <ol className="mt-10 grid gap-3 sm:grid-cols-2">
            {stages.map((stage, index) => (
              <li className="flex items-center gap-3 rounded-2xl border border-ink/10 bg-white/50 px-4 py-3" key={stage}>
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-ink font-mono text-[11px] text-white">
                  {index + 1}
                </span>
                <span className="text-sm font-medium">{stage}</span>
              </li>
            ))}
          </ol>
        </div>

        <AnalysisWorkspace />
      </section>

      <section className="relative z-10 border-t border-ink/10 bg-white/45">
        <div className="mx-auto grid max-w-[1440px] gap-8 px-6 py-10 text-sm lg:grid-cols-3 lg:px-12">
          <p><strong className="block text-ink">Evidence first</strong><span className="text-ink/55">Every finding stays connected to a moment in the video.</span></p>
          <p><strong className="block text-ink">Uncertainty included</strong><span className="text-ink/55">Confidence and ambiguity remain visible instead of being hidden.</span></p>
          <p><strong className="block text-ink">Built for review</strong><span className="text-ink/55">Reports are designed to be scanned quickly and inspected deeply.</span></p>
        </div>
      </section>
    </main>
  );
}
