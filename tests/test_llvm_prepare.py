import pickle
from types import SimpleNamespace

import pytest

from worker.llvm.prepare import validate_models


def test_empty_instruction_filter_fails_before_build(tmp_path):
    with (tmp_path / "example.seal5model").open("wb") as handle:
        pickle.dump(SimpleNamespace(sets={"XIsaac": SimpleNamespace(instructions={})}), handle)
    with pytest.raises(RuntimeError, match="use 32, not 3"):
        validate_models(tmp_path)


def test_missing_models_fail_before_build(tmp_path):
    with pytest.raises(RuntimeError, match="No SEAL5 models"):
        validate_models(tmp_path)


def test_valid_instruction_selection_is_accepted(tmp_path):
    with (tmp_path / "example.seal5model").open("wb") as handle:
        pickle.dump(SimpleNamespace(sets={"XIsaac": SimpleNamespace(instructions={"CUSTOM0": object()})}), handle)
    validate_models(tmp_path)


def test_llvm19_missing_marker_sites_are_registered_as_phase_one_patch(tmp_path):
    import subprocess
    from worker.llvm.prepare import configure_field_type_markers
    from seal5.settings import Seal5Settings
    home = tmp_path
    paths = {
        'llvm/lib/Target/RISCV/AsmParser/RISCVAsmParser.cpp': 'switch (x) {\n  case Match_InvalidSImm21Lsb0JAL:\n  break;\n}\n',
        'llvm/lib/Target/RISCV/RISCVInstrInfo.cpp': 'switch (x) {\n        CASE_OPERAND_UIMM(20)\n}\n',
    }
    for name, contents in paths.items():
        path = home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    subprocess.run(['git', 'init', str(home)], check=True, capture_output=True)
    settings = Seal5Settings.from_dict({'directory': str(home), 'patches': [],
                                      'llvm': {'state': {'version': {'major': 19}}}})
    configure_field_type_markers(home, settings)
    assert len(settings.patches) == 1
    patch = settings.patches[0]
    assert patch.stage == 1
    assert patch.priority == 1000
    # Registration must not modify the pristine checkout.
    assert all((home/name).read_text() == contents for name, contents in paths.items())
    subprocess.run(['git', '-C', str(home), 'apply', str(patch.file)], check=True)
    assert 'riscv_match_invalid_operands - INSERTION_START' in (home/next(iter(paths))).read_text()
    assert 'riscv_verify_operands - INSERTION_END' in (home/list(paths)[1]).read_text()
    configure_field_type_markers(home, settings)  # Already patched: no duplicate.
    assert len(settings.patches) == 1


def test_broken_marker_pair_fails_before_build(tmp_path):
    from worker.llvm.prepare import configure_field_type_markers
    path = tmp_path/'llvm/lib/Target/RISCV/AsmParser/RISCVAsmParser.cpp'
    path.parent.mkdir(parents=True)
    path.write_text('// RISCVAsmParser.cpp - riscv_match_invalid_operands - INSERTION_START\n')
    with pytest.raises(RuntimeError, match='Incomplete or duplicated'):
        configure_field_type_markers(tmp_path, None)
