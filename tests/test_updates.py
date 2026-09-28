import hashlib
import zipfile

import pytest

from idb_macro.core import updates as u


def test_versions():
    assert u.is_newer("v1.2.0", "1.1.0")
    assert u.is_newer("1.10", "1.9.9")
    assert not u.is_newer("1.1", "1.1.0")
    with pytest.raises(u.UpdateError):
        u.parse_version("latest")


def test_parse_release_picks_asset_and_digest():
    rel = u.parse_release({"tag_name": "v1.2.0", "body": "notes", "html_url": "https://github.com/x",
                           "assets": [{"name": u.ASSET_NAME, "browser_download_url": "https://github.com/a.zip",
                                       "size": 5, "digest": "sha256:" + "AB" * 32}]})
    assert (rel.version, rel.asset_url, rel.sha256) == ("1.2.0", "https://github.com/a.zip", "ab" * 32)
    with pytest.raises(u.UpdateError):
        u.parse_release({"assets": []})


def test_only_github_https_is_allowed():
    for bad in ("http://github.com/x", "https://evil.example/x", "file:///c:/x", "https://github.com.evil.io/x"):
        with pytest.raises(u.UpdateError):
            u._check_url(bad)
    u._check_url("https://objects.githubusercontent.com/x")


class FakeResp:
    def __init__(self, data, url="https://github.com/x"):
        self.data, self.url, self.pos = data, url, 0

    def read(self, n=-1):
        chunk = self.data[self.pos:self.pos + (len(self.data) if n < 0 else n)]
        self.pos += len(chunk)
        return chunk

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_download_verifies_checksum(tmp_path, monkeypatch):
    payload = b"zipdata"
    monkeypatch.setattr(u, "_open", lambda url: FakeResp(payload))
    rel = u.Release("1.2", "", "", "", asset_url="https://github.com/a.zip",
                    sha256=hashlib.sha256(payload).hexdigest())
    assert u.download(rel, tmp_path).read_bytes() == payload
    rel.sha256 = "0" * 64
    with pytest.raises(u.UpdateError, match="checksum"):
        u.download(rel, tmp_path)
    assert not (tmp_path / u.ASSET_NAME).exists()
    rel.sha256 = ""
    with pytest.raises(u.UpdateError, match="no checksum"):
        u.download(rel, tmp_path)


def test_safe_extract_blocks_zip_slip(tmp_path):
    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good, "w") as z:
        z.writestr("IDB-Macro/IDB-Macro.exe", b"x")
    assert u.safe_extract(good, tmp_path / "out").name == "IDB-Macro"
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../../evil.exe", b"x")
    with pytest.raises(u.UpdateError, match="unsafe"):
        u.safe_extract(bad, tmp_path / "out2")
