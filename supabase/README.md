# Player PDF lifecycle infrastructure

This directory is source-controlled Supabase infrastructure. Nothing here is
linked or deployed automatically.

## Safety defaults

- `cleanup-player-documents` accepts only a Supabase secret key in the `apikey`
  header.
- Every request is a dry run unless its JSON body contains `"dry_run": false`
  **and** the deployed function secret
  `PLAYER_DOCUMENT_CLEANUP_DELETE_ENABLED=true`.
- Only rows whose normalized category is exactly `report` are eligible.
  Workouts, generic/uncategorized documents, and `is_pinned = 1` rows are
  excluded in both SQL and function code.
- A Storage path must exactly equal `{player_documents.id}.pdf`.
- Expired report rows in `pending_upload` or `upload_failed` are eligible too:
  an ambiguous upload response can leave the deterministic object stored and
  billed. They are claimed and deleted through the same guarded path as
  `active` and `delete_failed` reports.
- Batches are capped at 100 objects.
- Dry-run responses include a bounded manifest (`id`, `storage_path`,
  `expires_at`, and `object_size_bytes`) for pre-canary review.
- The function deletes through the Storage API, verifies object absence, and
  only then deletes the `player_documents` metadata row.
- Run summaries are written to the RLS-protected, service-only
  `player_document_cleanup_runs` table.

## Local checks

The pure lifecycle safeguards can be tested without Docker:

```sh
node --test supabase/functions/cleanup-player-documents/lifecycle.test.ts
```

For full integration testing, start the local Supabase stack after supplying a
base schema that contains the application-owned `public.player_documents`
table. The lifecycle migration fails clearly when that prerequisite is absent;
it will never create a partial replacement for the application table.

## Production rollout (not performed by this change)

1. Review and apply the migration to the correct project.
2. Deploy the function with deletion disabled.
3. Invoke dry runs using a secret API key and inspect run summaries.
4. Configure Cron/pg_net and Vault only after the candidate set is approved.
5. Enable live deletion by setting the environment flag and sending an explicit
   live request. Disable the flag to return immediately to dry-run behavior.

Supabase Storage deletion is permanent. This function has no restore path for
objects that have been deleted successfully.

The bucket block in `config.toml` is a local-development/reference declaration
only (private, PDF-only, 15 MiB per object). Do not wholesale-push this newly
initialized config over the existing hosted project. Review and reconcile each
remote setting explicitly.

Live runs use a numeric `cleanup_claimed_at` lease plus a UUID claim token. A
later live run reclaims `pending_delete` leases older than 15 minutes, while
dry runs never mutate lifecycle rows. Repeated failures remain visible as
`delete_failed` with a bounded `last_delete_error` for reconciliation.
