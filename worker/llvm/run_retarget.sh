#!/bin/bash
set -euo pipefail
cd "${JOB_DIR:?JOB_DIR must be set}"
JOB_DIR=$(pwd)
export JOB_DIR
source /work/venv/bin/activate
export SEAL5_HOME=${SEAL5_HOME:-/work/llvm}
dest="$JOB_DIR/output"
mkdir -p "$dest"
echo "::progress:: 0.06 0.15 Preparing LLVM job"
python3 /scripts/prepare_llvm.py "$JOB_DIR/input"
verbosity=()
if [[ ${VERBOSE:-1} == 1 ]]; then verbosity+=(--verbose); fi
args=()
if [[ ${CCACHE:-1} == 1 ]]; then args+=(--ccache); fi
seal5 "${verbosity[@]}" generate --skip pattern_gen
seal5 "${verbosity[@]}" patch -s 1 2
echo "::progress:: 0.15 0.50 Building LLVM prerequisites"
seal5 "${verbosity[@]}" build "${args[@]}"
seal5 "${verbosity[@]}" build -t pattern-gen "${args[@]}"
seal5 "${verbosity[@]}" build -t llc "${args[@]}"
echo "::progress:: 0.50 0.60 Generating instruction patterns"
seal5 "${verbosity[@]}" generate --only pattern_gen
seal5 "${verbosity[@]}" patch -s 3 4 5
echo "::progress:: 0.60 0.85 Building retargeted LLVM"
seal5 "${verbosity[@]}" build "${args[@]}"
echo "::progress:: 0.85 0.88 Testing retargeted LLVM"
seal5 "${verbosity[@]}" test
echo "::progress:: 0.88 0.92 Installing LLVM artifacts"
seal5 "${verbosity[@]}" install --dest "$dest/llvm_install"
seal5 "${verbosity[@]}" deploy --dest "$dest/llvm_source.zip"
seal5 "${verbosity[@]}" export --dest "$dest/seal5.tar.gz"
echo "::progress:: 0.92 0.94 Collecting LLVM reports"
mkdir -p "$dest/seal5_reports"
python3 -m seal5.backends.report.properties.writer "$SEAL5_HOME"/.seal5/models/*.seal5model --output "$dest/seal5_reports/properties.csv"
for kind in status test_results; do
    extra=()
    if [[ $kind == test_results ]]; then extra+=(--coverage "$dest/seal5_reports/test_coverage.csv"); fi
    python3 -m "seal5.backends.report.$kind.writer" "$SEAL5_HOME"/.seal5/models/*.seal5model --yaml "$SEAL5_HOME/.seal5/settings.yml" --output "$dest/seal5_reports/$kind.csv" "${extra[@]}"
    if [[ $kind == test_results ]]; then extra=(--coverage "$dest/seal5_reports/test_coverage_compact.csv"); fi
    python3 -m "seal5.backends.report.$kind.writer" "$SEAL5_HOME"/.seal5/models/*.seal5model --yaml "$SEAL5_HOME/.seal5/settings.yml" --compact --output "$dest/seal5_reports/${kind}_compact.csv" "${extra[@]}"
done
python3 -m seal5.backends.report.diff.writer --yaml "$SEAL5_HOME/.seal5/settings.yml" --output "$dest/seal5_reports/diff.csv"
python3 -m seal5.backends.report.times.writer --yaml "$SEAL5_HOME/.seal5/settings.yml" --pass-times --output "$dest/seal5_reports/stage_times.csv" --sum-level 2
echo "::progress:: 0.94 0.94 Retargeting complete"
# The next job restores the pristine baseline before loading anything. Keep the
# checkout/build/dependency caches here, including after failures or cancellation.
