# Citation audit

Access date for every lookup below: **2026-10-26**. Scope: the 13 entries of
`docs/REFERENCES.md` / `report/refs.bib` (claims LIT-01..LIT-13 in `report/claims.json`).

## Outcome

**No entry could be verified against a primary source.** Every primary source was
unreachable from the audit environment:

| Source | Tool | Result |
|---|---|---|
| `https://export.arxiv.org/api/query?id_list=...` | curl via agent proxy | CONNECT refused, HTTP 403 (policy denial) |
| `https://arxiv.org/abs/<id>` | curl / WebFetch | 403 / `getaddrinfo ENOTFOUND arxiv.org` |
| `https://export.arxiv.org/abs/<id>` | WebFetch | `ENOTFOUND` |
| `https://api.crossref.org/works?...` | curl / WebFetch | 403 / `ENOTFOUND` |
| `https://doi.org/<doi>` | curl / WebFetch | 403 / `ENOTFOUND` |
| `https://journals.aps.org/` | curl | 403 |
| `https://www.semanticscholar.org/arxiv/<id>` | WebFetch | `ENOTFOUND` |

The only reachable service was a web-search index (WebSearch). Its output is a summary
generated over search results (arXiv PDF listings, ar5iv, NSF PAR, RePEc, institutional
pages), not the primary page itself. It is recorded below as **SECONDARY** corroboration
only. Nothing has been marked VERIFIED, and no value obtained from search has been written
into `report/refs.bib` (no DOI, first name, co-author or title change). Characterising
sentences in `report/sections/related_work.tex` were **not** written from abstracts,
because no abstract could be read from arXiv; they are restricted to what each title states.

Status legend:
- **UNVERIFIED**: not checked against a primary source (applies to every field below).
- **SECONDARY-OK**: a search result agreed with the current value.
- **SECONDARY-DIFFERS**: a search result reported a different value. Candidate correction,
  not applied.
- **SECONDARY-NONE**: search did not report the field.
- **N/A**: not a public document.

To finish the audit, someone with arxiv.org and doi.org access should check the
SECONDARY-DIFFERS and SECONDARY-NONE fields first, and then every other field.

## Per-entry table

Primary URL (not reachable) is the arXiv abstract page in `refs.bib`. Secondary URLs are the
search-result URLs that the search summary cited.

