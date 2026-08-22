begin;

-- The Flask application owns this table and stores timestamps as Unix seconds
-- in DOUBLE PRECISION columns. This migration augments that schema; it never
-- mutates Supabase's managed `storage` schema.
do $$
begin
  if to_regclass('public.player_documents') is null then
    raise exception
      'public.player_documents must exist before applying player document lifecycle migration';
  end if;
end
$$;

alter table public.player_documents
  add column if not exists expires_at double precision,
  add column if not exists is_pinned integer not null default 0,
  add column if not exists object_size_bytes bigint,
  add column if not exists lifecycle_status text not null default 'active',
  add column if not exists delete_attempts integer not null default 0,
  add column if not exists last_delete_error text,
  add column if not exists storage_deleted_at double precision,
  add column if not exists cleanup_claimed_at double precision,
  add column if not exists cleanup_claim_token uuid;

-- Fail clearly instead of allowing an ISO timestamp / Unix timestamp mismatch
-- if a conflicting lifecycle schema was installed separately.
do $$
declare
  actual_type text;
begin
  select data_type into actual_type
  from information_schema.columns
  where table_schema = 'public'
    and table_name = 'player_documents'
    and column_name = 'expires_at';
  if actual_type <> 'double precision' then
    raise exception 'public.player_documents.expires_at must be DOUBLE PRECISION, found %', actual_type;
  end if;

  select data_type into actual_type
  from information_schema.columns
  where table_schema = 'public'
    and table_name = 'player_documents'
    and column_name = 'storage_deleted_at';
  if actual_type <> 'double precision' then
    raise exception 'public.player_documents.storage_deleted_at must be DOUBLE PRECISION, found %', actual_type;
  end if;

  select data_type into actual_type
  from information_schema.columns
  where table_schema = 'public'
    and table_name = 'player_documents'
    and column_name = 'cleanup_claimed_at';
  if actual_type <> 'double precision' then
    raise exception 'public.player_documents.cleanup_claimed_at must be DOUBLE PRECISION, found %', actual_type;
  end if;
end
$$;

update public.player_documents set is_pinned = 0 where is_pinned is null;
update public.player_documents set delete_attempts = 0 where delete_attempts is null;
update public.player_documents
set lifecycle_status = 'active'
where lifecycle_status is null or btrim(lifecycle_status) = '';

alter table public.player_documents
  alter column is_pinned set default 0,
  alter column is_pinned set not null,
  alter column lifecycle_status set default 'active',
  alter column lifecycle_status set not null,
  alter column delete_attempts set default 0,
  alter column delete_attempts set not null;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'player_documents_object_size_nonnegative'
      and conrelid = 'public.player_documents'::regclass
  ) then
    alter table public.player_documents
      add constraint player_documents_object_size_nonnegative
      check (object_size_bytes is null or object_size_bytes >= 0) not valid;
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'player_documents_delete_attempts_nonnegative'
      and conrelid = 'public.player_documents'::regclass
  ) then
    alter table public.player_documents
      add constraint player_documents_delete_attempts_nonnegative
      check (delete_attempts >= 0) not valid;
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'player_documents_is_pinned_valid'
      and conrelid = 'public.player_documents'::regclass
  ) then
    alter table public.player_documents
      add constraint player_documents_is_pinned_valid
      check (is_pinned in (0, 1)) not valid;
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'player_documents_lifecycle_status_valid'
      and conrelid = 'public.player_documents'::regclass
  ) then
    alter table public.player_documents
      add constraint player_documents_lifecycle_status_valid
      check (lifecycle_status in (
        'pending_upload', 'active', 'pending_delete', 'delete_failed', 'upload_failed'
      )) not valid;
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'player_documents_cleanup_claim_consistent'
      and conrelid = 'public.player_documents'::regclass
  ) then
    alter table public.player_documents
      add constraint player_documents_cleanup_claim_consistent
      check (
        (cleanup_claimed_at is null and cleanup_claim_token is null)
        or (cleanup_claimed_at is not null and cleanup_claim_token is not null)
      ) not valid;
  end if;
end
$$;

comment on column public.player_documents.expires_at is
  'Unix-seconds retention deadline for report PDFs; non-report documents are never automated cleanup candidates.';
comment on column public.player_documents.is_pinned is
  'Integer boolean used by the application; 1 permanently excludes automated cleanup.';
comment on column public.player_documents.object_size_bytes is
  'Last known Supabase Storage object size, used for cleanup reporting.';
comment on column public.player_documents.lifecycle_status is
  'Application lifecycle state; pending_delete is the cleanup claim state.';
comment on column public.player_documents.storage_deleted_at is
  'Unix-seconds tombstone populated only when Storage deletion succeeded but metadata cleanup failed.';
comment on column public.player_documents.cleanup_claimed_at is
  'Unix-seconds start of the temporary automated cleanup lease; leases older than 15 minutes are reclaimable.';
comment on column public.player_documents.cleanup_claim_token is
  'Cleanup run UUID that owns the temporary lease.';

