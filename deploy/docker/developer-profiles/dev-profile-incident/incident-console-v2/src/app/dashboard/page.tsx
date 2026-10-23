// SPDX-License-Identifier: Apache-2.0

import { AppHeader } from '@/components/app-header';
import { Dashboard } from '@/components/dashboard';

export default function DashboardPage() { return <main className="min-h-screen bg-canvas text-ink"><AppHeader active="dashboard" subtitle="Operations overview" /><Dashboard /></main>; }
