# Release review: IEEE midterm paper and supplement

An AI release-verification agent prepared this review on 2026-10-27 against origin/main
`0bc48e45c351fc1a03543ad9ace41f45f545e56f`. It records checks and findings only. It does not edit
`report/`, approve evidence or authorize release. Items 3 to 5 need people.

## Release checklist

| # | Item | Status | Owner |
|---|---|---|---|
| 1 | CI green and combined PDF builds (main <= 6 pages, appendix appended) | **PASS** (details below) | AI-checked |
| 2 | Visual PDF review | **DONE, issues open**: 0 blockers, 15 should-fix, 9 nits (list below) | AI-checked; owner to fix in `report/` |
| 3 | PR reconciliation | handled by lead | lead |
| 4 | Team contributions and AI-use disclosure confirmed by all four authors | **OPEN (human)**. The paper says that individual contributions are unassigned pending author confirmation. | authors |
| 5 | Evidence ledger approval | **OPEN (human)**. AI pre-check in [EVIDENCE_REVIEW.md](EVIDENCE_REVIEW.md): 22 claims, 20 match, 2 text overstatements. All 235 ledger rows are still `PENDING`/`UNVERIFIED`. | named human reviewer |

## 1. CI and PDF build

### GitHub Actions (head SHA 0bc48e45c351fc1a03543ad9ace41f45f545e56f)

| Workflow | Run id | Event | Job | Job id | Conclusion |
|---|---|---|---|---|---|
| ci #92 | 40515527942 | push | test (3.11) | 122228383911 | success |
| ci #92 | 40515527942 | push | test (3.13) | 122228383155 | success. Log: `257 passed, 1 skipped in 14.61s` (skip: QUA SDK not installed); `evidence_map.csv up to date (235 claims)` |
| ci #92 | 40515527942 | push | report | 122228747321 | success. Log: `built report/combined_report.pdf (11 pages; main 5, appendix 6)` |
| pages #9 | 40515528151 | push | build | 122228870922 | success |
| pages #9 | 40515528151 | push | deploy | 122229839103 | **failure**. `Failed to create deployment (status: 404) ... Ensure GitHub Pages has been enabled` |
| pages #10 | 40516974172 | workflow_dispatch | build | 122233192189 | success (`paper.pdf` present in the uploaded site artifact) |
| pages #10 | 40516974172 | workflow_dispatch | deploy | 122233837659 | success |

Notes:
- The test (3.11) job passed, but the log excerpt retrieved did not include the pytest summary
  line, so the agent did not see its count.
- The pages failure in run 40515528151 happened before Pages was enabled. The manual re-run
  40516974172 on the same SHA deployed successfully.
- In `pages.yml`, "Build paper PDF" uses `continue-on-error`. A green step there therefore does not
  prove that the PDF built. The presence of `paper.pdf` in the artifact listing does.
- Runs on earlier SHAs, kept for history: pages #7 (40515404032) and #6 (40515332044) were
  cancelled. ci #91 (40515437709) and #90 (40515404042) succeeded.

### Local tests (worktree = origin/main, `PYTHONPATH=$PWD/src`, full suite with no marker filter)

| Python | Command | Result |
|---|---|---|
| 3.13.17 | `python -m pytest -q -p no:cacheprovider` | 257 passed, 1 skipped, exit 0 (75 s) |
| 3.11.17 | same | 257 passed, 1 skipped, exit 0 (75 s) |

On both versions the skipped test is `tests/test_qua_syntax.py:269` (QM QUA SDK `qm-qua` not
installed). The paper's 249/0/0/1 figure is the pinned historical run
`test_suite_20261027T000401Z_2fc21cc36501`, which records a dirty tree. The current suite has
more tests.

### Local report build

The agent exported the HEAD tree with `git archive` into its scratch directory, so the tracked
`report/appendix.pdf` was not overwritten, and ran
`PYTHON=<3.13 venv> PYTHONPATH=<copy>/src bash scripts/build_report.sh`. The build exited 0.

