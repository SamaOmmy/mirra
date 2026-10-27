"""The Samantha window's parts that need no screen: mouse and keys to phone input, the picture stream reader,
shortcut fixing, and the update swap reopening the window."""
import io
from pathlib import Path

from samantha_mirror import gestures, shortcuts, updater
from samantha_mirror.client import jpeg_frames
from samantha_mirror.phonelink import parse_input


def test_a_click_is_a_tap_and_holding_still_is_a_long_press():
    p = gestures.Pointer()
    p.down(0.5, 0.5, 0)
    tap = p.up(0.505, 0.5, 120)
    assert tap == {"t": "tap", "x": 0.5, "y": 0.5}
    p.down(0.2, 0.3, 0)
    p.move(0.2, 0.3, 300)
    assert p.up(0.2, 0.3, 700)["t"] == "long"
    assert p.up(0.1, 0.1, 800) is None     # no press in progress


def test_a_drag_is_a_swipe_the_server_accepts():
    p = gestures.Pointer()
    p.down(0.5, 0.9, 0)
    for i in range(1, 500):                # a long, slow drag: points are thinned out
        p.move(0.5, 0.9 - i * 0.0016, i * 20)
    swipe = p.up(0.5, 0.1, 10_000)
    assert swipe["t"] == "gesture" and len(swipe["pts"]) <= gestures.MAX_POINTS
    assert swipe["pts"][0] == [0.5, 0.9] and swipe["pts"][-1] == [0.5, 0.1]
    assert parse_input(swipe) == swipe


def test_dragging_off_the_picture_stays_on_the_phone():
    p = gestures.Pointer()
    p.down(0.5, 0.5, 0)
    swipe = p.up(1.7, -0.4, 200)
    assert swipe["pts"][-1] == [1.0, 0.0]
    assert parse_input(swipe)


def test_the_wheel_scrolls_the_way_the_wheel_turns():
    down = gestures.wheel(0.5, 0.5, -1)      # wheel towards you: see what is further down
    assert down["pts"][1][1] < down["pts"][0][1]
    up = gestures.wheel(0.5, 0.5, 1)
    assert up["pts"][1][1] > up["pts"][0][1]
    assert parse_input(gestures.wheel(0.0, 1.0, -20))


def test_keys_become_text_or_buttons():
    assert gestures.key("a", "a") == ("text", "a")
    assert gestures.key("BackSpace", "\b") == ("text", "\b")
    assert gestures.key("Return", "\r") == ("text", "\n")
    assert gestures.key("Escape", "\x1b") == ("key", "back")
    assert gestures.key("Shift_L", "") is None
    assert gestures.key("F5", "") is None


def test_pictures_are_read_from_the_stream_one_by_one():
    one, two = b"\xff\xd8one", b"\xff\xd8second"
    data = b"".join(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n%s\r\n" % (len(j), j) for j in (one, two))
    assert list(jpeg_frames(io.BytesIO(data))) == [one, two]
    assert list(jpeg_frames(io.BytesIO(data[:-8]))) == [one]     # cut off mid-picture


def test_old_shortcuts_are_pointed_at_the_window():
    window = Path(r"C:\Apps\SamanthaScreenMirror\Samantha.exe")
    script = shortcuts.script(window, [Path(r"C:\Users\me\Desktop")], create=True)
    assert r"'C:\Apps\SamanthaScreenMirror\samantha-mirror.exe'" in script        # only links to our old program
    assert "-not $link.Arguments" in script                                           # not ones that run a command
    assert r"Samantha.lnk" in script


def test_shortcuts_are_left_alone_when_running_from_source():
    assert shortcuts.window_exe() is None
    assert shortcuts.update() is False


def test_the_update_swap_reopens_the_window_when_it_started_it():
    script = updater.swap_script(Path(r"C:\A\Sam"), Path(r"C:\A\Sam.update"), "Task", 42, Path(r"C:\A\update.log"),
                                 "Samantha.exe")
    assert "$relaunch = 'Samantha.exe'" in script and "Start-Process" in script
    assert "samantha-mirror-service, samantha-mirror, Samantha" in script
    quiet = updater.swap_script(Path(r"C:\A\Sam"), Path(r"C:\A\Sam.update"), "Task", 42, Path(r"C:\A\update.log"))
    assert "$relaunch = ''" in quiet
