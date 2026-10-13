# Global Entry and Lazy Scope Correction (2026-10-05)

Historical checkpoint only. Its 3.0 coexistence statement is superseded by the explicitly authorized 4.0-only cutover in `outputs/p7/global-4-only-cutover-2026-10-05.json`; this note does not authorize restoring 3.0 or changing current configuration.

## Root cause

The frozen acceptance ledger was being treated as a pre-build backlog. That made the work drift toward pre-creating adapters, experts and application-specific scenarios even when no current task consumed them. The 92 G6 scenarios remain valid coverage and regression boundaries, but they are not 92 applications to build in advance.

## Correction

- The default behavior for every new Codex conversation is provided by the user-level `C:\Users\Administrator\.codex\AGENTS.md`.
- The 4.0 Skill remains a task capability package. It is discovered in the normal Skill catalog and is referenced only when the current task needs its narrow routing or guidance; no password, activation phrase or manual Skill selection is required.
- Existing Skills, MCPs, native subagents, CLIs, APIs and professional project runtimes remain the first integration choice. No peripheral application is copied or rewritten without a concrete current-task consumer.
- The 3.0 project and historical materials remain read-only, but its global runtime mount was explicitly retired. `config.toml`, model/provider/reasoning settings, credentials, plugins, audio devices and microphone paths remain protected except for the user-authorized entry-block cutover recorded in the current cutover receipt.

## Evidence

The no-model `codex debug prompt-input` check was run for a new session context from `C:\Users\Administrator`. Its model-visible input contained `agents_md.instructions` with the global title and the lazy-action rules. This verifies instruction injection for a new run; it does not claim hot reload of an already-open conversation.

Current content hashes:

- Global entry: `C:\Users\Administrator\.codex\AGENTS.md` — `2DA4A5D047CF907392C51DF99C4B80E08256BB7DE70E0AAF928FCFD7DECF734B`.
- 4.0 source and installed Skill: `07AEBEA36B307FAB5C62726436A53F7CA55EA281BE1BE8F8E400E209D69DFE02`.
- Existing 3.0 Skill: `482F2BACD49B1DF22EE5159223CFB3994EA506BD948757B83A2195740148E131`.
- Protected Codex config: `AE731FB7853BE02673402466840BAC5E25ED2CA7DC45A042C01EF6A5E4582146`.

## Acceptance boundary

This correction makes the global entry and lazy scope usable. The core global entry and 4.0 Skill are installed; this is not a claim that broader P0-P6 acceptance or all of P7 is complete. The latest P6 audit remains `passed=false` and G6 remains open. The 92-scenario ledger is retained for full capability acceptance but no longer blocks the minimum entry from being used. The latest refreshed audit can currently substantiate 0 of the 92 G6 scenarios because its acceptance/test receipts are stale against the current configuration and run; it classifies 22 as failed-or-stale and 92 as not-run-or-pending. An earlier audit recorded 22 passes, but those are historical and are not carried forward as current evidence. This is an evidence-currentness result, not proof that the implementation itself failed all 92 scenarios.

## Recovery

If rollback is ever requested, remove only the newly created global entry after confirming its current hash is still the recorded hash. Do not delete or restore over user changes, and leave the 3.0 Skill and `config.toml` untouched.
