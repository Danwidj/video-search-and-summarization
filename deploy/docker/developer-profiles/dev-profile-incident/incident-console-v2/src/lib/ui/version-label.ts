// SPDX-License-Identifier: Apache-2.0

/** The text of a version pill: a version is made by the model or by a person, and either can also be the official one. */
export function versionLabel(kind: 'ai' | 'human', official: boolean): string {
  const type = kind === 'human' ? 'Human' : 'Model';
  return official ? `Official · ${type}` : type;
}
