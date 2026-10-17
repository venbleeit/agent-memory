# Cross-OS hosts, subagent capture, and secret redaction

## Problem and target

Claude Code on Windows and Claude Code in WSL keep separate settings, so only the WSL install
reaches the Store; the core cannot run natively on Windows because its lock and hook timeout
are POSIX-only. Subagent work lives in its own transcript beside the parent session, so a
boundary sees only the handback and the work itself is never archived. Transcripts are archived
verbatim, so a pasted token or key becomes durable raw material and can be distilled into a
memory.

The target keeps one Store and one operating system doing the locking:

- A Windows host reaches the WSL install through a bridge. Setup writes exec-form hooks that
  invoke the WSL hook binary through the WSL launcher, translates Windows transcript paths, and
  renders the skill and optional MCP entry with the bridged command. No core change runs on
  Windows.
- A subagent stop is a boundary for a child session. The child is archived as its own session
  whose identity names its parent, opens with a provenance line naming the parent and agent
  type, and is distilled like any session.
- Redaction is a core guardrail at both chokepoints: the archive append and the memory write
  pipeline. A built-in catalogue covers common credential shapes; config adds patterns and can
  disable it. A read-only scan reports secrets already in the Store without their values;
  removal stays a human decision.

## Work units

1. Update the host-adapter design doc for the Windows bridge and subagent boundary, add a
   redaction design doc, and update the design index.
2. Redaction: failing unit and red-team tests for each catalogue shape, config patterns,
   idempotence, both chokepoints and the read-only scan; then the core module, config section,
   chokepoint calls and the scan command.
3. Subagent boundary: failing tests over a recorded subagent transcript fixture for child
   identity, parent provenance, executor-marker inertness and repeat-stop idempotence; then the
   dialect event and child capture.
4. Windows bridge: failing tests for path translation, exec-form hook rendering, preserving
   merge into the Windows settings file, bridged MCP and skill; then the setup option and the
   hook path dialect.
5. Verify end to end from the Windows side against a temporary Store, run the full suite,
   commit, push, open a PR and drive CI green.
