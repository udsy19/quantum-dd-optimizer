# Claude Code project instructions — mandatory

Read `docs/CLAUDE_CODE_MASTER_PROMPT.md`, `docs/ACCEPTANCE_GATES.md`, and `docs/REPORT_REQUIREMENTS.md` before writing code. This is a scientific research repository, not a demo that can be made credible with plausible-looking output.

1. **Never invent** datasets, accuracy, CI results, experiment logs, hardware access, author contribution, citation detail, publication, or customer validation. If unavailable: mark UNVERIFIED / NOT RUN / PENDING.
2. Distinguish source-supported historical facts, new computations and projections; every figure and number needs provenance.
3. Do not rewrite `report/` with numerical results unless the numbers trace to output artifacts and independently executed tests.
4. Maintain explicit mathematical conventions: Hamiltonian, units, one- vs two-sided PSD, Fourier normalization, switching function, Gaussian assumption, T1 treatment, target unitary and frame correction.
5. Use independent held-out noise, configurations and seeds. Control for optimization overfitting and model misspecification.
6. No hardware execution, credential acquisition, submission, or publication without explicit authorization from the human project owner.
7. Agents own disjoint files, communicate via tracked contracts, preserve tests, request review before breaking public APIs.
8. Make the smallest defensible claims. Return honest negative results.
9. On each integration, run tests, record outputs, and update `docs/PROGRESS.md`.
10. Treat all previous LaTeX claims of seven passing tests, 1% reconstruction and 1.7–1.8× improvement as **unverified** unless regenerated from actual scripts.

Execute the master prompt in phases. Stop and report blockers rather than improvising fake code, data or hardware success.
