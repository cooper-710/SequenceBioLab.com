import assert from "node:assert/strict";
import test from "node:test";

import {
  isEligibleCandidate,
  mapWithConcurrency,
  normalizeBatchLimit,
  resolveExecutionMode,
  toCandidateManifest,
  type CandidateRow,
} from "./lifecycle.ts";

const baseCandidate: CandidateRow = {
  id: 42,
  storage_path: "42.pdf",
  category: "report",
  expires_at: 1_776_729_600,
  is_pinned: 0,
  object_size_bytes: 3_000_000,
  lifecycle_status: "active",
  delete_attempts: 0,
  last_delete_error: null,
  storage_deleted_at: null,
  cleanup_claimed_at: null,
  cleanup_claim_token: null,
};

test("cleanup remains dry-run unless both safeguards allow deletion", () => {
  assert.deepEqual(resolveExecutionMode({}, undefined), {
    requestedDryRun: true,
    effectiveDryRun: true,
    deletionEnabled: false,
  });
  assert.equal(resolveExecutionMode({ dry_run: false }, undefined).effectiveDryRun, true);
  assert.equal(resolveExecutionMode({ dry_run: true }, "true").effectiveDryRun, true);
  assert.equal(resolveExecutionMode({ dry_run: false }, "true").effectiveDryRun, false);
  assert.equal(resolveExecutionMode({ dry_run: false }, "1").effectiveDryRun, true);
});

test("batch limits are bounded to the hard safety cap", () => {
  assert.equal(normalizeBatchLimit(undefined), 100);
  assert.equal(normalizeBatchLimit(25.8), 25);
  assert.equal(normalizeBatchLimit(1_000), 100);
  assert.equal(normalizeBatchLimit(0), 100);
});

test("only expired, unpinned report rows with safe paths are eligible", () => {
  const nowEpochSeconds = 1_777_593_600;
  assert.equal(isEligibleCandidate(baseCandidate, nowEpochSeconds), true);
  assert.equal(
    isEligibleCandidate(
      { ...baseCandidate, lifecycle_status: "pending_upload" },
      nowEpochSeconds,
    ),
    true,
  );
  assert.equal(
    isEligibleCandidate(
      { ...baseCandidate, lifecycle_status: "upload_failed" },
      nowEpochSeconds,
    ),
    true,
  );
  assert.equal(
    isEligibleCandidate({ ...baseCandidate, category: " WORKOUT " }, nowEpochSeconds),
    false,
  );
  assert.equal(
    isEligibleCandidate({ ...baseCandidate, category: null }, nowEpochSeconds),
    false,
  );
  assert.equal(
    isEligibleCandidate({ ...baseCandidate, category: "scouting" }, nowEpochSeconds),
    false,
  );
  assert.equal(
    isEligibleCandidate({ ...baseCandidate, is_pinned: 1 }, nowEpochSeconds),
    false,
  );
  assert.equal(
    isEligibleCandidate(
      { ...baseCandidate, expires_at: nowEpochSeconds + 1 },
      nowEpochSeconds,
    ),
    false,
  );
  assert.equal(
    isEligibleCandidate({ ...baseCandidate, storage_path: "other.pdf" }, nowEpochSeconds),
    false,
  );
  assert.equal(
    isEligibleCandidate(
      { ...baseCandidate, lifecycle_status: "pending_delete" },
      nowEpochSeconds,
    ),
    false,
  );
  assert.equal(
    isEligibleCandidate(
      {
        ...baseCandidate,
        cleanup_claimed_at: nowEpochSeconds - 30,
        cleanup_claim_token: "f97758b9-8eef-46b0-9213-35ed8b375281",
      },
      nowEpochSeconds,
    ),
    false,
  );
});

test("dry-run manifest exposes only the bounded review fields", () => {
  assert.deepEqual(toCandidateManifest(baseCandidate), {
    id: 42,
    storage_path: "42.pdf",
    expires_at: 1_776_729_600,
    object_size_bytes: 3_000_000,
  });
});

test("bounded concurrency preserves result order", async () => {
  const result = await mapWithConcurrency([3, 1, 2], 2, async (value) => {
    await new Promise((resolve) => setTimeout(resolve, value));
    return value * 2;
  });

  assert.deepEqual(result, [6, 2, 4]);
});
