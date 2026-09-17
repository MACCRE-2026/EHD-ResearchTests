---
inclusion: always
---

# Physics honesty — non-negotiable

This project's inputs include figures from an AI collaborator **known to be optimistic**, and
from maker-community builds whose instrumentation is unstated. Its output is meant to support
a funding case. That combination is precisely where a number acquires confidence it never
earned.

Always applied, because the temptation is strongest in the file you are editing right now.

---

## 1. Never curve-fit. Never invent a coefficient.

No free parameter is ever tuned to make a model match a target, a claim, or a measurement.

When a model and a number disagree, the disagreement **is the result**. Report it. Do not
introduce a factor to close it, and do not quietly widen a tolerance until it passes.

If a coefficient is genuinely geometry- or condition-dependent and its value is not known, it
is a **named, documented model parameter** carrying its uncertainty — not a fitted constant.
`k_geo` is the live example: a parallel-plate coefficient standing in for a wire-to-plane
emitter, roughly a 10× band, labelled rather than replaced with something that happens to fit.

**Corollary — do not "fix" an inherited formula silently.** If a source's physics is
geometrically inconsistent, label the assumption, document the alternative, and leave the
number reproducible. A silent correction destroys the ability to tell what the source actually
claimed.

## 2. Every relation cites a reference and states its assumptions

A formula with no citation is an assertion. A formula with a citation but no stated idealising
assumptions is worse, because the citation lends it borrowed authority.

State what the relation assumes and where it therefore fails: uniform field, full momentum
transfer, no neutral drag, thin-wire limit, `d >> r`, steady state, dry air at STP.

## 3. Uncertainty propagates by low-water-mark

A derived quantity's confidence is bounded **above** by the worst of its inputs. It is never
the confidence of the last calculation performed.

`W(result) = min over inputs` — *principle 1, trust is a ceiling inherited from provenance*.

Because current, power, thrust and efficiency all descend from `k_geo`, they all inherit its
band. Reporting any of them as a tight figure is laundering, whether or not anyone intended it.

Every quantity carries its **basis**, and the ladder is ordered:

| Basis | Meaning |
|---|---|
| `measured` | Instrument reading with stated uncertainty |
| `solved` | Numerical solver output, with tool version and input hash recorded |
| `analytical-cited` | Closed form from a cited reference |
| `analytical-placeholder` | Correct form, uncertain coefficient |
| `claimed` | Asserted by a source, unverified |

**A `claimed` input can never produce a `validated` output.** That transition is the specific
failure this project exists to catch, and it must be impossible by construction rather than
prevented by vigilance.

## 4. An upper bound is labelled an upper bound everywhere it appears

Not once in a footnote. In the CSV column header, on the plot axis, in the spec-sheet row, in
the whitepaper table, in the docstring.

`T = I·d/µ` is a **mobility-limited ceiling** — it assumes every ion transfers all its momentum
to neutrals with no drag. Real thrust is lower. A ceiling presented without its label becomes a
prediction the moment it is quoted by someone who did not read the derivation, and that someone
is often the author six weeks later.

The same applies to efficiency figures derived from it.

## 5. A hand-check is a lead. Reproduction is the finding.

*Principle 7, verified means reproduced.* Several figures in this project were worked by hand
during planning. None of them counts as a finding until code reproduces it, and none may be
used to size, schedule or justify anything before then.

This cuts both ways: a hand-check that *contradicts* an inherited claim is also only a lead.
Do not rewrite a spec sheet on the strength of arithmetic done in a chat message.

## 6. A solver run nobody performed did not happen

FEMM, LTspice, QSPICE, Elmer and ParaView are GUI or external tools outside `pytest`. A
cross-check attributed to a solver that was never opened is
*principle 3, never report success over unperformed work*.

A solver-derived value is only `solved` if the run recorded its **tool version, input file hash,
and the values read back**. Absent that, it is `analytical-placeholder` at best.

## 7. Absent beats approximately correct

*Principle 2, an approximately-correct identifier is worse than an absent one.* A wrong
non-empty number propagates and gets acted on; a missing one degrades visibly.

When a value is known to be defective, **withhold it and record why** rather than publishing it
beside a caveat nobody will read. `sweep_stages.csv` is withheld from `examples/` on exactly
this basis.

## 8. Units and geometry live in identifiers

`r_wire_m`, not `wire`. `d_gap_m`, not `gap`. **Radius versus diameter is explicit in the
name**, always.

A 25 µm emitter read as a radius and as a diameter differ by **29%** in onset voltage, because
the dimension sits inside both Peek's `1/√r` term and `ln(d/r)`. Both readings already exist in
this project's source material — the prose used one and the reference code used the other. That
is not a hypothetical.

## 9. Do not oversell in prose

The suite's credibility is the deliverable. Specific bans:

- No "validated" for anything whose basis is `analytical-placeholder` or `claimed`.
- No "proven", "confirmed" or "demonstrated" for a simulated result.
- No omission of the caveat when quoting a headline figure in a summary. The summary is what
  gets read.
- State what was checked and what was not, **in the same sentence as the result**.

Thrust-per-watt and thrust-per-mass are **different claims**. Shrinking a gap at constant field
does not improve `F/P = 1/(µE)`; it improves thrust-to-mass, because structure falls as `L³`
while thrust falls as `L²`. Conflating them is how a scaling argument becomes an efficiency
claim it does not support.
