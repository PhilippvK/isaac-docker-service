#!/bin/bash
set -euo pipefail
case "${JOB_TAG:?JOB_TAG must be set}" in
    llvm) exec /scripts/retarget_llvm.sh ;;
    etiss) source /work/venv/bin/activate; exec /scripts/retarget_etiss.sh ;;
    *) echo "Unsupported job tag: $JOB_TAG" >&2; exit 1 ;;
esac
