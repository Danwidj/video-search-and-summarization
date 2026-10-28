// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { Check, Circle, Copy, FileText, History, MoreHorizontal, Search, Sparkles, Upload, Video as VideoIcon } from 'lucide-react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
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

/** Videos and their analysis history; provides unified lifecycle status, responsive card/table layout and direct report navigation. */
export function VideosScreen() {
  const query = useSearchParams();
  const router = useRouter();
  const requested = query.get('filter');
  const filter =
    requested === 'with-report' ||
    requested === 'needs-analysis' ||
    requested === 'failed' ||
    requested === 'without-report' ||
    requested === 'awaiting-selection'
      ? requested
      : 'all';
  const page = Math.max(1, Number(query.get('page') || '1') || 1);
  const [state, setState] = useState<{
    videos: VideoItem[];
    totalItems: number;
    totalPages: number;
  } | null>(null);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [copiedId, setCopiedId] = useState<string | null>(null);

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

  const displayedVideos = useMemo(() => {
    if (!state?.videos) return [];
    const queryTerm = search.trim().toLowerCase();
    if (!queryTerm) return state.videos;
    return state.videos.filter(
      (video) =>
        video.filename.toLowerCase().includes(queryTerm) ||
        video.videoId.toLowerCase().includes(queryTerm) ||
        Boolean(video.source?.toLowerCase().includes(queryTerm)),
    );
  }, [state?.videos, search]);

  const copyVideoId = (id: string) => {
    void navigator.clipboard?.writeText(id);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div className="mx-auto max-w-[1500px] px-6 pb-16 pt-2 lg:px-12">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-primary">Videos</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">Uploaded videos</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Each video keeps its full analysis history. Report versions come only from successful analyses.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 sm:w-64 sm:flex-initial">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              type="search"
              placeholder="Filter by filename..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-9"
            />
          </div>
          <Button asChild className="shrink-0 bg-primary text-primary-foreground hover:bg-primary/90">
            <Link href="/">
              <Upload data-icon="inline-start" />
              Upload video
            </Link>
          </Button>
        </div>
      </div>

      <Tabs
        className="mt-6"
        onValueChange={(value) => go({ filter: value })}
        value={filter === 'without-report' ? 'needs-analysis' : filter === 'awaiting-selection' ? 'with-report' : filter}
      >
        <TabsList className="w-full justify-start overflow-x-auto sm:w-auto">
          <TabsTrigger value="all">All videos</TabsTrigger>
          <TabsTrigger value="with-report">With report</TabsTrigger>
          <TabsTrigger value="needs-analysis">Needs analysis</TabsTrigger>
          <TabsTrigger value="failed">Failed</TabsTrigger>
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
            {search.trim() ? ` · ${displayedVideos.length} matching search` : ''}
          </p>

          {/* Desktop Table View (>= md) */}
          <div className="mt-3 hidden overflow-hidden rounded-2xl border border-border bg-card md:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Video</TableHead>
                  <TableHead>Uploaded</TableHead>
                  <TableHead>Report & Lifecycle Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {displayedVideos.map((video) => (
                  <TableRow key={video.videoId}>
                    <TableCell className="max-w-xs">
                      <div className="flex items-center gap-3">
                        <div className="relative aspect-video w-16 shrink-0 overflow-hidden rounded-md border border-border bg-black/90 flex items-center justify-center">
                          <VideoIcon className="size-4 text-white/70" />
                        </div>
                        <div className="min-w-0">
                          <p className="truncate font-semibold text-foreground" title={video.filename}>
                            {video.filename}
                          </p>
                          {video.source && (
                            <p className="truncate font-mono text-[11px] text-muted-foreground" title={video.source}>
                              {video.source}
                            </p>
                          )}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{formatTimestamp(video.uploadedAt)}</TableCell>
                    <TableCell>
                      <div className="flex flex-col gap-1">
                        <div>
                          {video.officialRevisionId !== null ? (
                            <Badge className="gap-1 bg-moss text-white hover:bg-moss/90 text-xs font-bold" variant="default">
                              <Check className="size-3 text-signal" />
                              Official report selected
                            </Badge>
                          ) : video.revisions > 0 ? (
                            <Badge variant="secondary" className="gap-1 text-xs font-semibold">
                              <Sparkles className="size-3 text-amber-600" />
                              Report ready
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="gap-1 text-xs text-muted-foreground font-medium">
                              <Circle className="size-2 fill-muted-foreground/60" />
                              Ready to analyse
                            </Badge>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {video.revisions} {video.revisions === 1 ? 'report version' : 'report versions'}
                        </p>
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-2">
                        {video.revisions > 0 ? (
                          <Button asChild size="sm" variant="outline">
                            <Link href={`/reports/${encodeURIComponent(video.videoId)}`}>Open report →</Link>
                          </Button>
                        ) : (
                          <Button asChild size="sm" className="bg-primary text-primary-foreground hover:bg-primary/90">
                            <Link href={`/videos/${encodeURIComponent(video.videoId)}`}>Analyse video →</Link>
                          </Button>
                        )}
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button size="icon" variant="ghost" className="size-8" aria-label="More options">
                              <MoreHorizontal className="size-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem asChild>
                              <Link href={`/videos/${encodeURIComponent(video.videoId)}`}>
                                <History data-icon="inline-start" />
                                Analysis history
                              </Link>
                            </DropdownMenuItem>
                            {video.revisions > 0 && (
                              <DropdownMenuItem asChild>
                                <Link href={`/reports/${encodeURIComponent(video.videoId)}`}>
                                  <FileText data-icon="inline-start" />
                                  View report
                                </Link>
                              </DropdownMenuItem>
                            )}
                            <DropdownMenuSeparator />
                            <DropdownMenuItem onClick={() => copyVideoId(video.videoId)}>
                              <Copy data-icon="inline-start" />
                              {copiedId === video.videoId ? 'Copied ID' : 'Copy video ID'}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
                {!displayedVideos.length && (
                  <TableRow>
                    <TableCell className="h-32 text-center text-muted-foreground" colSpan={4}>
                      <div className="flex flex-col items-center justify-center gap-1">
                        <p className="font-semibold text-foreground">No videos match.</p>
                        <p className="text-xs">Try adjusting your search query or filter tab.</p>
                        {search && (
                          <Button variant="ghost" size="sm" onClick={() => setSearch('')} className="mt-2 text-xs">
                            Clear search
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          {/* Mobile Stacked Card View (< md) */}
          <div className="mt-3 flex flex-col gap-3 md:hidden">
            {displayedVideos.map((video) => (
              <Card key={video.videoId} className="gap-3 p-4 border border-border bg-card">
                <CardContent className="p-0 flex flex-col gap-3">
                  <div className="flex items-start gap-3">
                    <div className="relative aspect-video w-16 shrink-0 overflow-hidden rounded-md border border-border bg-black/90 flex items-center justify-center">
                      <VideoIcon className="size-4 text-white/70" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold text-foreground" title={video.filename}>
                        {video.filename}
                      </p>
                      <p className="mt-0.5 text-xs text-muted-foreground">{formatTimestamp(video.uploadedAt)}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        {video.officialRevisionId !== null ? (
                          <Badge className="gap-1 bg-moss text-white hover:bg-moss/90 text-[11px] font-bold" variant="default">
                            <Check className="size-3 text-signal" />
                            Official
                          </Badge>
                        ) : video.revisions > 0 ? (
                          <Badge variant="secondary" className="gap-1 text-[11px] font-semibold">
                            <Sparkles className="size-3 text-amber-600" />
                            Report ready
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="gap-1 text-[11px] text-muted-foreground font-medium">
                            <Circle className="size-1.5 fill-muted-foreground/60" />
                            Ready to analyse
                          </Badge>
                        )}
                        <span className="text-xs text-muted-foreground">
                          {video.revisions} {video.revisions === 1 ? 'version' : 'versions'}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 pt-2 border-t border-border">
                    {video.revisions > 0 ? (
                      <Button asChild size="sm" variant="outline" className="flex-1">
                        <Link href={`/reports/${encodeURIComponent(video.videoId)}`}>Open report →</Link>
                      </Button>
                    ) : (
                      <Button asChild size="sm" className="flex-1 bg-primary text-primary-foreground hover:bg-primary/90">
                        <Link href={`/videos/${encodeURIComponent(video.videoId)}`}>Analyse video →</Link>
                      </Button>
                    )}
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button size="icon" variant="ghost" className="size-8 shrink-0" aria-label="More options">
                          <MoreHorizontal className="size-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem asChild>
                          <Link href={`/videos/${encodeURIComponent(video.videoId)}`}>
                            <History data-icon="inline-start" />
                            Analysis history
                          </Link>
                        </DropdownMenuItem>
                        {video.revisions > 0 && (
                          <DropdownMenuItem asChild>
                            <Link href={`/reports/${encodeURIComponent(video.videoId)}`}>
                              <FileText data-icon="inline-start" />
                              View report
                            </Link>
                          </DropdownMenuItem>
                        )}
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onClick={() => copyVideoId(video.videoId)}>
                          <Copy data-icon="inline-start" />
                          {copiedId === video.videoId ? 'Copied ID' : 'Copy video ID'}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </CardContent>
              </Card>
            ))}

            {!displayedVideos.length && (
              <Card className="p-8 text-center border-dashed border-border">
                <CardContent className="p-0 flex flex-col items-center justify-center gap-1 text-muted-foreground">
                  <p className="font-semibold text-foreground">No videos match.</p>
                  <p className="text-xs">Try adjusting your search query or filter tab.</p>
                  {search && (
                    <Button variant="ghost" size="sm" onClick={() => setSearch('')} className="mt-2 text-xs">
                      Clear search
                    </Button>
                  )}
                </CardContent>
              </Card>
            )}
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
