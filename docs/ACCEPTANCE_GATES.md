# Scientific release gates

All unchecked gates mean **not yet demonstrated**. Each gate must cite test IDs, commands, dated logs, raw result paths and reviewer.

| Gate | Evidence to produce | Failure behavior |
|---|---|---|
| G0 environment | clean-clone installation and CI run | stop integration |
| G1 theory | explicit PSD convention, dimensional checks, analytic limit tests | block scientific claims |
| G2 controls | no overlaps, target-unitary corrections, numerical convergence | block optimizer |
| G3 MC physics | predetermined analytic comparison with CI and quadrature error | block accuracy claims |
| G4 fit | held-out decay prediction, parameter uncertainty, misspecification case | label fit exploratory |
| G5 fairness | same T, n, constraints, compensation and independent noise draws | block performance claims |
| G6 robustness | perturbation matrices, optimization ablations and failure reporting | label gains synthetic-specific |
| G7 QUA | compilation or hardware run ID, explicitly separated | never say hardware tested absent ID |
| G8 report | every numerical claim traced to data, program, seed and figure | remove ungrounded claim |
| G9 review | independent red-team pass, references confirmed, PDF visual QA | no release |

No gate is satisfied by a prose statement alone. Negative results pass integrity gates if documented.