-- Backfill reports only. Workouts, scouting documents, and uncategorized or
-- generic documents remain untouched.
update public.player_documents
set expires_at = case
  when series_end is not null and series_end > 0 then series_end + 86400.0
  else uploaded_at + 604800.0
end
where expires_at is null
  and uploaded_at > 0
  and lower(btrim(category)) = 'report';

-- Read Storage metadata only to seed byte reporting. Object deletion remains an
-- API operation; direct writes to the managed Storage schema are prohibited.
update public.player_documents as document
set object_size_bytes = nullif(storage_object.metadata ->> 'size', '')::bigint
from storage.objects as storage_object
where document.object_size_bytes is null
  and document.storage_path is not null
  and storage_object.bucket_id = 'player-documents'
  and storage_object.name = document.storage_path
  and (storage_object.metadata ->> 'size') ~ '^[0-9]+$';

create or replace function public.set_player_document_pdf_lifecycle()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
  source_fields_changed boolean := false;
  expiry_explicitly_changed boolean := false;
begin
  -- Automated retention is deliberately report-only and is enforced in both
  -- the database trigger and the application layer.
  if lower(btrim(coalesce(new.category, ''))) <> 'report' then
    new.expires_at := null;
    return new;
  end if;

  if tg_op = 'UPDATE' then
    source_fields_changed :=
      new.category is distinct from old.category
      or new.uploaded_at is distinct from old.uploaded_at
      or new.series_end is distinct from old.series_end;
    expiry_explicitly_changed := new.expires_at is distinct from old.expires_at;
  end if;

  if new.expires_at is null
     or (source_fields_changed and not expiry_explicitly_changed) then
    if new.series_end is not null and new.series_end > 0 then
      new.expires_at := new.series_end + 86400.0;
    elsif new.uploaded_at > 0 then
      new.expires_at := new.uploaded_at + 604800.0;
    end if;
  end if;

  return new;
end
$$;

revoke all on function public.set_player_document_pdf_lifecycle() from public;
revoke all on function public.set_player_document_pdf_lifecycle() from anon, authenticated;
grant execute on function public.set_player_document_pdf_lifecycle() to service_role;

drop trigger if exists set_player_document_pdf_lifecycle on public.player_documents;
create trigger set_player_document_pdf_lifecycle
before insert or update of category, uploaded_at, series_end, expires_at
on public.player_documents
for each row
execute function public.set_player_document_pdf_lifecycle();

create table if not exists public.player_document_cleanup_runs (
  id uuid primary key,
  bucket_id text not null default 'player-documents',
  status text not null,
  requested_dry_run boolean not null,
  effective_dry_run boolean not null,
  deletion_enabled boolean not null,
  batch_limit smallint not null,
  candidate_count integer not null default 0,
  candidate_bytes bigint not null default 0,
  claimed_count integer not null default 0,
  deleted_count integer not null default 0,
  deleted_bytes bigint not null default 0,
  skipped_count integer not null default 0,
  error_count integer not null default 0,
  error_summary text,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  constraint player_document_cleanup_runs_status_valid
    check (status in ('running', 'completed', 'partial_failure', 'failed')),
  constraint player_document_cleanup_runs_batch_limit_valid
    check (batch_limit between 1 and 100),
  constraint player_document_cleanup_runs_counts_nonnegative
    check (
      candidate_count >= 0
      and candidate_bytes >= 0
      and claimed_count >= 0
      and deleted_count >= 0
      and deleted_bytes >= 0
      and skipped_count >= 0
      and error_count >= 0
    ),
  constraint player_document_cleanup_runs_finished_after_start
    check (finished_at is null or finished_at >= started_at)
);

comment on table public.player_document_cleanup_runs is
  'Service-only aggregate summaries for dry-run and live report PDF cleanup invocations.';

alter table public.player_document_cleanup_runs enable row level security;

-- No anon or authenticated policy: the Edge Function authenticates a secret
-- key and uses service_role. Explicit grants support current Data API defaults.
revoke all on table public.player_document_cleanup_runs from public;
revoke all on table public.player_document_cleanup_runs from anon, authenticated;
grant select, insert, update on table public.player_document_cleanup_runs to service_role;
grant select, update, delete on table public.player_documents to service_role;

create index if not exists player_documents_cleanup_eligible_idx
on public.player_documents (expires_at, id)
include (storage_path, object_size_bytes, delete_attempts)
where is_pinned = 0
  and storage_deleted_at is null
  and storage_path is not null
  and expires_at is not null
  and lower(btrim(category)) = 'report'
  and cleanup_claimed_at is null
  and cleanup_claim_token is null
  and lifecycle_status in (
    'pending_upload', 'active', 'delete_failed', 'upload_failed'
  );

create index if not exists player_documents_cleanup_stale_claim_idx
on public.player_documents (cleanup_claimed_at, id)
where lifecycle_status = 'pending_delete'
  and cleanup_claimed_at is not null
  and cleanup_claim_token is not null;

create index if not exists player_document_cleanup_runs_started_idx
on public.player_document_cleanup_runs (started_at desc);

commit;
