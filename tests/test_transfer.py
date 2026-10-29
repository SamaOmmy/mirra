"""Files both ways: the phone sends to Downloads\\Mirra, the PC's files wait for the phone to fetch them."""
import io
from urllib.parse import quote

import pytest

from samantha_mirror import transfer
from samantha_mirror.phonelink import PhoneHub
from samantha_mirror.server import create_app
from samantha_mirror.transfer import Inbox, Outbox, TransferError, safe_name
from tests.conftest import TOKEN

AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.mark.parametrize("sent, saved", [
    ("photo.jpg", "photo.jpg"),
    ("..\\..\\Windows\\evil.exe", "evil.exe"),
    ("/etc/passwd", "passwd"),
    ('a<b>c:d"e|f?g*h.txt', "a_b_c_d_e_f_g_h.txt"),
    ("CON.txt", "_CON.txt"),
    ("nul", "_nul"),
    ("report. ", "report"),
])
def test_names_from_the_other_side_are_made_safe(sent, saved):
    assert safe_name(sent) == saved


def test_a_nameless_file_still_gets_a_name():
    assert safe_name("").startswith("file ") and safe_name("...").startswith("file ")


def test_received_files_never_replace_each_other(tmp_path):
    inbox = Inbox(tmp_path)
    first = inbox.receive("a.txt", io.BytesIO(b"one"), 3)
    second = inbox.receive("a.txt", io.BytesIO(b"two"), 3)
    assert (first.name, second.name) == ("a.txt", "a (2).txt")
    assert first.read_bytes() == b"one" and second.read_bytes() == b"two"
    assert [f["name"] for f in inbox.recent()] == ["a (2).txt", "a.txt"]
    assert not list(tmp_path.glob(".mirra-*"))   # no half files left


def test_an_incomplete_or_oversized_file_is_not_kept(tmp_path, monkeypatch):
    inbox = Inbox(tmp_path)
    with pytest.raises(TransferError):
        inbox.receive("a.txt", io.BytesIO(b"on"), 3)
    monkeypatch.setattr(transfer, "MAX_FILE", 4)
    with pytest.raises(TransferError):
        inbox.receive("b.txt", io.BytesIO(b"12345"), None)
    assert list(tmp_path.iterdir()) == [] and inbox.recent() == []


def test_a_waiting_file_goes_once_fetched_or_expired(tmp_path, monkeypatch):
    outbox = Outbox(tmp_path)
    item = outbox.add("x.pdf", io.BytesIO(b"pdf"), 3)
    assert outbox.get(item["id"])["path"].read_bytes() == b"pdf"
    outbox.done(item["id"])
    assert outbox.get(item["id"]) is None and list(tmp_path.iterdir()) == []
    item = outbox.add("y.pdf", io.BytesIO(b"pdf"), 3)
    monkeypatch.setattr(transfer, "WAITING_FOR", -1)
    assert outbox.get(item["id"]) is None and list(tmp_path.iterdir()) == []


@pytest.fixture
def setup(cfg, tmp_path):
    hub, inbox, outbox = PhoneHub(), Inbox(tmp_path / "in"), Outbox(tmp_path / "out")
    app = create_app(cfg, phone=hub, inbox=inbox, outbox=outbox)
    app.testing = True
    return app.test_client(), hub, inbox


def test_the_phone_sends_a_file_to_the_pc(setup):
    client, _hub, inbox = setup
    body = b"\x89PNG" + bytes(range(256)) * 4000   # about 1 MB, larger than a phone screenshot may be
    r = client.post("/api/phone/upload", data=body, headers=AUTH | {"X-File-Name": quote("Holiday ünïcode.png")})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["name"] == "Holiday ünïcode.png"
    assert (inbox.folder / "Holiday ünïcode.png").read_bytes() == body
    state = client.get("/api/phone/state", headers=AUTH).get_json()
    assert state["received"][0]["name"] == "Holiday ünïcode.png"


def test_sending_needs_the_token(setup):
    client, _hub, inbox = setup
    assert client.post("/api/phone/upload", data=b"x", headers={"X-File-Name": "a"}).status_code == 401
    assert client.get("/api/phone/files/anything").status_code == 401
    assert not inbox.folder.exists()


def test_the_pc_sends_a_file_and_the_phone_fetches_it_once(setup):
    client, hub, _inbox = setup
    r = client.post("/api/phone/send", data=b"hello", headers=AUTH | {"X-File-Name": "note.txt"})
    assert r.status_code == 409   # no phone yet
    hub.hello({"device": "Pixel"})
    hub.next_commands(timeout=0)
    r = client.post("/api/phone/send", data=b"hello", headers=AUTH | {"X-File-Name": "note.txt"})
    assert r.status_code == 200
    [command] = hub.next_commands(timeout=0)
    assert command["t"] == "file" and command["name"] == "note.txt" and command["size"] == 5
    r = client.get(f"/api/phone/files/{command['id']}", headers=AUTH)
    assert r.data == b"hello" and r.headers["X-File-Name"] == "note.txt"
    assert client.get(f"/api/phone/files/{command['id']}", headers=AUTH).status_code == 404
