"""Real SEAL5 regression; run inside the LLVM worker image without compiling LLVM.

python /src/tests/check_llvm_repeat.py /src/test_files
"""
import os
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


def main(samples):
    samples = Path(samples)
    with tempfile.TemporaryDirectory() as temp:
        inputs = Path(temp)
        (inputs / "etiss_instructions.core_desc").write_bytes((samples / "etiss_instructions.core_desc").read_bytes())
        good = yaml.safe_load((samples / "config.yaml").read_text())
        (inputs / "config.yaml").write_text(yaml.safe_dump(good))
        cmd = [sys.executable, "/scripts/prepare_llvm.py", str(inputs)]
        settings_path = Path(os.environ["SEAL5_HOME"]) / ".seal5/settings.yml"
        for cycle in range(2):
            subprocess.run(cmd, check=True)
            settings = yaml.safe_load(settings_path.read_text())
            assert settings["filter"]["encoding_sizes"]["keep"] == [32]
            assert settings["models"]["etiss_instructions"]["extensions"]["XIsaac"]["instructions"] == ["CUSTOM0"]
            print(f"Repeat {cycle + 1}: CUSTOM0 retained", flush=True)
            subprocess.run(["seal5", "reset", "--settings"], check=True)
            # Simulate stale options left after an earlier install/build.
            dirty = yaml.safe_load(settings_path.read_text())
            dirty["llvm"]["configs"]["release"]["options"]["CMAKE_INSTALL_PREFIX"] = "/previous-job/output"
            dirty["models"] = {"stale": {"extensions": {}}}
            settings_path.write_text(yaml.safe_dump(dirty))
        bad = yaml.safe_load(yaml.safe_dump(good))
        bad["filter"]["encoding_sizes"]["keep"] = [3]
        (inputs / "config.yaml").write_text(yaml.safe_dump(bad))
        result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert result.returncode != 0
        assert "No instructions remain" in result.stdout
        assert "use 32, not 3" in result.stdout
        (inputs / "config.yaml").write_text(yaml.safe_dump(good))
        subprocess.run(cmd, check=True)
        print("Repeated LLVM preparation and recovery after bad config passed", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
