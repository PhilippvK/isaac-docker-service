#!/usr/bin/env python3
"""Configure LLVM lit tests in an image-owned baseline; leave sources and tags intact."""
import argparse
import subprocess
from pathlib import Path


def git(home, *args, **kwargs):
    return subprocess.run(["git", "-C", str(home), *args], check=True, **kwargs)


def configure_regression_tests(home, settings):
    """Retain lit configuration sources and enable the worker's LLVM tests."""
    sparse = git(home, "rev-parse", "--git-path", "info/sparse-checkout",
                 capture_output=True, text=True).stdout.strip()
    sparse = Path(sparse)
    if not sparse.is_absolute():
        sparse = home / sparse
    if sparse.exists():
        patterns = sparse.read_text()
        # Generated tests must remain in the sparse checkout across job resets.
        extra = []
        for directory in ("/llvm/test/", "/llvm/test/CodeGen/", "/llvm/test/MC/"):
            extra.extend((directory, "!" + directory + "*/"))
        for kind in ("CodeGen", "MC"):
            extra.extend((f"/llvm/test/{kind}/RISCV/",
                          f"!/llvm/test/{kind}/RISCV/*/",
                          f"/llvm/test/{kind}/RISCV/seal5/"))
        if "/llvm/test/CodeGen/RISCV/seal5/" not in patterns.splitlines():
            patterns = patterns.rstrip() + "\n" + "\n".join(extra) + "\n"
        for directory in ("/llvm/test/Unit/", "/llvm/unittests/", "/third-party/"):
            if directory not in patterns.splitlines():
                patterns += directory + "\n"
        sparse.write_text(patterns)
    for config in (settings.llvm.configs or {}).values():
        config.options.update(LLVM_INCLUDE_TESTS=True, LLVM_BUILD_TESTS=False,
                              LLVM_INCLUDE_UTILS=True, CLANG_INCLUDE_TESTS=False,
                              LLD_INCLUDE_TESTS=False)


def main():
    from seal5.settings import Seal5Settings
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path("/work/llvm"))
    parser.add_argument("--baseline", type=Path, default=Path("/opt/seal5-baseline.yml"))
    args = parser.parse_args()
    settings = Seal5Settings.from_yaml_file(args.baseline)
    configure_regression_tests(args.home, settings)
    git(args.home, "read-tree", "-mu", "HEAD")
    settings.to_yaml_file(args.baseline)


if __name__ == "__main__":
    main()
