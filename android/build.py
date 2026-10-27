"""Build the Android apps with the plain Android SDK tools: no Gradle, no libraries.

    python android/build.py            builds samantha_mirror/phone_app/SamanthaPhone.apk (the Samantha app)
                                       and SamanthaSetup.apk next to it

Samantha Setup (android/setup/) carries a copy of the Samantha app and installs it through Android's installer
session. Android 13+ blocks the Accessibility switch ("Restricted setting") for apps installed from a downloaded
file, but not for apps installed that way, so people install Samantha with Setup.

Needs: a JDK (javac, keytool) and the Android SDK with build-tools and a platform (android.jar, API 34 or newer).
They are found through JAVA_HOME / ANDROID_HOME / ANDROID_SDK_ROOT, or a standard install location.

Signing: set SM_KEYSTORE, SM_KEYSTORE_PASS (and optionally SM_KEY_ALIAS) to sign with your release key. Without
them a local key (android/dev.keystore, never committed) is created and used. Android only updates an app in place
when the new APK is signed with the same key, so keep the key you release with.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = Path(os.environ.get("SM_APK_OUT") or ROOT / "samantha_mirror" / "phone_app" / "SamanthaPhone.apk")
SETUP_OUT = OUT.with_name("SamanthaSetup.apk")
SETUP_ASSET = "Mirra.apk"   # the name SetupActivity opens
MIN_SDK, TARGET_SDK = 30, 34   # 30: the first Android with accessibility screenshots


def fail(message: str):
    sys.exit(f"build failed: {message}")


def version() -> str:
    text = (ROOT / "samantha_mirror" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def version_code(name: str) -> int:
    major, minor, patch = (int(p) for p in (name.split(".") + ["0", "0"])[:3])
    return major * 10000 + minor * 100 + patch


def find_sdk() -> Path:
    candidates = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
                  str(Path.home() / "AppData/Local/Android/Sdk"), str(Path.home() / "Android/Sdk"), "C:/src/android-sdk"]
    for c in candidates:
        if c and (Path(c) / "build-tools").is_dir():
            return Path(c)
    fail("Android SDK not found. Set ANDROID_HOME.")


def find_jdk_tool(name: str) -> str:
    home = os.environ.get("JAVA_HOME")
    if home:
        for ext in (".exe", ""):
            p = Path(home) / "bin" / (name + ext)
            if p.exists():
                return str(p)
    found = shutil.which(name)
    if found:
        return found
    if Path("C:/src/jdk/bin").is_dir():
        for ext in (".exe", ""):
            p = Path("C:/src/jdk/bin") / (name + ext)
            if p.exists():
                return str(p)
    fail(f"{name} not found. Install a JDK 17+ or set JAVA_HOME.")


def tool(build_tools: Path, name: str) -> str:
    for ext in (".exe", ".bat", ""):
        p = build_tools / (name + ext)
        if p.exists():
            return str(p)
    fail(f"{name} not found in {build_tools}")


def run(*cmd, cwd=None):
    result = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        fail(f"{Path(str(cmd[0])).name} {' '.join(str(c) for c in cmd[1:4])} ...\n{result.stdout}{result.stderr}")
    return result.stdout


def signing() -> tuple[Path, str, str]:
    keystore = os.environ.get("SM_KEYSTORE")
    if keystore:
        password = os.environ.get("SM_KEYSTORE_PASS")
        if not password:
            fail("SM_KEYSTORE is set but SM_KEYSTORE_PASS is not.")
        return Path(keystore), password, os.environ.get("SM_KEY_ALIAS", "samantha")
    path = HERE / "dev.keystore"
    if not path.exists():
        print("Creating a local signing key (android/dev.keystore). Keep it: updates must be signed by the same key.")
        run(find_jdk_tool("keytool"), "-genkeypair", "-keystore", path, "-storepass", "samantha-dev", "-keypass",
            "samantha-dev", "-alias", "samantha", "-keyalg", "RSA", "-keysize", "3072", "-validity", "9125",
            "-dname", "CN=Samantha Phone")
    return path, "samantha-dev", "samantha"


def build_apk(build_tools: Path, android_jar: Path, name: str, app: Path, out: Path,
              extra_res: list[Path] = (), assets: Path | None = None) -> None:
    """One APK from app/AndroidManifest.xml, app/res, app/src (and optional extra resource files and assets)."""
    with tempfile.TemporaryDirectory(prefix="samantha-apk-") as tmp:
        tmp = Path(tmp)
        compiled, gen, classes, dex = tmp / "res.zip", tmp / "gen", tmp / "classes", tmp / "dex"
        for d in (gen, classes, dex):
            d.mkdir()

        run(tool(build_tools, "aapt2"), "compile", "--dir", app / "res", "-o", compiled)
        flats = []
        for i, res in enumerate(extra_res):
            flat_dir = tmp / f"extra{i}"
            flat_dir.mkdir()
            run(tool(build_tools, "aapt2"), "compile", res, "-o", flat_dir)
            flats += list(flat_dir.iterdir())
        base = tmp / "base.apk"
        run(tool(build_tools, "aapt2"), "link", "-o", base, "-I", android_jar, "--manifest", app / "AndroidManifest.xml",
            "--min-sdk-version", MIN_SDK, "--target-sdk-version", TARGET_SDK, "--version-code", version_code(name),
            "--version-name", name, "--java", gen, *(["-A", assets] if assets else []), compiled, *flats)

        sources = [str(p) for p in list((app / "src").rglob("*.java")) + list(gen.rglob("*.java"))]
        run(find_jdk_tool("javac"), "--release", "17", "-encoding", "UTF-8", "-Xlint:-options", "-classpath", android_jar, "-d", classes, *sources)
        class_files = [str(p) for p in classes.rglob("*.class")]
        run(tool(build_tools, "d8"), "--release", "--min-api", MIN_SDK, "--lib", android_jar, "--output", dex, *class_files)

        unsigned = tmp / "unsigned.apk"
        with zipfile.ZipFile(base) as src, zipfile.ZipFile(unsigned, "w", zipfile.ZIP_DEFLATED) as apk:
            for item in src.infolist():
                apk.writestr(item, src.read(item.filename))
            apk.write(dex / "classes.dex", "classes.dex")

        aligned = tmp / "aligned.apk"
        run(tool(build_tools, "zipalign"), "-f", "-p", 4, unsigned, aligned)
        keystore, password, alias = signing()
        out.parent.mkdir(parents=True, exist_ok=True)
        run(tool(build_tools, "apksigner"), "sign", "--v4-signing-enabled", "false", "--ks", keystore, "--ks-pass", f"pass:{password}", "--ks-key-alias", alias,
            "--out", out, aligned)
        run(tool(build_tools, "apksigner"), "verify", out)
    print(f"Built {out} ({out.stat().st_size // 1024} KB)")


def main():
    sdk = find_sdk()
    build_tools = sorted((sdk / "build-tools").iterdir(), key=lambda p: [int(x) if x.isdigit() else 0 for x in re.split(r"\D+", p.name)])[-1]
    platforms = sorted((p for p in (sdk / "platforms").iterdir() if (p / "android.jar").exists()), key=lambda p: p.name)
    platform = next((p for p in platforms if p.name == f"android-{TARGET_SDK}"), platforms[-1] if platforms else None)
    if platform is None:
        fail("No Android platform (android.jar) installed in the SDK.")
    android_jar = platform / "android.jar"
    name = version()
    print(f"Mirra for Android {name}: build-tools {build_tools.name}, {platform.name}")

    build_apk(build_tools, android_jar, name, HERE, OUT)
    with tempfile.TemporaryDirectory(prefix="samantha-setup-assets-") as assets:
        shutil.copy(OUT, Path(assets) / SETUP_ASSET)   # Setup installs this copy
        build_apk(build_tools, android_jar, name, HERE / "setup", SETUP_OUT,
                  extra_res=[HERE / "res" / "drawable" / f"{n}.xml" for n in
                             ("ic_launcher_background", "ic_launcher_foreground", "ic_launcher_monochrome", "logo")]
                  + [HERE / "res" / "mipmap-anydpi" / "ic_launcher.xml"], assets=Path(assets))


if __name__ == "__main__":
    main()