### LIT-01 Viola1999
| Field | Current value | Status | Notes / secondary source |
|---|---|---|---|
| authors | Viola; Knill; Lloyd | UNVERIFIED; SECONDARY-OK | search: Lorenza Viola, Emanuel Knill, Seth Lloyd (https://arxiv.org/abs/quant-ph/9809071 listing via search) |
| title | Dynamical decoupling of open quantum systems | UNVERIFIED; SECONDARY-OK | capitalisation differs between versions only |
| journal/vol/page | PRL 82, 2417 | UNVERIFIED; SECONDARY-NONE | search did not report the journal reference |
| year | 1999 | UNVERIFIED; SECONDARY-NONE | arXiv v1 1998-09-24, v2 1999-02-11 (search) |
| arXiv | quant-ph/9809071 | UNVERIFIED; SECONDARY-OK | |
| DOI | (none) | UNVERIFIED | not added |

### LIT-02 Uhrig2007
| Field | Current value | Status | Notes / secondary source |
|---|---|---|---|
| authors | Uhrig | UNVERIFIED; SECONDARY-OK | search: Götz S. Uhrig (https://www.alphaxiv.org/abs/quant-ph/0609203) |
| title | Keeping a quantum bit alive by optimized π-pulse sequences | UNVERIFIED; SECONDARY-OK | search: v1 had a different title ("Keeping a Physical Quantum Bit Alive") |
| journal/vol/page | PRL 98, 100504 | UNVERIFIED; SECONDARY-NONE | |
| year | 2007 | UNVERIFIED; SECONDARY-NONE | arXiv v2 2007-02-08 (search) |
| arXiv | quant-ph/0609203 | UNVERIFIED; SECONDARY-OK | |
| DOI | (none) | UNVERIFIED | not added |

### LIT-03 Cywinski2008
| Field | Current value | Status | Notes / secondary source |
|---|---|---|---|
| authors | Cywiński and others | UNVERIFIED; SECONDARY-OK | candidate full list (search, https://arxiv.org/pdf/0712.2225): Łukasz Cywiński, Roman M. Lutchyn, Cody P. Nave, S. Das Sarma |
| title | How to enhance dephasing time in superconducting qubits | UNVERIFIED; SECONDARY-OK | |
| journal/vol/page | PRB 77, 174509 | UNVERIFIED; SECONDARY-NONE | |
| year | 2008 | UNVERIFIED; SECONDARY-NONE | |
| arXiv | 0712.2225 | UNVERIFIED; SECONDARY-OK | |
| DOI | (none) | UNVERIFIED | not added |

### LIT-04 Biercuk2009
| Field | Current value | Status | Notes / secondary source |
|---|---|---|---|
| authors | Biercuk and others | UNVERIFIED; SECONDARY-OK | candidate list (search, surnames only): Biercuk, Uys, VanDevender, Shiga, Itano, Bollinger |
| title | Optimized dynamical decoupling in a model quantum memory | UNVERIFIED; SECONDARY-OK | |
| journal/vol/page | Nature 458, 996 | UNVERIFIED; SECONDARY-OK | RePEc: Nature 458(7241) 996–1000 (https://ideas.repec.org/a/nat/nature/v458y2009i7241d10.1038_nature07951.html); a NIST BibTeX export reportedly says "Science", which looks like an error in that export |
| year | 2009 | UNVERIFIED; SECONDARY-OK | |
| arXiv | 0812.5095 | UNVERIFIED; SECONDARY-OK | |
| DOI | (none) | UNVERIFIED | candidate 10.1038/nature07951 (RePEc), not added |

### LIT-05 Bylander2011
| Field | Current value | Status | Notes / secondary source |
|---|---|---|---|
| authors | Bylander and others | UNVERIFIED; SECONDARY-OK | candidate list (search, https://research.chalmers.se/publication/239583): Jonas Bylander, Simon Gustavsson, Fei Yan, Fumiki Yoshihara, Khalil Harrabi, George Fitch, David G. Cory, Yasunobu Nakamura, Jaw-Shen Tsai, William D. Oliver |
| title | Noise spectroscopy through dynamical decoupling with a superconducting flux qubit | UNVERIFIED; SECONDARY-OK for journal | **arXiv title differs**: "Dynamical decoupling and noise spectroscopy with a superconducting flux qubit" |
| journal/vol/page | Nature Physics 7, 565 | UNVERIFIED; SECONDARY-OK | search: pages 565–570 |
| year | 2011 | UNVERIFIED; SECONDARY-OK | |
| arXiv | 1101.4707 | UNVERIFIED; SECONDARY-OK | |
| DOI | (none) | UNVERIFIED | candidate 10.1038/nphys1994 (Chalmers record), not added |

### LIT-06 Alvarez2011
| Field | Current value | Status | Notes / secondary source |
|---|---|---|---|
| authors | Álvarez; Suter | UNVERIFIED; SECONDARY-OK | search: Gonzalo A. Álvarez, Dieter Suter (https://www.famaf.unc.edu.ar/~galvarez/2011-Alvarez_Suter-PRL-DDnoisespect.pdf) |
| title | Measuring the spectrum of colored noise by dynamical decoupling | UNVERIFIED; SECONDARY-NONE for journal title | **arXiv title differs**: "Dynamical decoupling noise spectroscopy" |
| journal/vol/page | PRL 107, 230501 | UNVERIFIED; SECONDARY-OK | |
| year | 2011 | UNVERIFIED; SECONDARY-OK | published 2011-11-30 (author PDF via search) |
| arXiv | 1106.3463 | UNVERIFIED; SECONDARY-OK | |
| DOI | (none) | UNVERIFIED | candidate 10.1103/PhysRevLett.107.230501, not added |

### LIT-07 Souza2011
| Field | Current value | Status | Notes / secondary source |
|---|---|---|---|
| authors | Souza; Álvarez; Suter | UNVERIFIED; SECONDARY-OK | https://www.arxiv.org/abs/1103.4563 via search |
| title | Robust dynamical decoupling for quantum computing and quantum memory | UNVERIFIED; SECONDARY-OK | do not confuse with the longer review arXiv:1110.6334 that has a similar title |
| journal/vol/page | PRL 106, 240501 | UNVERIFIED; SECONDARY-OK | |
| year | 2011 | UNVERIFIED; SECONDARY-OK | |
| arXiv | 1103.4563 | UNVERIFIED; SECONDARY-OK | |
| DOI | (none) | UNVERIFIED | candidate 10.1103/PhysRevLett.106.240501, not added |

### LIT-08 Ezzell2023
| Field | Current value | Status | Notes / secondary source |
|---|---|---|---|
| authors | Ezzell and others | UNVERIFIED; SECONDARY-OK | candidate list (search, https://par.nsf.gov/biblio/10574574): Nic Ezzell, Bibek Pokharel, Lina Tewala, Gregory Quiroz, Daniel A. Lidar |
| title | Dynamical decoupling for superconducting qubits: a performance survey | UNVERIFIED; SECONDARY-OK | |
| journal/vol/page | Physical Review Applied 20, 064027 | UNVERIFIED; SECONDARY-OK | https://qserver.usc.edu/?p=3827 |
| year | 2023 | UNVERIFIED; SECONDARY-OK | |
| arXiv | 2207.03670 | UNVERIFIED; SECONDARY-OK | |
| DOI | (none) | UNVERIFIED | candidate 10.1103/PhysRevApplied.20.064027, not added |

### LIT-09 Rahman2024
| Field | Current value | Status | Notes / secondary source |
|---|---|---|---|
| authors | Rahman; Egger; Arenz | UNVERIFIED; SECONDARY-OK | search: Arefur Rahman, Daniel J. Egger, Christian Arenz |
| title | Learning how to dynamically decouple | UNVERIFIED; **SECONDARY-DIFFERS** | matches the arXiv title; NSF PAR (https://par.nsf.gov/biblio/10629690) reportedly gives the journal title "Learning how to dynamically decouple by optimizing rotational gates" |
| journal/vol/page | Physical Review Applied 22, 054074 | UNVERIFIED; SECONDARY-OK | vol. 22 issue 5 (NSF PAR); 054074 from a citing paper |
| year | 2024 | UNVERIFIED; SECONDARY-OK | |
| arXiv | 2405.08689 | UNVERIFIED; SECONDARY-OK | |
| DOI | (none) | UNVERIFIED | candidate 10.1103/PhysRevApplied.22.054074, not added |

### LIT-10 Tong2025
| Field | Current value | Status | Notes / secondary source |
|---|---|---|---|
| authors | Tong; Zhang; Pokharel | UNVERIFIED; SECONDARY-OK | search: Christopher Tong, Helena Zhang, Bibek Pokharel |
| title | Empirical learning of dynamical decoupling on quantum processors | UNVERIFIED; SECONDARY-OK | |
| journal/vol/page | PRX Quantum 6, 030319 | UNVERIFIED; **SECONDARY-NONE** | no search result corroborated the journal reference; check it first |
| year | 2025 | UNVERIFIED; SECONDARY-NONE | |
| arXiv | 2403.02294 | UNVERIFIED; SECONDARY-OK | |
| DOI | (none) | UNVERIFIED | not added |

### LIT-11 Tong2026
| Field | Current value | Status | Notes / secondary source |
|---|---|---|---|
| existence | arXiv:2604.18734 | UNVERIFIED; SECONDARY-OK (FOUND in search index) | https://arxiv.org/pdf/2604.18734, https://www.emergentmind.com/papers/2604.18734 |
| authors | Tong and others | UNVERIFIED; SECONDARY-OK | candidate list (search): Christopher Tong, Liran Shirizly, Edward H. Chen, Derek S. Wang, Bibek Pokharel |
| title | Learning error suppression strategies for dynamic quantum circuits | UNVERIFIED; SECONDARY-OK | |
| venue | arXiv preprint | UNVERIFIED | no journal version known |
| year | 2026 | UNVERIFIED; SECONDARY-OK | v1 reportedly posted 2026-04-20 |
| arXiv | 2604.18734 | UNVERIFIED; SECONDARY-OK | |

### LIT-12 Hansen2016
| Field | Current value | Status | Notes / secondary source |
|---|---|---|---|
| authors | Hansen | UNVERIFIED; SECONDARY-OK | search: Nikolaus Hansen (https://arxiv.org/abs/1604.00772v2) |
| title | The CMA Evolution Strategy: A Tutorial | UNVERIFIED; SECONDARY-OK | |
| venue | arXiv preprint | UNVERIFIED | |
| year | 2016 | UNVERIFIED; SECONDARY-OK | v1 2016-04-04; v2 2023-03-10 (search). Consider citing the version used |
| arXiv | 1604.00772 | UNVERIFIED; SECONDARY-OK | |

### LIT-13 QMBrief2026
| Field | Current value | Status | Notes |
|---|---|---|---|
| all | Quantum Machines/Columbia course project-ideas brief (2026) | N/A | Internal, non-public document supplied by the team. Cannot be verified publicly; cite only as project motivation, never as evidence of implementation or hardware access |

## Changes made in this audit

- `report/refs.bib`: journal abbreviations PRL/PRB expanded to full names; per-entry
  `note` recording UNVERIFIED status; header updated. No metadata values changed.
- `report/sections/related_work.tex`: each sentence tagged with its LIT id in a comment;
  the two `\pending` paragraphs replaced. The empirical/model-based classification is given
  only where the title states it (Tong2025), and the rest remain PENDING; positioning paragraph
  added with the main finding left PENDING for the lead author.
- `docs/REFERENCES.md`: pointer to this audit and status line added.

## Candidate corrections for a human to confirm (not applied)

1. Rahman2024: the published title may include "by optimizing rotational gates".
2. Bylander2011 and Alvarez2011: arXiv titles differ from the journal titles in `refs.bib`.
   The journal titles are what should be cited, if the journal metadata is confirmed.
3. Tong2025: confirm PRX Quantum 6, 030319 (2025). No source reached corroborates it.
4. Full author lists and DOIs as listed above.


## Independent follow-up source checks (2026-10-26, separate web environment)

The initial execution environment could not reach primary sources. A subsequent independent
web research pass confirmed these specific records (this is a **partial** audit, not
an all-13-record verification):

- Tong, Zhang, Pokharel, *Empirical learning of dynamical decoupling on quantum processors*:
  https://arxiv.org/abs/2403.02294 — arXiv entry confirms title, full names and the
  genetic-algorithm hardware-empirical method. Publisher entry:
  https://journals.aps.org/prxquantum/abstract/10.1103/h7pq-s159 confirms published title.
- Rahman, Egger, Arenz, *Learning How to Dynamically Decouple*:
  https://arxiv.org/abs/2405.08689 — arXiv entry confirms title and the three authors;
  the abstract reports optimizing DD rotational gates for superconducting-qubit noise.
- Ezzell et al., *Dynamical decoupling for superconducting qubits: a performance survey*:
  https://arxiv.org/abs/2207.03670 — arXiv entry confirms author list, title and
  60-sequence survey across IBM superconducting devices.
- Tong et al., *Learning error suppression strategies for dynamic quantum circuits*:
  https://arxiv.org/abs/2604.18734 — arXiv entry confirms 2026 publication,
  five authors and empirical DD learning for dynamic circuits.
- Hansen, *The CMA Evolution Strategy: A Tutorial*:
  https://arxiv.org/abs/1604.00772 — arXiv confirms author, title, year and the
  continuous-optimization scope.

These checks corroborate the named records but **do not verify the remaining eight
reference entries, every bibliographic field, every paper claim, or published-version
metadata**. The initial audit above remains preserved as an accurate account of
its restricted network environment. Human review and final citation audit are outstanding.


## Follow-up completion: all 12 publicly accessible arXiv reference identities checked

A second independent research pass opened the canonical arXiv entries and checked
title, authors, year and abstracts for each of the 12 public literature entries.
This supersedes the earlier **network blocked** status for identity-level verification;
that earlier account is retained above as audit history. Journal title variants are
preserved where the report cites a journal version rather than the arXiv title.

| Key | Primary source opened | Verified scope |
|---|---|---|
| Viola1999 | https://arxiv.org/abs/quant-ph/9809071 | title, Viola/Knill/Lloyd, journal reference PRL 82, 2417 |
| Uhrig2007 | https://arxiv.org/abs/quant-ph/0609203 | title, Uhrig, 2007 journal-era entry |
| Cywinski2008 | https://arxiv.org/abs/0712.2225 | title, 4 authors, 2008 revision |
| Biercuk2009 | https://arxiv.org/abs/0812.5095 | title, 6 authors, experiments described in abstract |
| Bylander2011 | https://arxiv.org/abs/1101.4707 | original arXiv title **differs** from published journal title; Nature Physics 7 565--570 |
| Alvarez2011 | https://arxiv.org/abs/1106.3463 | original arXiv title **differs** from published journal title; PRL 107 230501 |
| Souza2011 | https://arxiv.org/abs/1103.4563 | title, 3 authors, robustness context |
| Ezzell2023 | https://arxiv.org/abs/2207.03670 | five authors, survey of 60 DD sequences |
| Rahman2024 | https://arxiv.org/abs/2405.08689 | three authors, gate-level tailored DD |
| Tong2025 | https://arxiv.org/abs/2403.02294 | three authors, empirical DD on quantum processors; publisher https://journals.aps.org/prxquantum/abstract/10.1103/h7pq-s159 |
| Tong2026 | https://arxiv.org/abs/2604.18734 | five authors, 2026 dynamic-circuit empirical study |
| Hansen2016 | https://arxiv.org/abs/1604.00772 | author, CMA-ES tutorial and scope |

**Audit precision:** Verified that each publicly cited work exists and describes the
relevant field, based on primary arXiv record and abstracts. This is not an audit of every
mathematical statement or every publisher pagination/DOI. QMBrief2026 is a supplied
non-public educational document, not a public arXiv reference.

**Important corrections:** Bylander and Alvarez titles on arXiv differ from the
corresponding journal titles. Do not replace a journal-version title with its
arXiv preprint title unless explicitly citing that version. Citation claims can be
classified identity-verified, but the experimental findings in this repository
still require independent code and data reproduction.


## Bibliography normalization pass (2026-10-28, report-finalization branch)

This pass edited `report/refs.bib` for IEEE presentation. Primary hosts (`api.crossref.org`,
`doi.org`, `arxiv.org`, `journals.aps.org`, `nature.com`, `overleaf.com`) were again unreachable
from the agent sandbox (DNS blocked), so **no field below was newly confirmed against a primary
source in this pass**. Every change and its source:

| Key | Change | Source of the value | Status |
|---|---|---|---|
| Viola1999, Uhrig2007, Cywinski2008, Bylander2011, Alvarez2011, Ezzell2023, Tong2025, Tong2026, Hansen2016 | Surname-only / "and others" author fields replaced by full author lists with given names and diacritics (IEEE requires initials) | Author lists recorded above (initial audit candidate lists and the follow-up arXiv identity checks) | identity-level, from recorded arXiv checks |
| Biercuk2009 | Full author list (M. J. Biercuk, H. Uys, A. P. VanDevender, N. Shiga, W. M. Itano, J. J. Bollinger); pages 996--1000 | Surnames and pages: RePEc record cited above. **Given names of VanDevender, Shiga, Itano and Bollinger were added from the agent's background knowledge, not from an opened source** | UNCONFIRMED: check against the Nature record |
| Souza2011 | Given names added (Alexandre M. Souza, Gonzalo A. Álvarez, Dieter Suter) | Álvarez/Suter from the audit above; **"Alexandre M." from the agent's background knowledge** | UNCONFIRMED: check against the PRL record |
| Bylander2011 | pages 565--570 | follow-up section above (Nature Physics 7 565--570) | as recorded |
| Tong2025 | **Removed article number 030319** (never corroborated by any source); added DOI 10.1103/h7pq-s159, printed via `note` because IEEEtranN does not print `doi` | DOI: publisher URL recorded in the follow-up section | volume/article number UNCONFIRMED; DOI as recorded |
| Tong2026, Hansen2016 | `howpublished = arXiv preprint arXiv:<id>` | arXiv identifiers already recorded | as recorded |
| BiercukDohertyUys2011 | added `eprint` 1012.4262 (already in its URL) | existing entry | volume/issue/article/DOI UNCONFIRMED (no lead found) |
| Ezzell2023, GreenUysBiercuk2012, Hansen2016 | Titles normalized to sentence case (`{CMA}` protected) | presentation only | n/a |
| Rahman2024, BiercukDohertyUys2011, GreenUysBiercuk2012 | unchanged DOIs kept in `doi` (not printed) | earlier entries; search leads only | UNCONFIRMED |

Not added: DOIs for Viola1999, Uhrig2007, Cywinski2008, Biercuk2009, Bylander2011, Alvarez2011,
Souza2011 and Ezzell2023 (candidate DOIs are listed above but were never opened). Cywinski2008's
journal reference (PRB 77, 174509) still has no corroborating record.

**Before submission, a human with Crossref access should confirm:** the UNCONFIRMED rows above
(especially Tong2025 volume/article number, the Biercuk2009 and Souza2011 given names, and the
BiercukDohertyUys2011 J. Phys. B locator), e.g. `https://api.crossref.org/works/<DOI>`.