| Check | Result |
|---|---|
| Evidence map check | `ok ... evidence_map.csv up to date (235 claims)` |
| `main.pdf` pages (pdfinfo) | **5** (target 5, hard maximum 6), US Letter |
| `appendix.pdf` pages | 6 |
| `combined_report.pdf` pages | 11 = 5 + 6 |
| Appendix really present in combined PDF | yes. `pdftotext -f 6 -l 11 combined_report.pdf` is byte-identical to `pdftotext appendix.pdf`. Page 6 opens with "Supplementary Material". All 11 pages were rendered and inspected. |
| Undefined references / citations | none (main.log, appendix.log) |
| Overfull hboxes | main: 0. appendix: 1 (4.8 pt, run id in the Table VI caption, from `generated/model_based_table.tex` line 7) |
| Underfull boxes | main 26, appendix 25 (loose lines; see the visual issues) |
| Font warnings | `OT1/ptm/m/scit undefined` (texttt or italic inside small-caps captions) |
| BibTeX | `main.blg` and `appendix.blg`: `warning$ -- 0`, no errors |
| `\cite` keys | 13 distinct keys cited, all 13 present in `refs.bib`, none unused. `main.bbl` has 13 items; `appendix.bbl` has 1 (Hansen2016). |
| Fonts | All embedded, but **26 Type 3 fonts** (DejaVu, from matplotlib figures) |

## 2. Visual PDF review (combined_report.pdf, 110 dpi, every page viewed)

Page numbers refer to the combined PDF: pages 1-5 are the main paper and pages 6-11 the appendix.
Nothing below was edited. All fixes are suggestions for the owner.

### Blockers

None found in the PDF itself. Release is still blocked by checklist items 4 and 5, which are
human sign-offs.

### Should-fix

