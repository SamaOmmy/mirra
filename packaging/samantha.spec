# PyInstaller spec. Build from the project root:  pyinstaller packaging/samantha.spec --noconfirm
# Produces dist/Mirra/ with three programs sharing one set of libraries:
#   Mirra.exe                    the Mirra window (what the shortcuts open)
#   samantha-mirror.exe          console: doctor / update / ... (double-clicked, it opens the window)
#   samantha-mirror-service.exe  no window: the background service (what start-at-logon runs; the name stays the same
#                                so the task of an older install keeps working after an update)
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

HERE = SPECPATH  # noqa: F821  (provided by PyInstaller) directory of this file
ROOT = os.path.abspath(os.path.join(HERE, ".."))

hidden = collect_submodules("dxcam") + collect_submodules("comtypes") + ["waitress", "pyaudiowpatch"]
datas = [(os.path.join(ROOT, "samantha_mirror", "web"), "samantha_mirror/web"),
         (os.path.join(ROOT, "samantha_mirror", "assets"), "samantha_mirror/assets")]
datas += collect_data_files("customtkinter")
apk_dir = os.path.join(ROOT, "samantha_mirror", "phone_app")   # built by android/build.py; phones install and update from here
if os.path.isdir(apk_dir):
    datas.append((apk_dir, "samantha_mirror/phone_app"))
excludes = ["matplotlib", "pytest", "ruff", "IPython", "scipy", "pandas"]
icon = os.path.join(HERE, "mirra.ico")


def analysis(script):
    return Analysis([os.path.join(HERE, script)], pathex=[ROOT], datas=datas,  # noqa: F821
                    hiddenimports=hidden, excludes=excludes)


a_app = analysis("entry_app.py")
a_cli = analysis("entry_cli.py")
a_svc = analysis("entry_service.py")
MERGE((a_app, "entry_app", "Mirra"), (a_cli, "entry_cli", "samantha-mirror"),  # noqa: F821
      (a_svc, "entry_service", "samantha-mirror-service"))

exe_app = EXE(PYZ(a_app.pure), a_app.scripts, [], exclude_binaries=True,  # noqa: F821
              name="Mirra", console=False, icon=icon)
exe_cli = EXE(PYZ(a_cli.pure), a_cli.scripts, [], exclude_binaries=True,  # noqa: F821
              name="samantha-mirror", console=True, icon=icon)
exe_svc = EXE(PYZ(a_svc.pure), a_svc.scripts, [], exclude_binaries=True,  # noqa: F821
              name="samantha-mirror-service", console=False, icon=icon)

COLLECT(exe_app, a_app.binaries, a_app.datas,  # noqa: F821
        exe_cli, a_cli.binaries, a_cli.datas,
        exe_svc, a_svc.binaries, a_svc.datas,
        name="Mirra")
