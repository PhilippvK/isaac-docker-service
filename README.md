# Retargeting Services

## Usage

```sh
docker compose --profile combined up --build -d --remove-orphans
# Or use dedicated LLVM and ETISS workers:
docker compose --profile separated up --build -d --remove-orphans
```

Use either profile. `separated` runs individual LLVM, ETISS, and Spike workers;
`combined` runs a shared `etiss`/`etiss_perf` worker pool (`worker-etiss-combined`)
and a separate LLVM pool (`worker-llvm`). `separated` also gives performance jobs
their own dedicated worker. The dedicated ISS worker uses
`philippvk/isaac-quickstart-etiss` and the performance worker uses
`philippvk/isaac-quickstart-etiss-perf`.

## Worker concurrency

Each worker container handles one job at a time. Scale the pools independently:

```sh
BUILD_JOBS=4 docker compose --profile combined up --build -d --remove-orphans \
  --scale worker-etiss-combined=3 --scale worker-llvm=1
```

This allows up to three simulator jobs (any mix of `etiss` and `etiss_perf`) plus
one LLVM job concurrently. `BUILD_JOBS` is passed to simulator retargeting CMake
build steps (default 4); it is not the number of jobs per worker. Upstream
workspace setup and LLVM tooling retain their own internal parallelism settings.

With separate simulator pools:

```sh
docker compose --profile separated up --build -d --remove-orphans \
  --scale worker-etiss=2 --scale worker-etiss-perf=1 --scale worker-llvm=1
```

Keep API and Redis at one instance with the current session-reset design.

## Example uploads

Paths below are relative to `test_files/`. The dashboard currently requires all
three base uploads, even though the simulator scripts do not use the LLVM config.

| Tag | CoreDSL upload | Split-description upload | Configuration | Extra uploads |
| --- | --- | --- | --- | --- |
| `llvm` | `etiss_instructions.core_desc` | the same `etiss_instructions.core_desc` | `config.yaml` | none |
| `etiss` | `etiss.core_desc` | `etiss_instructions.core_desc` | `config.yaml` | none |
| `spike` | top-level `XIsaacCore.core_desc` | imported instruction-set `.core_desc` | `config.yaml` | none |
| `etiss_perf` | `etiss.core_desc` | `etiss_instructions.core_desc` | `config.yaml` | matching ISAAC index + HLS archive |

For LLVM, uploading the same instruction-set file twice leaves one input file
and avoids feeding the ISS-only top-level Core description to SEAL5. Its load
and transform steps have been checked with this sample. `test.dsl` is empty;
use the table above for a small working example. The encoding-size filter is
in **bits** (`filter.encoding_sizes.keep: [32]` for these examples), not bytes or
RISC-V length-field values. LLVM preparation rejects an empty filtered model
before compiling. Each job restores pristine image settings and the stage-0
checkout while retaining build/dependency caches, so earlier successes, failures,
or installs do not carry model/settings state into the next job.

Generate synthetic performance inputs matching this one-instruction sample:

```sh
python3 tests/smoke_prepare.py /tmp/isaac-upload-example
tar -czf /tmp/isaac-upload-example/hls.tar.gz -C /tmp/isaac-upload-example/hls .
```

Upload `/tmp/isaac-upload-example/input/index.yaml` as the index and
`/tmp/isaac-upload-example/hls.tar.gz` as HLS results. These contain synthetic
latency/area data for testing; meaningful performance results require matching
index and HLS outputs from your actual design flow.

## Multiple hosts

The current Compose configuration is for a single Docker host. Running it
independently on another host would create a second queue and jobs volume.
For a small multi-host setup, keep one API/Redis coordinator, provide workers
with its Redis address over a private network, mount the same `/jobs` filesystem
on every host, and distribute prebuilt worker images. The filesystem must support
POSIX locks across hosts and that behavior must be tested; the local claim tests
do not establish cross-host filesystem behavior. Ccache can remain host-local.
Additional hosts need a worker-only deployment configuration; the current Compose
service names/dependencies assume the API and Redis are on the same Docker network.
An API restart still resets the shared session and cancels all current jobs by default.

