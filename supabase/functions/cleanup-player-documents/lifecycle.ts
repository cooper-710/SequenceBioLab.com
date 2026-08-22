export const PLAYER_DOCUMENT_BUCKET = "player-documents";
export const DEFAULT_BATCH_LIMIT = 100;
export const MAX_BATCH_LIMIT = 100;
export const CLAIM_TTL_SECONDS = 15 * 60;

export interface CleanupRequestBody {
  dry_run?: boolean;
  batch_limit?: number;
}

export interface CandidateRow {
  id: number;
  storage_path: string | null;
  category: string | null;
  expires_at: number | string | null;
  is_pinned: number | boolean | null;
  object_size_bytes: number | string | null;
  lifecycle_status: string | null;
  delete_attempts: number;
  last_delete_error: string | null;
  storage_deleted_at: number | string | null;
  cleanup_claimed_at: number | string | null;
  cleanup_claim_token: string | null;
}

export interface CandidateManifestEntry {
  id: number;
  storage_path: string;
  expires_at: number;
  object_size_bytes: number;
}

export interface ExecutionMode {
  requestedDryRun: boolean;
  effectiveDryRun: boolean;
  deletionEnabled: boolean;
}

export function deletionFlagEnabled(rawValue: string | undefined): boolean {
  return rawValue?.trim().toLowerCase() === "true";
}

export function resolveExecutionMode(
  request: CleanupRequestBody,
  deletionFlag: string | undefined,
): ExecutionMode {
  const requestedDryRun = request.dry_run !== false;
  const deletionEnabled = deletionFlagEnabled(deletionFlag);

  return {
    requestedDryRun,
    effectiveDryRun: requestedDryRun || !deletionEnabled,
    deletionEnabled,
  };
}

export function normalizeBatchLimit(
  value: unknown,
  fallback = DEFAULT_BATCH_LIMIT,
): number {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed) || parsed < 1) {
    return Math.min(Math.max(Math.floor(fallback), 1), MAX_BATCH_LIMIT);
  }

  return Math.min(Math.floor(parsed), MAX_BATCH_LIMIT);
}

export function normalizedByteSize(value: number | string | null): number {
  const parsed = typeof value === "number" ? value : Number(value ?? 0);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return 0;
  }

  return Math.floor(parsed);
}

export function storageAbsenceVerificationError(
  exists: boolean,
  errorMessage: string | null,
): string | null {
  // storage-js reports a missing object as `data: false` together with a
  // 400/404 Storage error. The false result is the successful absence signal.
  if (exists === false) {
    return null;
  }
  return errorMessage ?? "object still exists";
}

export function isSafePlayerPdfPath(candidate: CandidateRow): boolean {
  return candidate.storage_path?.trim() === `${candidate.id}.pdf`;
}

export function isEligibleCandidate(
  candidate: CandidateRow,
  referenceEpochSeconds: number,
): boolean {
  if (
    Number(candidate.is_pinned ?? 0) !== 0
    || candidate.storage_deleted_at !== null
    || candidate.cleanup_claimed_at !== null
    || candidate.cleanup_claim_token !== null
  ) {
    return false;
  }

  if (candidate.category?.trim().toLowerCase() !== "report") {
    return false;
  }

  const lifecycleStatus = candidate.lifecycle_status?.trim().toLowerCase();
  if (
    lifecycleStatus !== "pending_upload"
    && lifecycleStatus !== "active"
    && lifecycleStatus !== "delete_failed"
    && lifecycleStatus !== "upload_failed"
  ) {
    return false;
  }

  if (!isSafePlayerPdfPath(candidate) || !candidate.expires_at) {
    return false;
  }

  const expiry = Number(candidate.expires_at);
  return Number.isFinite(expiry) && expiry > 0 && expiry <= referenceEpochSeconds;
}

export function toCandidateManifest(candidate: CandidateRow): CandidateManifestEntry {
  return {
    id: candidate.id,
    storage_path: candidate.storage_path as string,
    expires_at: Number(candidate.expires_at),
    object_size_bytes: normalizedByteSize(candidate.object_size_bytes),
  };
}

export async function mapWithConcurrency<T, R>(
  items: readonly T[],
  concurrency: number,
  worker: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let nextIndex = 0;
  const workerCount = Math.min(Math.max(Math.floor(concurrency), 1), items.length);

  await Promise.all(
    Array.from({ length: workerCount }, async () => {
      while (nextIndex < items.length) {
        const index = nextIndex;
        nextIndex += 1;
        results[index] = await worker(items[index], index);
      }
    }),
  );

  return results;
}
