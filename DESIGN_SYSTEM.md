# Design system

Lives in [`.design/`](.design/) — dot-prefixed because it is tooling, not application
source. Start at [`.design/SKILL.md`](.design/SKILL.md).

**`.design/` is generated.** It is the source of truth for every design value, and the app
imports it rather than copying it, so there is nothing to edit locally. If something needs
to change, open a PR against `.design/` and have it reviewed in the design project first.
A `.design/` change merged without that review is drift.
