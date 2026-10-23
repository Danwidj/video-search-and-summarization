// SPDX-License-Identifier: Apache-2.0

/** Database liveness only; /api/health still checks the agent, gateway and R2 itself. */
export interface DatabaseHealth {
  configured: boolean;
  reachable: boolean;
}

export interface HealthRepository {
  checkHealth(): Promise<DatabaseHealth>;
}
