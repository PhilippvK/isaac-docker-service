#!/bin/bash
set -euo pipefail
export PATH="/work/venv/bin:$PATH"
# The base image can contain editable installs and a different PYTHONPATH.
unset PYTHONPATH
M2ISAR_REF=a2a9a9c87bdd97eca3ed6997af3656960b38c215
SEAL5_REF=35066e4b0504a66c5c83623a76583cc515547aeb
git clone https://github.com/tum-ei-eda/M2-ISA-R.git /opt/m2isar
git -C /opt/m2isar checkout "$M2ISAR_REF"
git -C /opt/m2isar apply /opt/genie-seal5/m2isar-spike-behavior.patch
git clone https://github.com/tum-ei-eda/seal5.git /opt/genie-seal5/src
git -C /opt/genie-seal5/src checkout "$SEAL5_REF"
git -C /opt/genie-seal5/src apply /opt/genie-seal5/seal5-isaac-main.patch
python -m pip install -e /opt/m2isar -e /opt/genie-seal5/src
# Reject an incompatible image baseline during the image build.
PYTHONPATH=/opt/genie-seal5/src:/opt/m2isar python -c 'from pathlib import Path; from seal5.settings import Seal5Settings; Seal5Settings.from_yaml_file(Path("/opt/seal5-baseline.yml"))'
python /opt/genie-seal5/upgrade_baseline.py
python -m pip check
