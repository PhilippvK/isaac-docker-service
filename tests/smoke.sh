#!/bin/bash
# Slow, opt-in builds against real upstream sources. No deployment services used.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
case "${1:-}" in
    etiss) service=worker-etiss ;;
    etiss_perf) service=worker-etiss-perf ;;
    *) echo "Usage: bash tests/smoke.sh {etiss|etiss_perf}" >&2; exit 1 ;;
esac
docker compose -p isaac-simulator-smoke --profile separated run --build --rm --no-deps \
    -v "$root/tests/smoke_prepare.py:/tmp/smoke_prepare.py:ro" \
    -e JOB_DIR=/tmp/smoke-job -e JOB_TAG="$1" -e BUILD_JOBS="${BUILD_JOBS:-4}" \
    --entrypoint bash "$service" -c '
        set -e
        python3 /tmp/smoke_prepare.py "$JOB_DIR"
        tar -czf "$JOB_DIR/input/hls.tar.gz" -C "$JOB_DIR/hls" .
        /scripts/run_retarget.sh
        if [[ $JOB_TAG == etiss ]]; then
            test -s "$JOB_DIR/output/etiss_source.tar.gz"
            find "$JOB_DIR/output/etiss_install" -name libXIsaacCore.so -size +0c -print -quit | grep -q .
        else
            test -s "$JOB_DIR/output/etiss_perf_source.tar.gz"
            test -s "$JOB_DIR/output/uarchs.csv"
            test -s "$JOB_DIR/output/InstructionTrace_XISAAC.json"
            test -s "$JOB_DIR/output/ini/cv32e40pxisaacv0.ini"
            find "$JOB_DIR/output/etiss_perf_install" -name libXIsaacCore.so -size +0c -print -quit | grep -q .
        fi
        tar --zstd -cf /tmp/artifact.tar.zst -C "$JOB_DIR" output
        tar --zstd -tf /tmp/artifact.tar.zst > /dev/null
        echo "Simulator smoke test passed: $JOB_TAG"
    '