| # | Page / location | Problem | Suggested fix |
|---|---|---|---|
| S1 | p3, main Fig. 2 (`figures/fig_benchmark.pdf`) | Axis and legend text is about 4-5 pt at print size and the markers are tiny. The key comparison (XY4/XY8 vs CMA-ES at the floor) collapses into overlapping markers on the dashed line, so the figure does not show the result it is cited for. | Regenerate with fonts of at least 7 pt at final width and larger markers. Either zoom the y-axis near the floor or plot the ratio eps_sel/eps_CMA with CI bars. Consider `figure*` at full width. |
| S2 | p3 Fig. 2 caption (main) and p9 Fig. 2 caption (appendix) | The main caption says timing-only methods are "outside the visible plotting range". The appendix caption says timing-only is "off-scale for n>=8". Neither is true: the timing-only values (A: 21.0, 49.8, 141.4; B: 18.6, 41.4, 109.6, all x1e-3) lie inside the plotted y-range (CPMG at 141.3e-3 is shown). | Plot timing-only, or write "timing-only CMA-ES omitted for clarity; see Table III". |
| S3 | p3, Sec. V-B, `sections/results.tex:35` | "Some sub-percent differences occur". The largest Scenario A ratio is 1.0112, a 1.1% gain (EVIDENCE_REVIEW row 9). | Change to "differences of at most about 1%". |
| S4 | p4, Sec. V-D, `sections/results.tex:61` | "CMA-ES still fails to beat XY8 in held-out evaluation". The ablations contain marginal wins over XY8: colored n=8 phase-only 1.002-1.004, and no-T1 n=8 up to 1.004 (EVIDENCE_REVIEW row 17). | "did not beat XY8 by more than 0.4% in any ablation configuration and lost substantially at n=16 (ratio 0.394-0.566)". |
| S5 | p4, Sec. VI-b, 5th bullet (`sections/discussion.tex:35`); same on p10 | "several exploratory runs were marked dirty". 5 of the 11 pinned runs are dirty, including the pre-registered spectroscopy run (headline RMSE 1.15x and coverage 0.934), the pre-registered T=4 us benchmark and the test-suite record. | Name the dirty pinned runs, or say "several runs, including the pre-registered spectroscopy and T=4 us runs". |
| S6 | p1-p4 and p6-p10, every run-in paragraph heading | Headings render with double punctuation, e.g. "Motivation.:" and "Limitations.:". IEEEtran adds the colon itself. | Remove the trailing period inside all 25 `\paragraph{...}` arguments (introduction, related_work, model, methods, discussion, results_full). |
| S7 | p1, author block | Three authors sit on row 1. The fourth (Udaya Vijay Anand) sits alone on row 2, left-aligned under the first column, which looks unbalanced. | Use a centered 2+2 layout. A common IEEEtran approach is `\newcommand{\linebreakand}{\end{@IEEEauthorhalign}\hfill\mbox{}\par\mbox{}\hfill\begin{@IEEEauthorhalign}}` (inside `\makeatletter`), with `\linebreakand` after the second author. Alternatively, shorten affiliations so all four fit on one row. |
| S8 | All figures (main and appendix) | 26 Type 3 fonts (matplotlib DejaVu). IEEE PDF eXpress and many venues reject Type 3 fonts. | Set `matplotlib.rcParams["pdf.fonttype"] = 42` (and `ps.fonttype = 42`), preferably with a Times-like serif to match the text, then regenerate the figures. |
| S9 | p6-p11, appendix numbering | The supplement restarts at Fig. 1 / Table I / eq. (1) / ref [1]. In the combined PDF, "Fig. 1", "Fig. 2" and "[1]" mean different things on p3 and p8-p10 (main [1] = QM brief; appendix [1] = Hansen). | Prefix the supplement: `\renewcommand{\thefigure}{S\arabic{figure}}`, `\renewcommand{\thetable}{S\Roman{table}}`, `\renewcommand{\theequation}{S\arabic{equation}}`. Either make the appendix bibliography numbering match the main paper (e.g. the same cite order or `\nocite` list) or state in "Scope" that it has its own reference list. |
| S10 | p8, appendix Fig. 1 and `results_full.tex:42` | The caption refers to panels "(a)" and "(b)" and the text says "Fig. 1a", but the panels have no (a)/(b) labels. | Add panel labels in `fig_spectroscopy`. |
| S11 | p9 bottom right to p10 | The heading "b) Limitations.:" is stranded at the bottom of the column. Its bullets begin on p10 below Fig. 3 and Table IV. | Use `\needspace{4\baselineskip}` before the paragraph, or adjust float placement (e.g. `[!t]` for Table IV, or move it). |
| S12 | p10, appendix Fig. 4 (`fig_robustness_b`) | Legend and axis text are about 3-4 pt and the legend is unreadable in print. | Regenerate at larger font size or use `figure*`. |
| S13 | p7-p11, table captions (Tables I-VI) | Run ids in `\texttt` inside IEEE small-caps captions render as small caps, e.g. "G3_VALIDATION_..._CBFE38B59354". Lower-case hex becomes visually upper-case and is easy to mis-transcribe. This is also the source of the `OT1/ptm/m/scit` font warning. In Table VI the id overflows by 4.8 pt. | Wrap ids in `\textnormal{\texttt{...}}` inside captions, or move run ids to a table footnote. Allow breaks (e.g. `\path{}`) to fix the overfull box. |
| S14 | p3 left column (Sec. IV-f) and p4/p10 limitation bullets | Very loose justified lines (large inter-word gaps) caused by long unbreakable `\texttt` paths ("The historical full-suite record ...", "The original citation audit ..."). | Use `\path`/`\url` (breakable), shorten the paths, or wrap those paragraphs in `{\sloppy ...}` or `\RaggedRight`. |
| S15 | p5, references | Several URLs break as "https:" / "//arxiv.org/...", e.g. [2] and [9]. | Load `\usepackage[hyphens]{url}` or `xurl` before hyperref, or drop the scheme from displayed URLs. |

### Nits

