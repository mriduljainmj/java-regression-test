# Demo runbook

Three staged changes that each show a different capability. Each script makes a
one-file change and commits it locally; **you push when you're ready to narrate**,
which is what triggers the workflow.

> Each script commits only its single source file. The demo kit itself is a
> separate committed change, so `reset.sh` never deletes these scripts.

## Before you start

```bash
# 1. Generate the local report so the dashboard's test pane is populated
mvn -f java-component/pom.xml verify

# 2. Start the dashboard (leave it open on screen all demo)
export GITHUB_TOKEN=ghp_...        # fine-grained PAT, Actions: read on this repo
python3 dashboard/server.py        # open the URL it prints

# 3. Make sure main is clean and pushed
git status      # should be clean
```

Keep two things on screen: the **dashboard** and a **terminal**.

---

## Segment A — "it generates the right tests"  (~90s)

```bash
./demo/01-add-validation.sh        # adds a max-price cap (new 400 path)
git push
```

**Say while the run goes:** "I added a rule — product price can't exceed 100000.
Watch the `generate-tests` run start in the dashboard." When the PR appears:
open it, show the new boundary scenario the agent wrote, point out it reused the
existing step phrasing so no new glue was needed.

**Then:** merge the PR → the `regression` run goes green on the dashboard. Code
and tests are back in sync.

---

## Segment B — "it knows when NOT to write tests"  (~60s)

```bash
./demo/02-refactor.sh              # renames an internal constant, no behavior change
git push
```

**Say:** "This time I only renamed an internal constant — nothing a user can
observe changed." The `generate-tests` run fires but produces **no PR**. Open the
run log and show the line: *"purely internal … no tests needed."*

**The point:** it's reading the diff for meaning, not pattern-matching — it won't
spam you with tests for a refactor.

---

## Segment C (optional finale) — "it writes its own test code"

```bash
./demo/04-new-endpoint.sh          # adds GET /api/v1/orders (list all orders)
git push
```

Adds a brand-new endpoint with **no** matching step definition, so the agent must
propose a Java `STEPDEF` block (new glue using `TestContext`) plus scenarios that
list orders.

**Say:** "I added a list-all-orders endpoint and wrote zero test code. Watch the
agent write its own step definitions." When the PR lands, open the
`STEPDEF`/`*StepDefinitions.java` file in the diff and show the glue it wrote.

**Verified deterministically** (foundation, not the live model output):
- compiles and the existing suite stays green with the endpoint added;
- a natural "list all orders" scenario matches **none** of the 36 existing step
  patterns → the agent is forced into glue generation, which is the point.

**Higher LLM variance** than A/B/D — the *quality* of the generated glue isn't
guaranteed. Rehearse with one real push this morning, and keep the merged
review-API PR open in a tab as a backup to show a known-good generated-glue
result if the live run wobbles. If the PR's regression check is red, that's the
honest story too: "the gate caught imperfect generation before merge."

---

## Segment D — "the safety net" (deterministic, zero LLM risk)  (~60s)

Save this for last — it always works because it's just a failing test.

```bash
./demo/03-break.sh                 # changes an error message the suite asserts on
git push
```

**Say:** "Now imagine a developer changes a response message but forgets the
tests." The `regression` run goes **RED**; the dashboard's right pane shows the
exact failing scenario and step. "The gate caught the drift before it shipped —
this is the whole point."

---

## Reset between rehearsals

```bash
./demo/reset.sh        # undoes the last demo commit if it hasn't been pushed
```

Already pushed it? Reset locally then `git push --force-with-lease`, or just roll
forward — the repo is a demo sandbox.

## Ordering recommendation

A → B → D. Only A depends on live model output (and it's the most reliable kind);
B's "no PR" result is reliable; D is deterministic. C is the only high-variance
piece — slot it in only if rehearsed.
