// SPDX-License-Identifier: Apache-2.0

// ChartInterpreter: turns one chart request into a model's raw reply. It sees
// only the request text, never any data, and each call stands alone. The reply
// is untrusted until parseChartSpec accepts it.

export interface ChartInterpreter {
  /** The model's reply, parsed from JSON; null when it was not JSON. Throws when no model answered. */
  interpret(request: string): Promise<unknown>;
}