| # | Page / location | Problem | Suggested fix |
|---|---|---|---|
| N1 | p1, left column | "Midterm Report, October 27, 2026" floats as a centered line in the left column above the abstract rather than under the title block. | Put it in the title block, e.g. as a third title line, or in a `\thanks`. |
| N2 | p1, Sec. I-a | Internal ledger id "(claim LIT-13)" appears in the prose. | Drop it. The ledger maps claims to text. |
| N3 | p5 | The main paper's last page holds only the end of the references in the left column. The right column is empty. | Acceptable at 5 pages. No action needed unless content is added. |
| N4 | p5, ref [12] | Author list is "Tong et al." only. | Complete the authors per `docs/CITATION_AUDIT.md`, or keep it and note the reason. |
| N5 | p6, appendix title | Title wraps with single words ("Decoupling", "Evidence") on their own lines. | Shorten it, e.g. "Supplementary Material: Detailed Synthetic Results", or add manual `\\`. |
| N6 | p6-p10, appendix | Sections A, B and D repeat the main paper's model, methods and discussion text verbatim, adding 2-3 pages. | Intentional for a self-contained supplement. Optionally replace with "see main paper Sec. III" and keep only the added detail. |
| N7 | p11 | Tables V-VII are floated to the final page with large white gaps. | Acceptable. Optionally use `\clearpage` placement or `[!htbp]`. |
| N8 | Abstract | About 197 words, at the top of the 150-200 range in REPORT_REQUIREMENTS. "CMA-ES beat XY4 by a few percent ... only at n=4" is true only at the few-percent level (n=8 shows 0.2-0.4% wins). | Optionally "by up to 5% at n=4 (below 0.5% at n=8, 16)". |
| N9 | p9, p11 (Tables III, VII) | "—" used as the empty-cell marker. | Fine as is (see the em-dash list). |

### Em-dash inventory

Searched `report/main.tex`, `report/appendix.tex`, `report/sections/*.tex`,
`report/generated/*.tex` and `report/refs.bib` for `---` and `—`, plus the pdftotext output of
`combined_report.pdf` for `—`.

| Location | Text | Assessment |
|---|---|---|
| `report/generated/bench_table.tex:15,17,19,21` (appendix Table III, p9) | `---` in the XY8/UDD columns | Empty-cell or not-applicable marker in a table. Conventional, not unnecessary. Could be "n/a". Generated file. |
| `report/generated/feasibility_table.tex:11,12,14,15,16` (appendix Table VII, p11) | `---` in the "Infeasible" column | Means "none". Conventional. Could be "none". Generated file. |
| PDF p1 "Abstract—" and "Index Terms—" | inserted by IEEEtran | Class-generated, required by IEEE style. Not in the source. |

There are no em dashes in running prose in any `.tex` source or in the PDF text.

## 3. PR reconciliation

Handled by the lead. Not reviewed here.

## 4. Team contributions and AI disclosure (human)

The "Author Contributions and Disclosure" section (p4) lists the four authors and says that
individual contributions are not assigned because the authors have not confirmed them. It also
discloses AI coding assistance. All four authors must confirm the author list, the affiliations
and emails in the author block, and the AI-use statement. The agent did not and cannot do this.

## 5. Evidence ledger approval (human)

See [EVIDENCE_REVIEW.md](EVIDENCE_REVIEW.md). Summary of the AI pre-check, which is not an
approval:

- All 11 pinned runs pass `python -m ddopt.provenance verify`.
- 22 main-paper claims were recomputed independently from checksum-verified artifacts. 20 match.
- Rows 9 and 17 are wording overstatements whose numbers are correct. They correspond to S3 and S4
  above.
- 5 of the 11 pinned runs record a dirty tree. This is S5.
- `report/evidence_map.csv`: 235 rows, reviewer `PENDING` on all, status `UNVERIFIED` (222) or
  `PENDING` (13). Some hard-coded numbers in the main text have no ledger row (106 held-out
  points, 14 times / 1000 shots, budgets, seeds, device parameters).

A named human reviewer must approve rows and update the ledger.


## Follow-up editing pass (2026-10-27)

The original findings above are preserved as an audit of an earlier PDF build, not a live checklist.
The current report source now includes: a two-by-two author grid, readable seven-to-eight-point
plot fonts with TrueType (PDF Type 42) embedding, a ratio benchmark figure, explicit
spectroscopy panel labels, qualified sub-percent/ablation wording, exact dirty-run caveats,
fixed paragraph punctuation, supplementary S-numbered references/figures/tables,
line-breakable provenance paths, and improved URL handling. The authors have supplied a
statement of equal contributions, which the manuscript now uses. The main paper and
supplement now both include the public project URL.

The AI-use paragraph has been removed from the paper at the owner's request; any
institutional/course AI-disclosure requirements remain the submitting authors'
responsibility. The original use of AI is still described in repository history and project
documents. The latest CI PDF and visual render should be reviewed before considering this
follow-up list complete. Evidence-ledger human sign-off is still separate from an AI check.
