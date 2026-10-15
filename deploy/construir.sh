#!/usr/bin/env bash
# Arma deploy/public: página de inicio, presentación y la interfaz del POC compilada para /poc/.
set -euo pipefail
cd "$(dirname "$0")"

rm -rf public
mkdir -p public
cp landing/index.html public/
rsync -a --exclude '.DS_Store' ../presentacion/ public/presentacion/
npm --prefix ../mvp/web run build -- --base=/poc/ --outDir ../../deploy/public/poc --emptyOutDir
