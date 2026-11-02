"""Fix list-valued conditional branches in the demo's M2-ISA-R revision.

The preprocessor can emit statement lists, but the ETISS writer assumes every
branch has a generate() method. Generate the individual statements and retain
their CodeStrings for the enclosing operation's exception handling.
"""
import sys
from pathlib import Path


def patch(root):
    path = Path(root) / "m2isar/backends/etiss/instruction_transform.py"
    source = path.read_text()
    old = "\tfor stmt in self.stmts:\n\t\tret = stmt.generate(context)"
    new = ("\tfor stmt in self.stmts:\n"
           "\t\tif isinstance(stmt, list):\n"
           "\t\t\tret = list(flatten([child.generate(context) for child in flatten(stmt)]))\n"
           "\t\telse:\n"
           "\t\t\tret = stmt.generate(context)")
    if new in source:
        return
    if old not in source:
        if "for stmt in expr.stmts:" in source and "if isinstance(stmt, list):" in source:
            return
        raise RuntimeError(f"M2-ISA-R conditional implementation changed: {path}")
    path.write_text(source.replace(old, new, 1))


if __name__ == "__main__":
    patch(sys.argv[1])
