#!/usr/bin/env python3
"""Upgrade an image-owned LLVM stage-zero baseline for current Seal5 markers."""
import argparse
import re
import subprocess
from pathlib import Path


def git(home, *args, **kwargs):
    return subprocess.run(["git", "-C", str(home), *args], check=True, **kwargs)


def missing_marker_patch(home, patch):
    """Select wholly missing comment-only hunks; reject partial marker sites."""
    selected, changed = [], set()
    for section in re.split(r"(?m)(?=^diff --git )", patch):
        if not section.strip():
            continue
        lines = section.splitlines(keepends=True)
        filename = next(line[6:].strip() for line in lines if line.startswith("+++ b/"))
        content = (home / filename).read_text()
        starts = [index for index, line in enumerate(lines) if line.startswith("@@ ")]
        header = lines[:starts[0]]
        hunks = []
        for number, start in enumerate(starts):
            end = starts[number + 1] if number + 1 < len(starts) else len(lines)
            hunk = lines[start:end]
            additions = [line[1:].strip() for line in hunk[1:] if line.startswith("+")]
            markers = [line for line in additions if "INSERTION_" in line]
            if not markers or any(line and not line.startswith(("//", "#")) for line in additions):
                raise ValueError(f"Baseline migration requires comment-only marker hunks: {filename}")
            present = [marker in content for marker in markers]
            if all(present):
                continue
            if any(present):
                raise ValueError(f"Partially present marker site in {filename}")
            hunks.extend(hunk)
            changed.add(filename)
        if hunks:
            selected.extend(header + hunks)
    return "".join(selected), sorted(changed)


def upgrade(home, baseline):
    from seal5.resources.resources import get_patches
    from seal5.settings import Seal5Settings
    from seal5.tools.llvm import detect_llvm_imm_types

    home, baseline = Path(home), Path(baseline)
    settings = Seal5Settings.from_yaml_file(baseline)
    version = settings.llvm.state.version.major
    patches = get_patches(patch_name=f"insert_markers_llvm{version}", target="llvm")
    if len(patches) != 1:
        raise ValueError(f"Expected one marker patch for LLVM {version}")
    # This script is run during image construction, before accepting any jobs.
    dirty = git(home, "status", "--porcelain", "--untracked-files=no", capture_output=True, text=True).stdout
    if dirty.strip():
        raise RuntimeError("Refusing to migrate a baseline with uncommitted tracked changes")
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
            sparse.write_text(patterns.rstrip() + "\n" + "\n".join(extra) + "\n")
    git(home, "reset", "--hard", "seal5-default-stage0")
    patch, files = missing_marker_patch(home, patches[0].read_text())
    if patch:
        git(home, "apply", "--check", "-", input=patch, text=True)
        git(home, "apply", "-", input=patch, text=True)
        git(home, "add", "--", *files)
        git(home, "-c", "user.name=Seal5", "-c", "user.email=seal5@localhost",
            "commit", "-m", "Update Seal5 stage-zero insertion markers")
        git(home, "tag", "--force", "seal5-default-stage0")
    revision = git(home, "rev-parse", "HEAD", capture_output=True, text=True).stdout.strip()
    settings.llvm.state.base_commit = revision
    settings.patches = [item for item in settings.patches
                        if item.name not in {"uimm12_op", "uimm12_op_llvm19"}]
    if settings.llvm.state.supported_imm_types is None:
        settings.llvm.state.supported_imm_types = sorted(detect_llvm_imm_types(home))
    settings.to_yaml_file(baseline)
    print(f"Seal5 baseline {revision}: updated {len(files)} marker file(s)", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path("/work/llvm"))
    parser.add_argument("--baseline", type=Path, default=Path("/opt/seal5-baseline.yml"))
    args = parser.parse_args()
    upgrade(args.home, args.baseline)


if __name__ == "__main__":
    main()
