-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Rollback of freeze_midterm.sql: give writes back to service_role and postgres on MIDTERM, so
-- the team can return to it if the finals switch is abandoned. The anon lockdown stays (nothing
-- uses anon). Run as postgres in the midterm SQL editor.

BEGIN;
SET TRANSACTION READ WRITE; -- postgres sessions start read-only while frozen
ALTER ROLE postgres RESET default_transaction_read_only;
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO service_role;
COMMIT;

NOTIFY pgrst, 'reload schema';
