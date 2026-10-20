import io
import tarfile

import pytest

from worker.etiss_perf.unpack_hls import unpack


def archive(tmp_path, name, kind=tarfile.REGTYPE):
    path = tmp_path / "hls.tar.gz"
    with tarfile.open(path, "w:gz") as output:
        member = tarfile.TarInfo(name)
        member.type = kind
        if kind == tarfile.REGTYPE:
            member.size = 6
            output.addfile(member, io.BytesIO(b"report"))
        else:
            member.linkname = "../../outside"
            output.addfile(member)
    return path


def test_extract_nested_hls_reports(tmp_path):
    path = archive(tmp_path, "variant/report.xml")
    unpack(path, tmp_path / "hls")
    assert (tmp_path / "hls/variant/report.xml").read_bytes() == b"report"


@pytest.mark.parametrize("name,kind", [
    ("../outside", tarfile.REGTYPE),
    ("/outside", tarfile.REGTYPE),
    ("link", tarfile.SYMTYPE),
    ("link", tarfile.LNKTYPE),
])
def test_reject_unsafe_hls_archive(tmp_path, name, kind):
    path = archive(tmp_path, name, kind)
    with pytest.raises(ValueError, match="Unsafe HLS archive entry"):
        unpack(path, tmp_path / "hls")
