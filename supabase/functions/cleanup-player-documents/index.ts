import "@supabase/functions-js/edge-runtime.d.ts";
import { withSupabase } from "@supabase/server";

import {
  CLAIM_TTL_SECONDS,
  DEFAULT_BATCH_LIMIT,
  isEligibleCandidate,
  mapWithConcurrency,
  MAX_BATCH_LIMIT,
  normalizeBatchLimit,
  normalizedByteSize,
  PLAYER_DOCUMENT_BUCKET,
  resolveExecutionMode,
  toCandidateManifest,
  type CandidateRow,
  type CleanupRequestBody,
} from "./lifecycle.ts";

const SELECT_COLUMNS = [
  "id",
  "storage_path",
  "category",
  "expires_at",
  "is_pinned",
  "object_size_bytes",
  "lifecycle_status",
  "delete_attempts",
  "last_delete_error",
  "storage_deleted_at",
  "cleanup_claimed_at",
  "cleanup_claim_token",
].join(",");

function messageFrom(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === "string") {
    return error;
  }
  try {
    return JSON.stringify(error);
  } catch {
    return "Unknown cleanup error";
  }
}

function compactErrors(errors: readonly string[]): string | null {
  if (errors.length === 0) {
    return null;
  }
  return errors.slice(0, 10).join(" | ").slice(0, 2_000);
}

