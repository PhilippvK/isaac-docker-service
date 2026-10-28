"""Prepare a small ISAAC/HLS fixture for manual simulator build smoke tests.

Run inside a worker image: python tests/smoke_prepare.py /tmp/job
"""
import json
import sys
from pathlib import Path


def prepare(root):
    root = Path(root)
    inputs = root / "input"
    inputs.mkdir(parents=True, exist_ok=True)
    (root / "output").mkdir(exist_ok=True)
    (inputs / "XIsaacCore.core_desc").write_text('''
import "/tools/etiss_arch_riscv/rv_base/RVI.core_desc"
import "/tools/etiss_arch_riscv/rv_base/RVM.core_desc"
import "/tools/etiss_arch_riscv/tum_mod.core_desc"
InstructionSet XIsaac extends RV32I {
    instructions {
        CUSTOM0 {
            encoding: 7'b0000000 :: rs2[4:0] :: rs1[4:0] :: 3'b000 :: rd[4:0] :: 7'b0001011;
            assembly: {"custom0", "{name(rd)}, {name(rs1)}, {name(rs2)}"};
            behavior: { X[rd] = X[rs1] + X[rs2]; }
        }
    }
}
Core XIsaacCore provides RV32I, RV32M, tum_csr, tum_ret, tum_semihosting, XIsaac {}
''')
    # JSON is valid YAML; avoid adding a YAML dependency to this fixture writer.
    (inputs / "index.yaml").write_text(json.dumps({
        "global": {"properties": {"xlen": 32}},
        "candidates": [{"properties": {
            "InstrName": "CUSTOM0", "OperandNames": ["rd", "rs1", "rs2"],
            "OperandTypes": ["REG", "REG", "REG"], "OperandDirs": ["OUT", "IN", "IN"],
        }}],
    }))
    hls = root / "hls"
    variant = hls / "output/V0"
    variant.mkdir(parents=True, exist_ok=True)
    (hls / "hls_schedules.csv").write_text(
        "config,Fallback,Instruction latencies,II\nSG_0_SOL_IDX_0,False,{'CUSTOM0': 1},1\n"
    )
    (hls / "hls_selected_schedule_metrics.csv").write_text(
        "Variant idx,Variant name,Variant details,Variant description,total_area_estimate\n"
        "0,V0,smoke,smoke,1\n"
    )
    (variant / "selected_solutions.yaml").write_text(json.dumps([
        {"sharing_group": 0, "solution_idx": 0},
    ]))
    (variant / "ISAX_XIsaac.yaml").write_text(json.dumps([
        {"instruction": "CUSTOM0", "schedule": [{"stage": 0}]},
    ]))


if __name__ == "__main__":
    prepare(sys.argv[1])
