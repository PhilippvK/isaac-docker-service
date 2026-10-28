#!/bin/bash
# Adapted from isaac-demo fb3acb1/docker/etiss_perf_script_local.sh.
set -eo pipefail
unset PYTHONPATH
if [[ $# != 4 ]]; then
    echo "Usage: $0 DEST INDEX HLS_DIR CORE_DESC" >&2
    exit 1
fi
dest=$1
index=$2
hls=$3
top=$4
top_dir=$(dirname "$top")
name=$(basename "$top" .core_desc)
home=${ETISS_PERF_HOME:?ETISS_PERF_HOME must be job-local}
# The Docker entrypoint only builds an ISS; the local script contains the full
# performance workflow. Use its workspace/ETISS refs and HTTPS submodules.
echo "::progress:: 0.08 0.12 Preparing performance workspace"
if [[ ! -d $home/.git ]]; then
    git -c url.https://github.com/.insteadOf=git@github.com: clone --recursive \
        --branch "${ETISS_PERF_WS_REF:-xisaac_gen2}" \
        https://github.com/tum-ei-eda/PerformanceSimulation_workspace.git "$home"
fi
export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0=url.https://github.com/.insteadOf
export GIT_CONFIG_VALUE_0=git@github.com:
cd "$home"
git -C etiss-perf-sim checkout "${ETISS_PERF_REF:-xisaac_gen}"
git -C etiss-perf-sim/etiss checkout "${ETISS_REF:-xisaac_gen}"
git submodule update --init --recursive
python3 /scripts/fix_m2isar.py "$home/code_gen/generators/M2-ISA-R"
echo "::progress:: 0.12 0.32 Building workspace dependencies"
./scripts/setup_workspace.sh
source .env
export PSW_DEFAULT_CORE_DSL="$top"
wrapper="$PSW_SCRIPTS_SUPPORT/m2isar_run_wrapper.sh"
echo "::progress:: 0.32 0.35 Parsing CoreDSL"
"$wrapper" python3 -m m2isar.frontends.coredsl2.parser "$top"
echo "::progress:: 0.35 0.38 Generating architecture"
"$wrapper" python3 -m m2isar.backends.etiss.writer \
    "$top_dir/gen_model/$name.m2isarmodel" --separate --static-scalars
etiss="$home/etiss-perf-sim/etiss"
mapfile -d '' cores < <(find "$top_dir/gen_output/$name" -mindepth 1 -maxdepth 1 -type d -print0)
if [[ ${#cores[@]} != 1 ]]; then
    echo "etiss_perf requires exactly one generated core" >&2
    exit 1
fi
name=$(basename "${cores[0]}")
if [[ $name != XIsaacCore ]]; then
    echo "The upstream CV32E40P performance templates require Core XIsaacCore" >&2
    exit 1
fi
cp -r "${cores[0]}" "$etiss/ArchImpl/"
for ext in cpp h; do
    sed "s/RV32IMACFD/$name/g" "$etiss/ArchImpl/RV32IMACFD/RV32IMACFDArchSpecificImp.$ext" \
        > "$etiss/ArchImpl/$name/${name}ArchSpecificImp.$ext"
done
args=()
if [[ ${CCACHE:-1} == 1 ]]; then
    args+=(-DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache)
fi
echo "::progress:: 0.38 0.40 Configuring simulator"
cmake -S "$etiss" -B "$etiss/build_dir" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$etiss/build_dir/installed" "${args[@]}"
echo "::progress:: 0.40 0.65 Building retargeted simulator"
cmake --build "$etiss/build_dir" -j "${BUILD_JOBS:-$(nproc)}"
echo "::progress:: 0.65 0.67 Installing retargeted simulator"
cmake --install "$etiss/build_dir"
echo "::progress:: 0.67 0.72 Generating timing model"
cd "$home/code_gen/descriptions/core_perf_dsl"
"$wrapper" pip install -r requirements.txt
mkdir -p ini_out
extra=()
if [[ -n ${VARIANTS_FILTER:-} ]]; then
    extra+=(--variants "$VARIANTS_FILTER")
fi
"$wrapper" python3 gen_xisaac_core_perf_dsl_new.py \
    -t CV32E40PXISAAC.corePerfDsl.mako -c cv32e40p \
    -o CV32E40PXISAAC.corePerfDsl --temp-dir temp_out/ \
    --index-yaml "$index" --hls-dir "$hls" --ini-dest ini_out/ \
    --monitor-template InstructionTrace_XISAAC.json.mako \
    --monitor-dest InstructionTrace_XISAAC.json --uarchs-dest uarchs.csv "${extra[@]}"
mkdir -p "$dest/ini"
cp -r ini_out/. "$dest/ini/"
cp uarchs.csv InstructionTrace_XISAAC.json CV32E40PXISAAC.corePerfDsl "$dest/"
cd "$home"
echo "::progress:: 0.72 0.76 Generating performance plugins"
"$PSW_SCRIPTS_SUPPORT/code_gen_helper.py" code_gen/descriptions/core_perf_dsl/CV32E40PXISAAC.corePerfDsl
"$PSW_SCRIPTS_SUPPORT/code_gen_helper.py" code_gen/descriptions/core_perf_dsl/InstructionTrace_XISAAC.json
echo "::progress:: 0.76 0.90 Building performance plugins"
cmake --build "$etiss/build_dir" -j "${BUILD_JOBS:-$(nproc)}"
echo "::progress:: 0.90 0.92 Installing performance plugins"
cmake --install "$etiss/build_dir"
echo "::progress:: 0.92 0.94 Collecting simulator artifacts"
tar --dereference --exclude=.git --exclude=.gitmodules --exclude=build_dir \
    -czf "$dest/etiss_perf_source.tar.gz" -C "$etiss" .
mkdir -p "$dest/etiss_perf_install"
cp -r "$etiss/build_dir/installed/." "$dest/etiss_perf_install/"

echo "::progress:: 0.94 0.94 Retargeting complete"
