# About

**Quantum DD Optimizer** studies whether model-based optimization of dynamical-decoupling (DD)
sequences can protect an idle superconducting qubit — for example one waiting while a neighbour is
measured mid-circuit — better than strong canonical sequences, when the comparison is made fair
(equal pulse budget, timing constraints and correction privileges; pre-registered baselines;
independent held-out noise).

The project originated from a Columbia University × Quantum Machines course project-ideas brief.
That brief describes other work and is not evidence of this project's implementation or of hardware
access. All results in this repository are synthetic simulations; prospective hardware work is
gated behind explicit authorization (`docs/HARDWARE_PROTOCOL.md`).

## Suggested GitHub "About" metadata

Set in the repository's *About* panel (gear icon on the GitHub repository page):

- **Description:** Pre-registered synthetic benchmark of CMA-ES-optimized dynamical decoupling vs XY4/XY8 for idle superconducting qubits — with provenance and an honest negative result.
- **Website:** https://udsy19.github.io/quantum-dd-optimizer/
- **Topics:** `quantum-computing` `dynamical-decoupling` `superconducting-qubits` `quantum-control` `filter-function` `noise-spectroscopy` `cma-es` `reproducible-research` `python`

## Status

Software, recorded synthetic runs, paper draft and website: complete for v0.1.0.
Open: human review of the evidence ledger, citation metadata verification, team authorship,
CI observed on GitHub, and any hardware work (not authorized).
