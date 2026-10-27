# Cross-platform IonQ experiments and response to technical review

Status: **new protocol, no IonQ jobs submitted, no IonQ results claimed**.

## Hardware distinction

The existing work models a **superconducting transmon** with finite-width microwave
pulses, an assumed 4 ns controller grid, relaxation and a synthetic dispersive
readout-like Stark shift. IonQ provides **trapped-ion** gate-model systems, using
laser-driven control and different errors. IonQ's general circuit submission does
not expose the same analog pulse schedules, precise 2 us idle windows, transmon T1,
or neighboring superconducting resonator-readout mechanism.

Therefore an IonQ result cannot be presented as verification of IQCC hardware
behavior, the previous transmon noise model, or Scenario B. A gate-level IonQ
control study can be reported only as **cross-platform exploratory work** with
clearly separated hypotheses and data.

Official reference: https://quantumai.google/cirq/hardware/ionq/service and
https://www.ionq.com/resources/best-practices-for-using-ionq-hardware

## Authentication and authorization

1. Revoke/rotate the key previously shared in chat. Never paste keys into issues,
   PRs, prompts or committed files.
2. Install `cirq` and `cirq-ionq` in a local private environment.
3. Set `IONQ_API_KEY` in the local environment or credential manager.
4. First run `run_ionq("xy4", submit=False)` and inspect the dry-run circuit.
5. Remote execution is an opt-in `submit=True` call; it can incur costs and
   must be authorized in advance. Default target is the vendor simulator;
   request a QPU explicitly and establish expected usage/credits.

## Proposed exploratory benchmark

- Start with free, XY4, XY8 single-qubit memory circuits with X-basis return,
  identical shot count, repeated randomized/interleaved order and independent
  sessions if possible.
- These gates are net-identity up to a global phase, but they have no enforced
  idle dwell and therefore measure mostly gate insertion/control error, not
  calibrated dynamical decoupling of ambient low-frequency noise.
- Record circuit text, provider backend, job IDs, timestamps, target, shots,
  observations, status and estimated cost. Protect credentials.
- Only once backend capabilities are confirmed consider delay-time studies.
- Do not reuse existing numerical conclusions without a separately preregistered
  protocol and explicit readout/error-model qualification.

## Independent report audit findings

The attached technical review largely confirms the equations, but raises
methodological concerns:
- Original baseline near the $T_1$ + white-noise floor, with little headroom.
  **Report amended** to foreground this limitation and the exploratory colored
  noise ablation, rather than generalizing the negative optimizer conclusion.
- Timing-only optimization fixed to CPMG-Y phases, which confounds timing with
  coherent amplitude-error accumulation. **Open**: design new XY8-based timing
  optimization and matching baseline.
- The frozen 256-trajectory Monte Carlo training objective may overfit relative
  to the available 1% effect. **Open**: deterministic filter-function objective,
  objective-noise sensitivity and larger independent seeds.
- Scenario B missing a readout-aware XY4 heuristic. **Open**: add a robust
  heuristic with fixed safety margin, benchmark against virtual Z, and record
  all prespecified timing perturbations.
- Five recorded runs had dirty git trees. **Open**: clean reproducibility reruns
  without overwriting original archived results.
- Spectroscopy fits use an analytic model as the synthetic data generator.
  **Open**: hold out a finite-pulse truth simulation, state fit criteria and
  coverage over independent generators.
- Main and supplementary table/caption inconsistencies require visual
  validation after regeneration. Do not claim completion without rendered PDFs.

All added experiments must have new configs and seed assignments. Original
pre-registered findings and associated artifacts are immutable historical results.
