// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Pagination, PaginationContent, PaginationItem, PaginationNext, PaginationPrevious } from '@/components/ui/pagination';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { formatTimestamp } from '@/lib/time';

interface VideoItem {
  videoId: string;
  filename: string;
  uploadedAt: string | null;
  source: string | null;
  revisions: number;
  officialRevisionId: number | null;
}

/** Videos and their analysis history; `?filter=without-report` shows uploads with no successful analysis. */
export function VideosScreen() {
  const query = useSearchParams();
  const router = useRouter();
  const requested = query.get('filter');
  const filter = requested === 'without-report' || requested === 'awaiting-selection' ? requested : 'all';
  const page = Math.max(1, Number(query.get('page') || '1') || 1);
  const [state, setState] = useState<{ videos: VideoItem[]; totalItems: number; totalPages: number } | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    setState(null);
    void fetch(`/api/videos?filter=${filter}&page=${page}`, { cache: 'no-store' })
      .then(async (response) => {
        const payload = (await response.json()) as {
          videos?: VideoItem[];
          pagination?: { totalItems: number; totalPages: number };
          error?: string;
        };
        if (!response.ok || !payload.videos) throw new Error(payload.error || 'Could not load videos');
        setState({
          videos: payload.videos,
          totalItems: payload.pagination?.totalItems ?? 0,
          totalPages: payload.pagination?.totalPages ?? 0,
        });
      })
      .catch((cause: Error) => setError(cause.message));
  }, [filter, page]);

  const go = (next: Record<string, string>) => router.push(`/videos?${new URLSearchParams({ filter, page: '1', ...next })}`);

  return (
    <div className="mx-auto max-w-[1500px] px-6 pb-16 pt-2 lg:px-12">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-primary">Videos</p>
      <h1 className="mt-3 text-4xl font-semibold tracking-tight text-foreground">Uploaded videos</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Each video keeps its full analysis history. Report versions come only from successful analyses.
      </p>

      <Tabs className="mt-6" onValueChange={(value) => go({ filter: value })} value={filter}>
        <TabsList>
          <TabsTrigger value="all">All videos</TabsTrigger>
          <TabsTrigger value="awaiting-selection">Awaiting official report</TabsTrigger>
          <TabsTrigger value="without-report">Without a report</TabsTrigger>
        </TabsList>
      </Tabs>

      {error && (
        <Alert className="mt-6" variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {!state && !error && <Skeleton className="mt-6 h-40 w-full rounded-2xl" role="status" />}

      {state && (
        <>
          <p className="mt-6 text-sm text-muted-foreground">
            {state.totalItems} {state.totalItems === 1 ? 'video' : 'videos'}
          </p>
          <div className="mt-3 overflow-hidden rounded-2xl border border-border bg-card">
            <p className="border-b border-border px-4 py-2 text-xs text-muted-foreground sm:hidden">
              Swipe the table sideways to see every column.
            </p>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Filename</TableHead>
                  <TableHead>Uploaded</TableHead>
                  <TableHead>Reports</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {state.videos.map((video) => (
                  <TableRow key={video.videoId}>
                    <TableCell className="max-w-xs truncate font-semibold" title={video.filename}>
                      {video.filename}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatTimestamp(video.uploadedAt)}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {video.revisions} {video.revisions === 1 ? 'report version' : 'report versions'}
                    </TableCell>
                    <TableCell>
                      {video.officialRevisionId !== null ? (
                        <Badge className="text-xs font-bold" variant="default">
                          Official report selected
                        </Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button asChild size="sm" variant="ghost">
                        <Link href={`/videos/${encodeURIComponent(video.videoId)}`}>Analysis history →</Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {!state.videos.length && (
                  <TableRow>
                    <TableCell className="h-24 text-center italic text-muted-foreground" colSpan={5}>
                      No videos match.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          {state.totalPages > 1 && (
            <div className="mt-6 flex flex-col items-center justify-between gap-4 sm:flex-row">
              <p className="text-xs text-muted-foreground">
                Page {page} of {state.totalPages}
              </p>
              <Pagination className="mx-0 w-auto justify-end">
                <PaginationContent>
                  <PaginationItem>
                    <PaginationPrevious
                      aria-disabled={page <= 1}
                      className={page <= 1 ? 'pointer-events-none opacity-50' : ''}
                      href={`/videos?${new URLSearchParams({ filter, page: String(Math.max(1, page - 1)) })}`}
                      tabIndex={page <= 1 ? -1 : undefined}
                    />
                  </PaginationItem>
                  <PaginationItem>
                    <PaginationNext
                      aria-disabled={page >= state.totalPages}
                      className={page >= state.totalPages ? 'pointer-events-none opacity-50' : ''}
                      href={`/videos?${new URLSearchParams({ filter, page: String(Math.min(state.totalPages, page + 1)) })}`}
                      tabIndex={page >= state.totalPages ? -1 : undefined}
                    />
                  </PaginationItem>
                </PaginationContent>
              </Pagination>
            </div>
          )}
        </>
      )}
    </div>
  );
}
