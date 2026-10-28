"""Extract uploaded reports without allowing paths or links outside the job."""
import sys
import tarfile
from pathlib import Path


def unpack(archive, destination):
    root = Path(destination).resolve()
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        for member in members:
            target = (root / member.name).resolve()
            if not target.is_relative_to(root) or not (member.isfile() or member.isdir()):
                raise ValueError(f"Unsafe HLS archive entry: {member.name}")
        source.extractall(root, members=members)


if __name__ == "__main__":
    unpack(*sys.argv[1:])
