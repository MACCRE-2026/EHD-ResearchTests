---
inclusion: always
---

# High-voltage safety — non-discretionary

This project designs supplies delivering **4.8 kV to 22 kV at milliampere currents**. That
combination is lethal. Roughly 10 mA across the chest can prevent someone letting go; the
Cockcroft-Walton ladders here are specified for 1–16 mA.

This file is `inclusion: always` deliberately. A lethal-voltage rule must not be path-scoped,
discretionary, or something an agent decides is not relevant to the current file.

---

## The framing that is most likely to hurt someone

**"The palm-scale rail is only 5 kV, so it's the safe one."**

It is not. 5 kV at 2.5 mA is lethal. The MK1 design point is *lower voltage than MK0*, which
makes it feel safer while remaining entirely capable of killing. Relative safety language —
"low voltage", "just the small one", "only the test cell" — is banned in anything this project
generates. State absolute figures.

Worse, the palm-scale design is the one intended to be handled: it is small, cheap, built on a
cardboard tube and a breadboard, and meant to be shown to people. Familiarity is the hazard.

## Every generated bench procedure and firmware must carry these

A procedure or sketch missing any of the following is **incomplete**, not merely terse. This
is not a style preference; a document that omits the discharge step will be followed by
someone who trusts it.

1. **Bleeder resistors, sized and stated.** Every high-voltage capacitor and the whole CW
   ladder has a permanent bleeder path across it, with the computed discharge time constant
   written down. The MK0 design specifies 60 MΩ; the MK1 palm-scale specifies 40 MΩ, giving
   sub-0.1 s discharge on 1 nF stages. A bleeder is not optional and is not a component to be
   value-engineered out.
2. **An explicit discharge step before contact, every time.** Power down, wait the stated
   number of time constants, then **short the output to ground with an insulated grounding
   stick** and leave it shorted while hands are near the cell. Waiting is not verification.
3. **Verify dead, do not assume dead.** A meter reading before contact. A bleeder can fail
   open, and a failed-open bleeder is silent.
4. **An interlock.** HV enable is gated — a physical switch, a dead-man control, or a firmware
   enable that fails to *off* on reset, watchdog timeout, loss of serial link, or undefined
   state. Firmware must never leave HV asserted through a fault path.
5. **Single-hand rule, stated in the procedure.** One hand near the apparatus. Keep the other
   in a pocket. Current across the chest is what stops a heart.
6. **No floating high-voltage returns.** A defined ground reference, and current sense that
   does not lift the return above ground under fault.
7. **Never work alone at voltage**, and never with the supply energised and unattended.

## Ozone and nitrogen oxides

Positive corona in ambient air generates **ozone and nitric acid vapour**. These are why
25 µm emitter wire embrittles and snaps in bench tests, and they are also a respiratory
hazard in an enclosed room. Any procedure specifying more than brief bursts specifies
ventilation. This is a real exposure, not a footnote — the same chemistry that eats the wire
is being inhaled.

## What this file does not cover

Electrical safety practice, not electrical safety qualification. Nothing generated here
substitutes for the operator's own judgement about their bench, and no document this project
produces should imply a procedure has been reviewed by a qualified electrical engineer unless
one has actually reviewed it. Claiming otherwise would be
*principle 3, never report success over unperformed work*, applied to something that can kill.
