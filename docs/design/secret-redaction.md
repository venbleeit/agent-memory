# Secret redaction

Credentials never become memory. Redaction is a core guardrail, not a host feature, so every
entry reaches it and no adapter can bypass it.

It applies at the two places text becomes durable: the archive append and the memory write
pipeline, before validation. Raw material is therefore append-only over already-redacted text;
nothing recoverable is lost because the secret was never admitted. The distillation prompt is
built from the same redacted increment, so a reasoner never sees the value either.

A match is replaced by a placeholder naming its kind, which keeps the surrounding sentence
useful and makes redaction idempotent. A built-in catalogue covers credential shapes with a
recognizable form: platform tokens, cloud keys, private-key blocks, bearer and basic
credentials, signed tokens, credentials embedded in connection strings, and assignments to
secret-named keys. The Store config adds patterns, which are validated at load and rejected
when malformed, and can switch redaction off for a controlled experiment.

Redaction over-matches rather than under-matches; a false positive costs a word, a false
negative costs a credential. Values that carry no recognizable shape remain the user's to keep
out of a session.

Secrets admitted before redaction existed are reported, not rewritten. A read-only scan lists
each hit by file, location and kind and never prints the value. Removal is a human-run
operation outside Manage, consistent with the rule that Manage never destroys information.
