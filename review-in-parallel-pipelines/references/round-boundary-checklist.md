# Round-boundary checklist

The round-boundary review (checkpoint 2) runs once after all of a round's
branches land on `main`. Its whole reason for existing is to catch the class of
defect that produces **no merge conflict and no test failure** — invisible to
the merge tool and the build, visible only by comparing branches against each
other and inspecting the integrated whole.

Work these four categories. Each entry is a concrete thing to grep/read for, not
an abstract worry.

## 1. Halo effects (cross-branch interference)

The defining round-boundary defect: two or more branches that are each clean in
isolation, but interfere once combined.

- **Duplicated logic.** Two branches independently implemented the same helper,
  validator, or constant. Symptom: the same function name/body defined in two
  modules; near-identical blocks in two files. Fix: consolidate to one home, have
  the other import it. *(This is the canonical halo — disjoint files, clean
  merge, green tests, duplicated logic.)*
- **Shadowed / dead code.** Branch A added a real implementation of something
  branch B left as a stub, or two branches both touched a registry/dispatch
  table and one silently wins. Symptom: a stub still present after a real
  implementation landed; a definition that's never reached.
- **Redundant dependencies.** Branch X added a package that overlaps one branch Y
  added (two date libraries, two HTTP clients). Two branches each added coverage
  exclusions or lint suppressions for similar patterns that could be one rule.

How to look: list each branch's added files/symbols and scan for overlap. `git
log <round-start>..HEAD --stat`; grep for duplicated function signatures across
the new files; diff the dependency manifest for additions from more than one
branch.

## 2. Architectural drift

Did the round's combined work stay within the planned shape, or bulge into
unplanned areas?

- New top-level modules/packages the plan didn't anticipate.
- A layer boundary crossed (e.g., a domain module now imports infrastructure)
  because two branches each took a half-step.
- Public API surface that grew more than the plan called for.

How to look: compare the round's net file/structure changes against the plan's
expected shape. Small per-branch diffs can still aggregate into a shape the plan
never described.

## 3. Open-thread carry-over

Deviations that individually were fine to defer but collectively need a decision.

- Multiple branches each left a "we'll clean this up later" / TODO / temporary
  shim. Individually deferrable; together they're a refinement round.
- Multiple branches noted the same upstream gap (a missing fixture, an absent
  abstraction). That gap is now confirmed by repetition — schedule it.

How to look: collect the deviations sections from every branch's report and the
TODO/FIXME markers added this round; cluster them. Repetition across branches is
the signal that a thread should become scheduled work, not linger.

## 4. Gate integrity

Are the green signals green for the *right* reasons?

- **Coverage gate.** Did any branch lower a threshold (`fail_under`, Kover/JaCoCo
  minimums) to escape a gate? Did total coverage drop while still passing because
  the threshold moved? Did a `# pragma: no cover` / `[ExcludeFromCodeCoverage]`
  get added over real (not native-only) code?
- **Tests.** Any test that used to run now silently skipped, `xfail`-ed, or
  deleted? Compare the collected test count before/after the round.
- **Build/lint.** Any new suppression (`# type: ignore`, `eslint-disable`,
  `|| true` in a build step) that hides a failure rather than fixing it?

How to look: diff the gate config files (`pyproject.toml`, `*.csproj`,
`build.gradle*`, CI yaml) across the round; compare test-collection counts; grep
the round's diff for suppression markers.

## Output

A numbered refinement punch-list — each item names the file(s) and a one-line
fix — handed to checkpoint 3 (refinement round) and dispatched before the next
planned feature phase. An empty list is a valid, common result: say the
integration is clean and proceed. Do not manufacture items to look thorough.
