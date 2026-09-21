// SPDX-License-Identifier: Apache-2.0

import { AppHeader } from '@/components/app-header';
import { NotificationsCenter } from '@/components/notifications-center';

export default function NotificationsPage() { return <main className="min-h-screen bg-canvas text-ink"><AppHeader active="reports" subtitle="Notifications" /><NotificationsCenter /></main>; }
