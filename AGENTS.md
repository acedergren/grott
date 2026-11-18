# Grott

Fork of the Growatt inverter monitor: reads, parses and optionally forwards raw inverter metrics.

## Code comments

Code is the documentation. Make the code say it first: better names, smaller functions, types that forbid bad states, and tests that show behavior. Comment only what the code cannot say.

A comment is justified for:
- Why, not what: a non-obvious reason, constraint or trade-off ("Growatt sends little-endian here despite the spec").
- Workarounds and external quirks, with a link to the issue, upstream bug or spec section.
- Invariants and safety: `unsafe`, locking/concurrency assumptions, protocol offsets, security-sensitive checks, units and ranges.
- Public API doc comments (Python docstrings) on exported items whose name and types don't fully explain use, errors or side effects.
- `TODO(#123)`: only with an issue number. No bare TODO/FIXME.
- Required license or generated-file headers.

Not justified (delete on sight in code you touch):
- Restating what the next line does, or explaining a name (rename instead).
- History: "changed", "fixed", "added by", dates, authors, bot names, PR or chat references (git and the PR hold history).
- Commented-out code.
- Section banners and decorative dividers.
- Agent narration or reasoning ("Now we handle...", "As requested...").
- Decisions and designs longer than two lines: put them in docs/ (ADR or docs/contracts) and link.

In review, an unjustified comment is a change request. Don't add comments to code you didn't otherwise change.
