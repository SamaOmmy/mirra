"""Pairing a phone by the code shown in the Samantha window."""
import time

from samantha_mirror import pairing
from samantha_mirror.pairing import Pairing


def test_there_is_no_code_until_the_window_asks_for_one():
    p = Pairing()
    assert p.current() is None
    assert p.claim("000000") is False


def test_the_shown_code_works_with_or_without_spaces_for_several_phones():
    p = Pairing()
    code = p.new_code()["code"]
    assert len(code) == 6 and code.isdigit()
    assert p.claim(f"{code[:3]} {code[3:]}", "Pixel") is True
    assert p.claim(code, "Galaxy") is True        # a second phone while the code lasts
    assert [d["device"] for d in p.recent()] == ["Pixel", "Galaxy"]


def test_a_code_runs_out(monkeypatch):
    p = Pairing()
    code = p.new_code()["code"]
    later = time.monotonic() + pairing.CODE_SECONDS + 1
    monkeypatch.setattr(pairing.time, "monotonic", lambda: later)
    assert p.current() is None
    assert p.claim(code) is False


def test_a_few_wrong_tries_throw_the_code_away():
    p = Pairing()
    code = p.new_code()["code"]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(pairing.MAX_WRONG):
        assert p.claim(wrong) is False
    assert p.claim(code) is False and p.current() is None


def test_a_new_code_replaces_the_old_one_and_cancel_ends_it():
    p = Pairing()
    old = p.new_code()["code"]
    new = p.new_code()["code"]
    if old != new:
        assert p.claim(old) is False
    p.cancel()
    assert p.claim(new) is False


def test_junk_is_refused():
    p = Pairing()
    p.new_code()
    for junk in (None, 123456, ["1"], ""):
        assert p.claim(junk) is False
