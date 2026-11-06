
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "Orbit"

def app_version() -> str:
    try:
        text = (ROOT / "core" / "updater.py").read_text(encoding="utf-8")
        match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text)
        if match:
            return match.group(1)
    except OSError:
        pass
    return "1.1.1"

def run(cmd):
    print("[cmd] " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode != 0:
        print()
        print("[X] A command failed, build stopped. Read the lines above.")
        sys.exit(1)

def slim_onedir(app_dir: Path) -> None:
    if os.environ.get("ORBIT_KEEP_SOFTGL") == "1":
        print("[*] ORBIT_KEEP_SOFTGL=1 - keeping opengl32sw.dll")
    else:
        for dll in app_dir.rglob("opengl32sw.dll"):
            with_context = suppress_unlink(dll)
            if with_context:
                print(f"[-] stripped {dll.relative_to(app_dir)} "
                      "(software-OpenGL fallback, ~20 MB)")
    for qm_root in app_dir.rglob("translations"):
        if "PySide6" not in str(qm_root) and "Qt" not in str(qm_root):
            continue
        if qm_root.is_dir():
            shutil.rmtree(qm_root, ignore_errors=True)
            print(f"[-] stripped {qm_root.relative_to(app_dir)}/ "
                  "(Qt translations, English-only app)")
    for qml_dir in app_dir.rglob("qml"):
        if qml_dir.is_dir() and "PySide6" in str(qml_dir):
            shutil.rmtree(qml_dir, ignore_errors=True)

def suppress_unlink(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except OSError:
        return False

_ISCC_ROOTS = (Path(r"C:\Program Files"), Path(r"C:\Program Files (x86)"))

def find_iscc() -> str | None:
    override = os.environ.get("ORBIT_ISCC")
    if override and Path(override).is_file():
        return override
    found: list[Path] = []
    for root_dir in _ISCC_ROOTS:
        try:
            found.extend(root_dir.glob("Inno Setup */ISCC.exe"))
        except OSError:
            pass

    def _ver_key(p: Path) -> list[int]:
        m = re.search(r"Inno Setup (\d+(?:\.\d+)*)", str(p))
        return [int(x) for x in m.group(1).split(".")] if m else [0]

    if found:
        return str(sorted(found, key=_ver_key, reverse=True)[0])
    return shutil.which("ISCC.exe") or shutil.which("ISCC")

def build_installer(version: str) -> None:
    if not (ROOT / "installer.iss").is_file():
        print("[!] installer.iss is missing - skipping the installer")
        return
    if os.name != "nt":
        print("[!] Installer needs Windows - skipped (portable ZIP is ready)")
        return
    iscc = find_iscc()
    if iscc is None:
        print()
        print("[!] Inno Setup not found (ISCC.exe) - the Setup EXE was skipped.")
        print("    The portable ZIP is still ready to share.")
        print("    To also get a real installer (shortcuts + uninstaller, so the")
        print("    app stays even if the downloaded file is deleted):")
        print("      1. Install Inno Setup: https://jrsoftware.org/isdl.php")
        print("      2. Run: python build.py   (it is detected automatically)")
        print("    (or set ORBIT_ISCC to the full path of ISCC.exe)")
        return
    print("[*] Building the Windows installer ...")
    run([iscc, f"/DAPP_VERSION={version}", "installer.iss"])
    out = ROOT / "dist" / f"Orbit-Setup-{version}.exe"
    if out.exists():
        print(f"[OK] Installer: dist/Orbit-Setup-{version}.exe "
              f"({out.stat().st_size // (1024 * 1024)} MB)")
        print("     Users who run it get the app installed properly: Start-menu")
        print("     + desktop shortcuts and an entry in Windows 'Installed apps'.")
    else:
        print("[!] ISCC finished but the Setup EXE was not found in dist/.")

def main():
    parser = argparse.ArgumentParser(description="Build Orbit")
    parser.add_argument("--onefile", action="store_true",
                        help="produce one big EXE instead of a fast folder "
                             "+ shareable ZIP")
    parser.add_argument("--no-installer", action="store_true",
                        help="skip the Setup EXE (portable ZIP only)")
    args = parser.parse_args()
    version = app_version()
    onefile = args.onefile

    print(f"  Orbit v{version} build")
    print(f"  mode: {'ONEFILE (classic)' if onefile else 'ONEDIR (fast start, recommended)'}")

    try:
        import PyInstaller
    except ImportError:
        print("[*] PyInstaller is missing. Installing it (one time)...")
        run([sys.executable, "-m", "pip", "install", "pyinstaller"])

    cmd = [sys.executable, "-m", "PyInstaller",
           "--noconfirm", "--clean", "--windowed",
           "--name", APP_NAME]
    cmd += ["--onefile"] if onefile else ["--onedir"]
    cmd += ["--hidden-import", "PySide6.QtNetwork"]

    PARSERS = ["parsers.base", "parsers.steam", "parsers.epic",
               "parsers.generic", "parsers.riot", "parsers.rockstar",
               "parsers.battlenet", "parsers.minecraft",
               "parsers.bethesda", "parsers.roblox",
               "parsers.itchio", "parsers.amazon", "parsers.hoyo"]
    for mod in PARSERS:
        cmd += ["--hidden-import", mod]
    cmd += ["--collect-submodules", "parsers"]

    TRIM = ["PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
            "PySide6.QtQuick3D", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
            "PySide6.QtVirtualKeyboard", "PySide6.QtTest", "PySide6.QtSql",
            "PySide6.QtCharts", "PySide6.QtDataVisualization",
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
            "PySide6.QtWebEngineQuick", "PySide6.QtBluetooth", "PySide6.QtNfc",
            "PySide6.QtPositioning", "PySide6.QtSensors",
            "PySide6.QtSerialPort", "PySide6.QtTextToSpeech",
            "PySide6.QtWebChannel", "PySide6.QtWebSockets",
            "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
            "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
            "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
            "PySide6.QtRemoteObjects", "PySide6.QtScxml",
            "PySide6.QtStateMachine", "PySide6.QtLocation",
            "PySide6.QtDesigner", "PySide6.QtAxContainer",
            "PySide6.QtHelp", "PySide6.QtUiTools"]
    for mod in TRIM:
        cmd += ["--exclude-module", mod]

    assets = ROOT / "assets"
    if assets.is_dir():
        cmd += ["--add-data", "assets" + os.pathsep + "assets"]
        for ico in sorted(assets.glob("*.ico")):
            cmd += ["--icon", str(ico)]
            break

    cmd.append("main.py")

    print("[*] Building ... this takes a few minutes, please wait.")
    run(cmd)

    if onefile:
        exe = ROOT / "dist" / (APP_NAME + ".exe")
        if not exe.exists():
            print("[X] Build finished but the EXE was not found in dist/.")
            sys.exit(1)
        print()
        print(f"[OK] Single-file build: dist/{APP_NAME}.exe "
              f"({exe.stat().st_size // (1024 * 1024)} MB)")
        print("     Onefile apps unpack themselves to %TEMP% on every")
        print("     start - that is why the folder build starts faster.")
    else:
        app_dir = ROOT / "dist" / APP_NAME
        exe = app_dir / (APP_NAME + ".exe")
        if not exe.exists():
            print("[X] Build finished but dist/"
                  + APP_NAME + "/" + APP_NAME + ".exe was not found.")
            sys.exit(1)
        print("[*] Slimming the build ...")
        slim_onedir(app_dir)
        zip_path = (ROOT / "dist" /
                    f"Orbit-v{version}-win64")
        if os.environ.get("ORBIT_NO_ZIP") != "1":
            archive = shutil.make_archive(str(zip_path), "zip",
                                          root_dir=str(ROOT / "dist"),
                                          base_dir=APP_NAME)
            print(f"[OK] Shareable ZIP: {archive} "
                  f"({Path(archive).stat().st_size // (1024 * 1024)} MB)")
        print(f"[OK] Folder build: dist/{APP_NAME}/{APP_NAME}.exe "
              f"- start this EXE directly (fast start)")
        total = sum(f.stat().st_size for f in app_dir.rglob("*") if f.is_file())
        print(f"     Folder size: {total // (1024 * 1024)} MB "
              f"(zip usually compresses to roughly half)")
        if not args.no_installer:
            build_installer(version)

    print()
    print("Upload the ZIP and the Setup EXE to a GitHub Release.")
    try:
        input("\nPress Enter to close...")
    except EOFError:
        pass

if __name__ == "__main__":
    main()
