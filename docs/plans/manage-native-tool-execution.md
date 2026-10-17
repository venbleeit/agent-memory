# Manage native-tool execution study

## Current call chain

`mem sleep` and the one-shot Dream worker both enter `Manage.sleep()`. The method first performs
T0 maintenance deterministically: date normalization, weight settlement, co-occurrence links,
exact-duplicate invalidation, near-duplicate group repair, and clustering. It then computes T1
proposals from the resulting active records. When a reasoner exists, `_review()` renders all open
proposals and their named records into one prompt, calls the text `Reasoner`, parses JSON-line
verdicts, enforces the per-kind caps, and calls `decide()` only for an open proposal. `decide()`
reopens the proposal, applies the mutation through Store methods, and appends the Decision Ledger.
Finally `Manage.sleep()` writes the Dream Report and optionally commits the Store repository.

The manual path holds the Dream run and maintenance locks around `Manage.sleep()`. Automatic
Dreaming adds the persisted claim/lease and stable dream id, then the worker takes the same locks
and calls the same method. PR #106 did not change this chain. Its `ToolHostReasoner` class can be
constructed for a Manage Host, but Manage invokes only `__call__`; `converse()` and the Write
toolkit are not used.

## Reusable boundary and non-reusable toolkit

The reusable piece is the executor transport: an endpoint can drive a typed loop and a Host can
receive a per-job stdio MCP server. The Write toolkit itself is not a Manage authority model.
Manage should not expose Store record, correct, delete, merge, or filesystem tools. Those would
bypass open-proposal membership, caps, stale-target checks, the Decision Ledger, and report
accounting.

A separate PR can add a `ManageReviewToolkit` with one operation:

- `submit_verdicts(verdicts)`: submit the complete judgement set under the existing verdict
  schema. The tool validates proposal ids and verdict payloads but performs no mutation.

`Manage._review()` should then retain ownership of cap enforcement and call the existing
`decide()` path for accepted verdicts. T0, proposal generation, claim/lease handling, locks,
mutation guards, Decision Ledger, Dream Report, and Git behavior remain unchanged. The existing
text Host and endpoint paths remain selectable until the new path has paired verification.

## Why this is a separate PR

Manage has a different completion object and authority boundary from Write. Sharing only the
transport avoids inventing a second memory-write algorithm, while a dedicated toolkit prevents a
Write `submit_operations` schema from expanding Manage authority. Verification must cover unknown
and stale proposal ids, malformed verdicts, per-kind caps, partial tool failure, no submission,
timeout, claim recovery, and concurrent mutation under the current locks before native mode can
become a default.
