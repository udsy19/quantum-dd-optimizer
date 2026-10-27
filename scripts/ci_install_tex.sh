#!/usr/bin/env bash
# Install the TeX Live packages that scripts/build_report.sh needs (CI only).
# Downloaded .deb files go to .apt-archives/ in the workspace, which the workflows
# cache with actions/cache, so a slow Ubuntu mirror is only hit on a cache miss.
set -euo pipefail
ARCHIVES="${GITHUB_WORKSPACE:-$PWD}/.apt-archives"
mkdir -p "$ARCHIVES/partial"
sudo rm -f /var/lib/man-db/auto-update   # skip the slow man-db trigger
APT=(sudo apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o "Dir::Cache::Archives=$ARCHIVES")
"${APT[@]}" update
"${APT[@]}" install -y --no-install-recommends \
  latexmk texlive-latex-base texlive-latex-recommended texlive-latex-extra \
  texlive-publishers texlive-fonts-recommended lmodern poppler-utils
sudo rm -rf "$ARCHIVES/partial" "$ARCHIVES/lock"
sudo chown -R "$(id -u):$(id -g)" "$ARCHIVES"
