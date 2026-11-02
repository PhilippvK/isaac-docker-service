#!/bin/bash
set -euo pipefail
export PATH="/work/venv/bin:$PATH"
# The base image can contain editable installs and a different PYTHONPATH.
unset PYTHONPATH
M2ISAR_REF=59ba470011fafe5e814a2b9ca9504d8175fe25cc
SEAL5_REF=168b81be68c752a96238c8f504b88346bc38a55c
git clone https://github.com/tum-ei-eda/M2-ISA-R.git /opt/m2isar
git -C /opt/m2isar checkout "$M2ISAR_REF"
git clone https://github.com/tum-ei-eda/seal5.git /opt/genie-seal5/src
git -C /opt/genie-seal5/src checkout "$SEAL5_REF"
python -m pip install -e /opt/m2isar -e /opt/genie-seal5/src
# Reject an incompatible image baseline during the image build.
PYTHONPATH=/opt/genie-seal5/src:/opt/m2isar python -c 'from pathlib import Path; from seal5.settings import Seal5Settings; Seal5Settings.from_yaml_file(Path("/opt/seal5-baseline.yml"))'
python /opt/genie-seal5/configure_baseline.py
python -m pip check
