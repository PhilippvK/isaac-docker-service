#!/bin/bash
set -eo pipefail
cd "${JOB_DIR:?JOB_DIR must be set}"
JOB_DIR=$(pwd)
export JOB_DIR
mapfile -d '' files < <(find "$JOB_DIR/input" -maxdepth 1 -name '*.core_desc' \
    -exec grep -lZ -E '^[[:space:]]*Core[[:space:]]' {} +)
if [[ ${#files[@]} != 1 || ! -f input/index.yaml || ! -f input/hls.tar.gz ]]; then
    echo "etiss_perf requires one .core_desc, index.yaml and hls.tar.gz" >&2
    exit 1
fi
mkdir -p output hls
echo "::progress:: 0.06 0.08 Unpacking HLS reports"
python3 /scripts/unpack_hls.py input/hls.tar.gz "$JOB_DIR/hls"
export ETISS_PERF_HOME="$JOB_DIR/perf_sim_workspace"
export CCACHE=${CCACHE:-1}
exec /scripts/retarget_etiss_perf.sh "$JOB_DIR/output" "$JOB_DIR/input/index.yaml" "$JOB_DIR/hls" "${files[0]}"
