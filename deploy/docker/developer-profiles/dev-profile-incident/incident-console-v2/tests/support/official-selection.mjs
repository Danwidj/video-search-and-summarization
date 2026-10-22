// SPDX-License-Identifier: Apache-2.0

// Only the explicit official-report RPCs may set or clear a video's official
// run. Given recorded PostgREST requests ({ method, path, body }), returns the
// ones that would: a call to either RPC, or a write carrying a selection column.

const SELECTION_COLUMNS = ['selected_model_run_id', 'selected_by', 'selected_at'];
const SELECTION_RPCS = ['rpc/select_official_report', 'rpc/clear_official_report'];

export function officialSelectionWrites(requests) {
  return requests.filter(({ method, path, body }) => SELECTION_RPCS.includes(path)
    || ((method ?? 'GET') !== 'GET' && [].concat(body ?? []).some((row) => row !== null && typeof row === 'object' && SELECTION_COLUMNS.some((column) => column in row))));
}
