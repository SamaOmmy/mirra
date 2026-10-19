# PyInstaller spec. Build from the project root:  pyinstaller packaging/samantha.spec --noconfirm
# Produces dist/SamanthaScreenMirror/ with two programs sharing one set of libraries:
#   samantha-mirror.exe          console: setup / link / doctor / ...
#   samantha-mirror-service.exe  no window: the server (what start-at-logon runs)
import os

from PyInstaller.utils.hooks import collect_submodules

HERE = SPECPATH  # noqa: F821  (provided by PyInstaller) directory of this file
ROOT = os.path.abspath(os.path.join(HERE, ".."))

hidden = collect_submodules("dxcam") + collect_submodules("comtypes") + ["waitress", "pyaudiowpatch"]
datas = [(os.path.join(ROOT, "samantha_mirror", "web"), "samantha_mirror/web")]
apk_dir = os.path.join(ROOT, "samantha_mirror", "phone_app")   # built by android/build.py; the Android app phones install
if os.path.isdir(apk_dir):
    datas.append((apk_dir, "samantha_mirror/phone_app"))
excludes = ["tkinter", "matplotlib", "pytest", "ruff", "IPython", "scipy", "pandas"]
icon = os.path.join(HERE, "app.ico")


def analysis(script):
    return Analysis([os.path.join(HERE, script)], pathex=[ROOT], datas=datas,  # noqa: F821
                    hiddenimports=hidden, excludes=excludes)


a_cli = analysis("entry_cli.py")
a_svc = analysis("entry_service.py")
MERGE((a_cli, "entry_cli", "samantha-mirror"), (a_svc, "entry_service", "samantha-mirror-service"))  # noqa: F821

exe_cli = EXE(PYZ(a_cli.pure), a_cli.scripts, [], exclude_binaries=True,  # noqa: F821
              name="samantha-mirror", console=True, icon=icon)
exe_svc = EXE(PYZ(a_svc.pure), a_svc.scripts, [], exclude_binaries=True,  # noqa: F821
              name="samantha-mirror-service", console=False, icon=icon)

COLLECT(exe_cli, a_cli.binaries, a_cli.datas,  # noqa: F821
        exe_svc, a_svc.binaries, a_svc.datas,
        name="SamanthaScreenMirror")