// Service-to-service authentication is enforced by @supabase/server. The
// caller must provide a Supabase secret key in the `apikey` header.
export default {
  fetch: withSupabase({ auth: "secret" }, async (req, ctx) => {
    if (req.method !== "POST") {
      return Response.json({ error: "Method not allowed" }, { status: 405 });
    }

    const startedAt = new Date();
    const referenceEpochSeconds = startedAt.getTime() / 1_000;
    const staleClaimCutoff = referenceEpochSeconds - CLAIM_TTL_SECONDS;
    const runId = crypto.randomUUID();
    let runInserted = false;
    const errors: string[] = [];

    const body = await req.json().catch(() => ({})) as CleanupRequestBody;
    const execution = resolveExecutionMode(
      body,
      Deno.env.get("PLAYER_DOCUMENT_CLEANUP_DELETE_ENABLED"),
    );
    const configuredLimit = normalizeBatchLimit(
      Deno.env.get("PLAYER_DOCUMENT_CLEANUP_MAX_BATCH"),
      MAX_BATCH_LIMIT,
    );
    const batchLimit = Math.min(
      normalizeBatchLimit(body.batch_limit, DEFAULT_BATCH_LIMIT),
      configuredLimit,
    );
    const summary = {
      bucket_id: PLAYER_DOCUMENT_BUCKET,
      requested_dry_run: execution.requestedDryRun,
      effective_dry_run: execution.effectiveDryRun,
      deletion_enabled: execution.deletionEnabled,
      batch_limit: batchLimit,
      candidate_count: 0,
      candidate_bytes: 0,
      claimed_count: 0,
      deleted_count: 0,
      deleted_bytes: 0,
      skipped_count: 0,
      error_count: 0,
    };

    const finishRun = async (status: "completed" | "partial_failure" | "failed") => {
      summary.error_count = errors.length;
      const { error } = await ctx.supabaseAdmin
        .from("player_document_cleanup_runs")
        .update({
          status,
          ...summary,
          error_summary: compactErrors(errors),
          finished_at: new Date().toISOString(),
        })
        .eq("id", runId);

      if (error) {
        console.error("Unable to finalize player PDF cleanup run", {
          runId,
          error: error.message,
        });
      }
      return error;
    };

    const releaseClaim = async (candidate: CandidateRow, reason: string) => {
      const { error } = await ctx.supabaseAdmin
        .from("player_documents")
        .update({
          lifecycle_status: "delete_failed",
          last_delete_error: reason.slice(0, 2_000),
          cleanup_claimed_at: null,
          cleanup_claim_token: null,
        })
        .eq("id", candidate.id)
        .eq("storage_path", candidate.storage_path as string)
        .eq("lifecycle_status", "pending_delete")
        .eq("cleanup_claim_token", runId);
      if (error) {
        errors.push(`release ${candidate.id}: ${error.message}`);
      }
    };

    try {
      const { error: insertError } = await ctx.supabaseAdmin
        .from("player_document_cleanup_runs")
        .insert({
          id: runId,
          status: "running",
          ...summary,
          started_at: startedAt.toISOString(),
        });

      if (insertError) {
        throw new Error(`Unable to start cleanup audit record: ${insertError.message}`);
      }
      runInserted = true;

      if (!execution.effectiveDryRun) {
        // Recover only expired leases in live mode. A function crash therefore
        // delays a row for at most the lease window without mutating dry-run data.
        const { data: staleClaims, error: staleClaimError } = await ctx.supabaseAdmin
          .from("player_documents")
          .select("id")
          .eq("category", "report")
          .eq("lifecycle_status", "pending_delete")
          .lt("cleanup_claimed_at", staleClaimCutoff)
          .not("cleanup_claim_token", "is", null)
          .order("cleanup_claimed_at", { ascending: true })
          .limit(MAX_BATCH_LIMIT);

        if (staleClaimError) {
          throw new Error(`Unable to list stale cleanup claims: ${staleClaimError.message}`);
        }

        const staleClaimIds = (staleClaims ?? []).map((row) => row.id as number);
        if (staleClaimIds.length > 0) {
          const { error: reclaimError } = await ctx.supabaseAdmin
            .from("player_documents")
            .update({
              lifecycle_status: "delete_failed",
              cleanup_claimed_at: null,
              cleanup_claim_token: null,
              last_delete_error: "Recovered an expired automated cleanup claim.",
            })
            .in("id", staleClaimIds)
            .eq("category", "report")
            .eq("lifecycle_status", "pending_delete")
            .lt("cleanup_claimed_at", staleClaimCutoff);

          if (reclaimError) {
            throw new Error(`Unable to recover stale cleanup claims: ${reclaimError.message}`);
          }
        }
      }

      // Fetch extra rows so a malformed legacy row cannot crowd every safe
      // candidate out of the bounded batch. Code-level checks remain authoritative.
      const queryLimit = Math.min(batchLimit * 3, MAX_BATCH_LIMIT * 3);
      const { data, error: candidateError } = await ctx.supabaseAdmin
        .from("player_documents")
        .select(SELECT_COLUMNS)
        .not("storage_path", "is", null)
        .ilike("storage_path", "%.pdf")
        .not("expires_at", "is", null)
        .lte("expires_at", referenceEpochSeconds)
        .eq("is_pinned", 0)
        .is("storage_deleted_at", null)
        .eq("category", "report")
        .in("lifecycle_status", [
          "pending_upload",
          "active",
          "delete_failed",
          "upload_failed",
        ])
        .is("cleanup_claimed_at", null)
        .is("cleanup_claim_token", null)
        .order("expires_at", { ascending: true })
        .order("id", { ascending: true })
        .limit(queryLimit);

      if (candidateError) {
        throw new Error(`Unable to list cleanup candidates: ${candidateError.message}`);
      }

      const fetched = (data ?? []) as CandidateRow[];
      const candidates = fetched
        .filter((candidate) => isEligibleCandidate(candidate, referenceEpochSeconds))
        .slice(0, batchLimit);

      summary.candidate_count = candidates.length;
      summary.candidate_bytes = candidates.reduce(
        (total, candidate) => total + normalizedByteSize(candidate.object_size_bytes),
        0,
      );
      summary.skipped_count = fetched.length - candidates.length;

      if (execution.effectiveDryRun || candidates.length === 0) {
        const finalizeError = await finishRun("completed");
        return Response.json(
          {
            run_id: runId,
            ...summary,
            status: "completed",
            candidates: candidates.map(toCandidateManifest),
            note: execution.effectiveDryRun
              ? "Dry-run only; no Storage objects or database rows were deleted."
              : "No eligible player PDFs were found.",
          },
          { status: finalizeError ? 500 : 200 },
        );
      }

      const claimResults = await mapWithConcurrency(candidates, 8, async (candidate) => {
        const { data: claimed, error } = await ctx.supabaseAdmin
          .from("player_documents")
          .update({
            lifecycle_status: "pending_delete",
            delete_attempts: candidate.delete_attempts + 1,
            last_delete_error: null,
            cleanup_claimed_at: referenceEpochSeconds,
            cleanup_claim_token: runId,
          })
          .eq("id", candidate.id)
          .eq("storage_path", candidate.storage_path as string)
          .eq("category", "report")
          .eq("is_pinned", 0)
          .is("storage_deleted_at", null)
          .lte("expires_at", referenceEpochSeconds)
          .in("lifecycle_status", [
            "pending_upload",
            "active",
            "delete_failed",
            "upload_failed",
          ])
          .is("cleanup_claimed_at", null)
          .is("cleanup_claim_token", null)
          .select(SELECT_COLUMNS)
          .maybeSingle();

        if (error) {
          errors.push(`claim ${candidate.id}: ${error.message}`);
          return null;
        }
        return claimed as CandidateRow | null;
      });

      const claimed = claimResults.filter(
        (candidate): candidate is CandidateRow => candidate !== null,
      );
      summary.claimed_count = claimed.length;
      summary.skipped_count += candidates.length - claimed.length;

      if (claimed.length === 0) {
        const status = errors.length > 0 ? "partial_failure" : "completed";
        const finalizeError = await finishRun(status);
        return Response.json(
          { run_id: runId, ...summary, status, errors: errors.slice(0, 10) },
          { status: finalizeError || errors.length > 0 ? 500 : 200 },
        );
      }

      const paths = claimed.map((candidate) => candidate.storage_path as string);
      const { error: removeError } = await ctx.supabaseAdmin.storage
        .from(PLAYER_DOCUMENT_BUCKET)
        .remove(paths);

      if (removeError) {
        const reason = `Storage delete failed: ${removeError.message}`;
        errors.push(reason);
        await mapWithConcurrency(claimed, 8, (candidate) => releaseClaim(candidate, reason));
        const finalizeError = await finishRun("failed");
        return Response.json(
          {
            run_id: runId,
            ...summary,
            status: "failed",
            errors: errors.slice(0, 10),
          },
          { status: finalizeError ? 500 : 502 },
        );
      }

      // Supabase deletions are irreversible. Verify each requested object is absent
      // before removing the corresponding application metadata row.
      const verification = await mapWithConcurrency(claimed, 10, async (candidate) => {
        const path = candidate.storage_path as string;
        const { data: exists, error } = await ctx.supabaseAdmin.storage
          .from(PLAYER_DOCUMENT_BUCKET)
          .exists(path);

        if (error) {
          return { candidate, error: `verify ${candidate.id}: ${error.message}` };
        }
        if (exists) {
          return { candidate, error: `verify ${candidate.id}: object still exists` };
        }
        return { candidate, error: null };
      });

      const confirmed = verification
        .filter((result) => result.error === null)
        .map((result) => result.candidate);
      const unconfirmed = verification.filter((result) => result.error !== null);

      for (const result of unconfirmed) {
        errors.push(result.error as string);
      }
      await mapWithConcurrency(unconfirmed, 8, (result) =>
        releaseClaim(result.candidate, result.error as string)
      );

      if (confirmed.length > 0) {
        const confirmedIds = confirmed.map((candidate) => candidate.id);
        const { error: metadataDeleteError } = await ctx.supabaseAdmin
          .from("player_documents")
          .delete()
          .in("id", confirmedIds)
          .eq("lifecycle_status", "pending_delete")
          .eq("cleanup_claim_token", runId);

        if (metadataDeleteError) {
          const reason = `Database metadata delete failed: ${metadataDeleteError.message}`;
          errors.push(reason);
          await mapWithConcurrency(confirmed, 8, async (candidate) => {
            const { error } = await ctx.supabaseAdmin
              .from("player_documents")
              .update({
                lifecycle_status: "delete_failed",
                storage_deleted_at: Date.now() / 1_000,
                last_delete_error: reason.slice(0, 2_000),
                cleanup_claimed_at: null,
                cleanup_claim_token: null,
              })
              .eq("id", candidate.id)
              .eq("storage_path", candidate.storage_path as string)
              .eq("lifecycle_status", "pending_delete")
              .eq("cleanup_claim_token", runId);
            if (error) {
              errors.push(`tombstone ${candidate.id}: ${error.message}`);
            }
          });
        } else {
          summary.deleted_count = confirmed.length;
          summary.deleted_bytes = confirmed.reduce(
            (total, candidate) => total + normalizedByteSize(candidate.object_size_bytes),
            0,
          );
        }
      }

      const status = errors.length > 0 ? "partial_failure" : "completed";
      const finalizeError = await finishRun(status);
      return Response.json(
        { run_id: runId, ...summary, status, errors: errors.slice(0, 10) },
        { status: finalizeError || errors.length > 0 ? 500 : 200 },
      );
    } catch (error) {
      errors.push(messageFrom(error));
      if (runInserted) {
        await finishRun("failed");
      }
      return Response.json(
        {
          run_id: runId,
          ...summary,
          status: "failed",
          errors: errors.slice(0, 10),
        },
        { status: 500 },
      );
    }
  }),
};
