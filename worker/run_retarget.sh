#!/bin/bash
set -e

cd "$JOB_DIR"

mkdir -p output

echo "Running retargeting job"

# example placeholder
sleep 30

echo "Generating fake output"
echo "LLVM build artifacts" > output/result.txt

echo "Job finished"
