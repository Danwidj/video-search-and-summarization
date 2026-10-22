-- Drop unused tables dropped from live finals Supabase database.
-- asset_matches, entity_matches, instrument_matches and notifications were only used
-- by the retired v1 console and are unused in finals.
DROP TABLE IF EXISTS public.asset_matches CASCADE;
DROP TABLE IF EXISTS public.entity_matches CASCADE;
DROP TABLE IF EXISTS public.instrument_matches CASCADE;
DROP TABLE IF EXISTS public.notifications CASCADE;
