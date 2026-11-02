#!/bin/bash
# Adapted from isaac-demo/docker/etiss_script_local.sh.
set -euo pipefail
cd "${JOB_DIR:?JOB_DIR must be set}"
JOB_DIR=$(pwd)
mapfile -d '' files < <(find "$JOB_DIR/input" -maxdepth 1 -name '*.core_desc' \
    -exec grep -lZ -E '^[[:space:]]*Core[[:space:]]' {} +)
if [[ ${#files[@]} != 1 ]]; then
    echo "ETISS requires one top-level .core_desc containing a Core declaration" >&2
    exit 1
fi
top=${files[0]}
name=$(basename "$top" .core_desc)
dest="$JOB_DIR/output"
home="$JOB_DIR/etiss"
mkdir -p "$dest"
echo "::progress:: 0.06 0.12 Cloning ETISS"
# Each job gets its own checkout and generated model.
git clone --depth 1 --branch "${ETISS_REF:-print_instr_to_file}" \
    "${ETISS_URL:-https://github.com/PhilippvK/etiss.git}" "$home"
echo "::progress:: 0.12 0.18 Parsing CoreDSL"
python3 -m m2isar.frontends.coredsl2.parser "$top"
echo "::progress:: 0.18 0.24 Generating architecture"
python3 -m m2isar.backends.etiss.writer \
    "$JOB_DIR/input/gen_model/$name.m2isarmodel" --separate --static-scalars \
    --fill-mode "${ISAAC_M2ISAR_FILL_MODE:-auto}"
mapfile -d '' cores < <(find "$JOB_DIR/input/gen_output/$name" -mindepth 1 -maxdepth 1 -type d -print0)
if [[ ${#cores[@]} != 1 ]]; then
    echo "ETISS requires exactly one generated core" >&2
    exit 1
fi
name=$(basename "${cores[0]}")
cp -r "${cores[0]}" "$home/ArchImpl/"
# Keep the typed backend implementation, including installDir() and JIT paths.
echo "::progress:: 0.24 0.28 Preparing sources"
git -C "$home" add -N ArchImpl/
git -C "$home" diff > "$dest/etiss_patch_full.diff"
git -C "$home" diff --stat > "$dest/etiss_patch_full.stat"
tar --exclude=.git -czf "$dest/etiss_source.tar.gz" -C "$home" .
args=()
if [[ ${CCACHE:-1} == 1 ]]; then
    args+=(-DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache)
fi
echo "::progress:: 0.28 0.32 Configuring ETISS"
cmake -S "$home" -B "$home/build" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$dest/etiss_install" "${args[@]}"
echo "::progress:: 0.32 0.90 Building ETISS"
cmake --build "$home/build" -j "${BUILD_JOBS:-$(nproc)}"
echo "::progress:: 0.90 0.94 Installing ETISS"
cmake --install "$home/build"
echo "::progress:: 0.94 0.94 Retargeting complete"
