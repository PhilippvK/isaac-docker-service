import pickle
from types import SimpleNamespace

import pytest

from worker.llvm.prepare import validate_models


def test_empty_instruction_filter_fails_before_build(tmp_path):
    with (tmp_path / "example.seal5model").open("wb") as handle:
        pickle.dump({"sets": {"XIsaac": SimpleNamespace(instructions={})}}, handle)
    with pytest.raises(RuntimeError, match="use 32, not 3"):
        validate_models(tmp_path)


def test_missing_models_fail_before_build(tmp_path):
    with pytest.raises(RuntimeError, match="No SEAL5 models"):
        validate_models(tmp_path)


def test_valid_instruction_selection_is_accepted(tmp_path):
    with (tmp_path / "example.seal5model").open("wb") as handle:
        pickle.dump({"sets": {"XIsaac": SimpleNamespace(instructions={"CUSTOM0": object()})}}, handle)
    validate_models(tmp_path)
