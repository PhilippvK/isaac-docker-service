#!/usr/bin/env python3
import json
import os
import re
from pathlib import Path
import subprocess
import sys

from m2isar.backends.spike.plugin import generate_plugin, identifier


def adapt_extension_api(source):
    """Support Spike releases whose extension API has no processor arguments."""
    # The generated source contains the concrete class name, so match its
    # signature while preserving the body.
    name_sig = "const char* name() const override {"
    if name_sig in source:
        source = source.replace(name_sig, "const char* name() {", 1)
        # Supply the newer const overload as well as the legacy pure virtual.
        start = source.index("const char* name() {")
        end = source.index("\n", start)
        definition = source[start:end]
        source = source[:end] + "\n" + definition.replace("name()", "name() const", 1) + source[end:]
    insn_sig = "std::vector<insn_desc_t> get_instructions(const processor_t&) override {"
    if insn_sig in source:
        source = source.replace(insn_sig, "std::vector<insn_desc_t> get_instructions() {", 1)
        start = source.index("std::vector<insn_desc_t> get_instructions() {")
        end = source.index("\n", start)
        source = source[:end] + "\nstd::vector<insn_desc_t> get_instructions(const processor_t&) { return get_instructions(); }" + source[end:]
    disasm_sig = "std::vector<disasm_insn_t*> get_disasms(const processor_t* = nullptr) override {"
    if disasm_sig in source:
        source = source.replace(disasm_sig, "std::vector<disasm_insn_t*> get_disasms() {", 1)
        start = source.index("std::vector<disasm_insn_t*> get_disasms() {")
        end = source.index("\n", start)
        source = source[:end] + "\nstd::vector<disasm_insn_t*> get_disasms(const processor_t*) { return get_disasms(); }" + source[end:]
    reset_sig = "void reset(processor_t&) override {"
    if reset_sig in source:
        source = source.replace(reset_sig, "void reset() {", 1)
        start = source.index("void reset() {")
        end = source.index("\n", start)
        source = source[:end] + "\nvoid reset(processor_t&) { reset(); }" + source[end:]
    # This Spike release defines six descriptor fields. Newer M2-ISA-R emits
    # ten for releases with separate compressed and privilege handlers.
    source = re.sub(
        r"\{\{(0x[0-9a-fA-F]+,\s*0x[0-9a-fA-F]+),\s*([^,]+)(?:,[^}]+){7}\}\}",
        r"{{\1, \2, \2, \2, \2}}",
        source,
    )
    log_line = "if (p->get_log_commits_enabled()) p->get_state()->log_reg_write[i << 4] = {value, 0};"
    if log_line in source:
        source = source.replace(log_line, "#ifdef RISCV_ENABLE_COMMITLOG\n" + log_line + "\n#endif", 1)
    return source


def main():
    job = Path(os.environ["JOB_DIR"])
    inputs = job / "input"
    top_files = [p for p in inputs.glob("*.core_desc")
                 if any(line.lstrip().startswith("Core ") for line in p.read_text().splitlines())]
    if len(top_files) != 1:
        raise RuntimeError("Spike requires exactly one top-level .core_desc containing a Core declaration")
    top = top_files[0]
    core_name = next(line.split()[1] for line in top.read_text().splitlines()
                     if line.lstrip().startswith("Core "))
    print("::progress:: 0.05 0.20 Parsing CoreDSL", flush=True)
    subprocess.run([sys.executable, "-m", "m2isar.frontends.coredsl2.parser", str(top)], check=True)
    model = inputs / "gen_model" / f"{top.stem}.m2isarmodel"
    if not model.is_file():
        raise FileNotFoundError(f"CoreDSL parser did not produce {model}")

    import pickle
    with model.open("rb") as stream:
        core = pickle.load(stream).cores[core_name]
    source = adapt_extension_api(generate_plugin(core, custom_only=True, strict=True))

    install = os.environ.get("SPIKE_INSTALL_DIR")
    if not install and os.environ.get("MLONMCU_HOME"):
        install = str(Path(os.environ["MLONMCU_HOME"]) / "deps/install/spike")
    include_dirs = []
    if install:
        install_path = Path(install).resolve()
        include_dirs.extend(install_path / p for p in ("include/riscv", "include", "include/fesvr"))
    source_dir = os.environ.get("SPIKE_SOURCE_DIR")
    if source_dir:
        source_path = Path(source_dir).resolve()
        include_dirs.extend(source_path / p for p in ("", "riscv", "fesvr", "softfloat"))
    build_dir = os.environ.get("SPIKE_BUILD_DIR")
    if build_dir:
        include_dirs.append(Path(build_dir).resolve())
    if not any((directory / "extension.h").is_file() for directory in include_dirs):
        raise FileNotFoundError("Spike extension.h is unavailable; configure SPIKE_INSTALL_DIR or SPIKE_SOURCE_DIR")

    output = job / "output" / "spike"
    output.mkdir(parents=True, exist_ok=True)
    cpp = output / "extension.cc"
    cpp.write_text(source)
    library = output / "libextension.so"
    print("::progress:: 0.55 0.90 Compiling Spike extension", flush=True)
    subprocess.run([os.environ.get("CXX", "c++"), "-std=c++17", "-shared", "-fPIC",
                    *[f"-I{directory}" for directory in include_dirs], str(cpp), "-o", str(library)], check=True)
    (output / "spike_plugin.json").write_text(json.dumps({
        "schema": 1,
        "core": core_name,
        "extlibs": ["libextension.so"],
        "extension_names": [identifier(core_name)],
    }, indent=2) + "\n")
    print("::progress:: 0.94 0.94 Spike retargeting complete", flush=True)


if __name__ == "__main__":
    main()