This is a moderate deployment change if suitable shared storage already exists.
A robust distributed design needs more work: leases/recovery for lost workers,
central transactional job state rather than file locks, and worker-local build
workspaces with shared/object storage for inputs, logs and artifacts. Swarm can
schedule containers across hosts but does not by itself distribute local job volumes.
See [Compose scaling](https://docs.docker.com/reference/cli/docker/compose/up/) and
[Swarm storage](https://docs.docker.com/engine/swarm/services/#data-volumes).

## Dashboard and job control

Open `http://localhost:8080/dashboard` to submit LLVM, ETISS, Spike, or performance
simulator jobs. The plus icon opens the submission popup, which is hidden by
default. The form accepts the same files as the client. Actions use icons with
tooltips and accessible labels. Queued jobs offer only abort; running jobs also
offer log monitoring and downloads. The monitor opens in a separate popup and
stops polling when closed. Finished jobs also offer artifact downloads.
Artifact downloads are named `<job-id>_artifact.tar.zst`; logs use
`<job-id>_logs.txt`. Running jobs show the current stage beneath their progress
bar. Simulator stages include preparation, code generation, build and install;
both Make percentages and Ninja step counts update the bar. Overall percentages
are stage-weighted estimates and never move backward between build targets.
The final 5% is reserved for artifact packaging.

The trash icon beside Recently completed jobs clears the completed history,
including finished, failed, and aborted entries. It keeps their logs and artifacts
on disk and leaves queued/running jobs untouched. This uses
`POST /jobs/completed/clear`; existing token-protected download URLs still work.

`/dashboard/readonly` (or `/dashboard?readonly=true`) shows the same status with
all buttons and form controls disabled. This is a view-only interface, not an
API authorization boundary: there is no user management or authentication yet.

Abort from Python with `client.abort_job(job_id)`, or from the command line:

```sh
python3 client/cient.py --abort JOB_ID --token JOB_TOKEN
```

The API endpoint is `POST /jobs/{job_id}/abort?token=JOB_TOKEN`. Queued jobs are
removed immediately; running jobs enter `aborting` until the worker terminates
the build process group, then become `aborted`. Cancellation also covers silent
builds and artifact compression. A completed job is not changed by a late abort.

By default, **every API startup resets the session**: the queue is cleared, worker
registrations are removed, and old jobs disappear from the dashboard. Running
builds from the previous session are stopped. Their job files and artifacts remain
on disk, marked as archived, rather than being deleted. Live workers register
again as they become available. Workers wait for API readiness on Compose startup.
Use `RESET_ON_STARTUP=0` to retain the previous orphan-recovery behavior instead.
The shared jobs volume must support POSIX file locks; job claims and state
transitions are serialized there so multiple workers cannot execute the same job.

## Retargeting ETISS

Submit a multipart `POST /jobs` with `tag=etiss`, `cdsl`, `cpdsl`, and `config`.
The input directory must contain exactly one top-level `.core_desc` with one
`Core` declaration; other `.core_desc` files can supply imported instruction sets.
Core names may differ from filenames. Like the demo, the scripts use the RV32
`RV32IMACFD` architecture implementation as their template.

```sh
python3 client/cient.py etiss --cdsl test_files/etiss.core_desc \
  --cpdsl test_files/etiss_instructions.core_desc
```

The client rewrites `rv_base` imports to `/tools/etiss_arch_riscv/rv_base`.
It also rewrites ETISS architecture imports and references to the uploaded split
description so generated files can be submitted from another host directory.
The artifact includes `output/etiss_install`, `etiss_source.tar.gz`, and a full
architecture patch. Each job uses a fresh ETISS checkout in its own job directory.

## Retargeting the performance simulator

Use `tag=etiss_perf` and add `index` (ISAAC index YAML) and `hls` (gzip tar archive)
uploads. Both are required. Archive the **contents** of the HLS results directory:
`hls_schedules.csv`, `hls_selected_schedule_metrics.csv`, and
`output/<variant>/selected_solutions.yaml` and `ISAX_XIsaac.yaml`, as produced by
the demo's HLS flow.

```sh
tar -czf /tmp/hls.tar.gz -C /path/to/hls-results .
python3 client/cient.py etiss_perf --cdsl /path/to/XIsaacCore.core_desc \
  --cpdsl /path/to/XIsaac.core_desc --index /path/to/index.yml --hls /tmp/hls.tar.gz
```

The upstream performance templates currently target CV32E40P and require the
core name `XIsaacCore`, with RV32IM and CSR instructions. The worker generates
timing and monitor code, rebuilds ETISS, and packages `etiss_perf_install`,
`etiss_perf_source.tar.gz`, `ini/`,
`uarchs.csv`, `CV32E40PXISAAC.corePerfDsl`, and `InstructionTrace_XISAAC.json`.
Workspaces are isolated per job. Builds need network access for upstream sources
and Python packages; `BUILD_JOBS` controls retargeting CMake parallelism (Compose default: 4).

The scripts follow [isaac-demo's local ETISS workflows](https://github.com/PhilippvK/isaac-demo/tree/fb3acb1ddcb3af2903837cb45ddba19b289ed5a7/docker).

## Retargeting Spike

The `spike` worker parses the uploaded top-level CoreDSL and its imported
instruction-set description, compiles the custom extension against the matching
Spike headers in `isaac-quickstart-spike`, and returns `output/spike/` with
`libextension.so` and `spike_plugin.json`. The manifest uses a library path
relative to itself, so it remains valid after the Toolkit downloads and extracts
the artifact. Start the worker with the `separated` profile; configure the demo
service tag as `spike`.
The ISS images pin M2-ISA-R to that demo's submodule revision; performance builds
use the `xisaac_gen2` workspace and its generators, following the local performance
script rather than the image's older ISS-only entrypoint.
Both flows apply a compatibility fix for list-valued conditional branches in
the upstream ETISS code generator.

## Tests

Run the lightweight API tests with Docker Compose:

```sh
docker compose -f compose.test.yml run --build --rm tests
```

The test project uses its own Redis and temporary job directories. It exercises
competing worker processes, tag routing, exactly-once claims, cancellation races,
child-process termination, independent concurrent builds, and restart resets.
Chromium tests submit jobs through the form and exercise dashboard abort, live
logs, downloads, and disabled read-only controls. No deployment Redis, job volumes,
or compiler builds are used by this suite.

To run locally in a virtual environment (Python 3.11):

```sh
python3 -m venv .venv
.venv/bin/pip install -r tests/requirements.txt
# For integration tests, point TEST_REDIS_HOST at an isolated Redis.
# These tests clear database 15. Browser tests require Chromium at /usr/bin/chromium.
.venv/bin/python -m pytest -q tests
```

Opt-in smoke tests compile real simulators with one synthetic custom instruction
and HLS variant, check the installed architecture and generated outputs, and
package the artifact. They require network access and take several minutes:

```sh
bash tests/smoke.sh etiss
bash tests/smoke.sh etiss_perf
```

To check repeated LLVM preparation with the real SEAL5 tooling, without building
LLVM, run this inside the LLVM worker image (the container is disposable):

```sh
docker run --rm --entrypoint bash -v "$PWD:/src:ro" \
  isaac-docker-service-worker-llvm -c \
  'source /work/venv/bin/activate; python /src/tests/check_llvm_repeat.py /src/test_files'
```

This checks two successive preparations, rejects a 3-bit filter, and checks that
a subsequent valid job still retains `CUSTOM0` after that failure.
