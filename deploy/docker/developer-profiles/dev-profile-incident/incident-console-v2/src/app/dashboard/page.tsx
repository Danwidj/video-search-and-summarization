// SPDX-License-Identifier: Apache-2.0

import { AppHeader } from '@/sections/shell/components/AppHeader';
import { Dashboard } from '@/sections/dashboard/components/Dashboard';

export default function DashboardPage() {
  return (
    <main className="min-h-screen bg-canvas text-ink">
      <AppHeader active="dashboard" subtitle="Operations overview" />
      <Dashboard />
    </main>
  );
}
