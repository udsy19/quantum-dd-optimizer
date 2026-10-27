# Security policy

## Reporting a vulnerability

Please report security issues privately via GitHub's
[private vulnerability reporting](https://github.com/udsy19/quantum-dd-optimizer/security/advisories/new)
rather than a public issue. Expect an acknowledgement within a few days.

## Scope and rules

- This repository must never contain API tokens, QM/IQCC credentials, private hardware
  configurations, identifying device data or undisclosed team material. If you find any, report it
  privately so it can be removed and rotated.
- The `qua/` adapter never opens network connections or executes jobs; any change that would make
  it do so requires explicit owner authorization.
- Result payloads are JSON written by this project; treat third-party result files as untrusted data.
