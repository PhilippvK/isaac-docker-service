#!/bin/bash
set -euo pipefail
case "${JOB_TAG:-etiss_perf}" in
    etiss) exec /scripts/retarget_etiss.sh ;;
    etiss_perf) exec /scripts/run_etiss_perf.sh ;;
    *) echo "Unsupported simulator job tag: $JOB_TAG" >&2; exit 1 ;;
esac
