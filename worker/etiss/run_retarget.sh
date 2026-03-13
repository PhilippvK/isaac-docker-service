#!/bin/bash
set -e

cd "$JOB_DIR"

mkdir -p output

echo "Running retargeting job"

# CLEANUP=${CLEANUP:-1}
CLEANUP=0  # keep llvm clone and .seal5 dir
CCACHE=${CCACHE:-1}
RESET=${RESET:-1}
VERBOSE=${VERBOSE:-1}
DEST=$JOB_DIR/output

echo "JOB_DIR=$JOB_DIR"
ls
ls input
FILES=$(find input/ -name "*.core_desc" -or -name "*.yml" -or -name "*.yaml")
# example placeholder
CLEANUP=$CLEANUP CCACHE=$CCACHE RESET=$RESET VERBOSE=$VERBOSE /work/seal5_script.sh $DEST $FILES
# sleep 30

echo "Generating fake output"
echo "LLVM build artifacts" > output/result.txt

echo "Job finished"
