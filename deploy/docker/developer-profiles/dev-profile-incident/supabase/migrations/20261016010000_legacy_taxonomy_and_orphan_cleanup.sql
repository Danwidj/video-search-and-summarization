-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Prompt-contract phase 4 & legacy clean-up:
-- 1. Migrate stored legacy values in incidents and entities to the 5-label contract taxonomy:
--    - incidents.type: 'fighting' -> 'assault' (13 rows: 12 MR-SEED rows + run m37883594f65802c8a31)
--    - incidents.type: 'animal' -> 'animal attack' (20 rows: 19 MR-SEED rows + run mab7125d03c705e67b20)
--    - entities.type: 'person' -> 'human' (6 rows: runs mab7125d03c705e67b20, m37883594f65802c8a31, mbf6b0f0bb944b497d4d)
--    Note: incidents.type currently has 0 rows with 'other'. Per Firstmate decision (Option 1),
--    no relational migration is needed for 'other', and model_runs.notes remains immutable by design
--    (the lone test-pattern run m5629b0938e679c9873d has no incidents row).
-- 2. Remove the 20 pre-existing orphaned legacy console model_runs rows that name videos
--    that no longer exist (status.md known issue 4). None of these rows have incident or report rows.

BEGIN;

-- 1. Taxonomy migration: incidents
UPDATE public.incidents
SET type = 'assault'
WHERE type = 'fighting';

UPDATE public.incidents
SET type = 'animal attack'
WHERE type = 'animal';

-- 2. Taxonomy migration: entities
UPDATE public.entities
SET type = 'human'
WHERE type = 'person';

-- 3. Delete 20 orphaned legacy console model_runs rows naming deleted videos
DELETE FROM public.model_runs
WHERE id IN (
    'm8f79a33b8231fec914a', -- v1c7b420524f69e1f125 (test workshop)
    'md2f6528f38497c186ff', -- v99d75ba36e105877239 (test workshop)
    'ma3d606d678144b079ee', -- v2c6be171fdeb7c78d75 (alley monkey)
    'm6af95ffc5e9a3e0cb2b', -- v014bb818a3e9629352a (alley monkey)
    'md5fb29b5eac05b6a66c', -- vc5bebd9061c97aefed7 (test face)
    'm64c1ac3b9016b0a5c25', -- v5d098f5202ad4ac63cd (bear store)
    'm2d715078e3280006296', -- v5f895248445d65f47d3 (living room)
    'm7e25e066d916c23cc46', -- v5f895248445d65f47d3 (living room)
    'mbc0a845a383fee3ba5a', -- v5f895248445d65f47d3 (living room)
    'm5b613baff9759dca358', -- v03e884e1dfba65ab953 (test2 living room)
    'm0929a3a7bd056d6f247', -- v03e884e1dfba65ab953 (test2 living room)
    'm6868a8b2e7d0aea7650', -- v2b6a3a3813585476b01 (test2 cat vase)
    'm907febd09dfb9185af0', -- v2b6a3a3813585476b01 (test2 cat vase)
    'm6d4b327cf8970d4132f', -- v2b6a3a3813585476b01 (test2 cat vase)
    'mcee3ae89ac39f4180f1', -- vf18e560eb8cb860892e (dim room)
    'm25d64aaddd5cb2a86aa', -- v2b6a3a3813585476b01 (test2 cat vase)
    'mda8e4766ad10350a2a3', -- v2b6a3a3813585476b01 (test2 cat vase)
    'm555a079c4f026fdbae8', -- v4f640830a03216447a4 (plush toys)
    'mf437bbbff1823828b51', -- v0cc5f073a7a520f199b (plush toys)
    'm4b396db37e3b25e8ed4'  -- vdbcbab9584cb21decc6 (plush toys)
);

COMMIT;
