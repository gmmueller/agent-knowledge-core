"""Launch a brain's dedicated Chrome/Chromium profile for remote debugging."""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brainlib
from source_helpers import cdp, site


def find_chrome(override=None) -> str:
    if override:
        path = Path(override).expanduser()
        found = str(path.resolve()) if path.is_file() else shutil.which(str(path))
        if not found:
            raise FileNotFoundError(f"Chrome executable not found: {override}")
        return found
    names = ("chrome", "chromium", "chromium-browser", "google-chrome", "google-chrome-stable")
    for name in names:
        if found := shutil.which(name):
            return found
    candidates = []
    if sys.platform == "win32":
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            if base := os.environ.get(variable):
                candidates.extend(Path(base) / suffix for suffix in (
                    "Google/Chrome/Application/chrome.exe", "Chromium/Application/chrome.exe"))
    elif sys.platform == "darwin":
        for base in (Path("/Applications"), Path.home() / "Applications"):
            candidates.extend(base / suffix for suffix in (
                "Google Chrome.app/Contents/MacOS/Google Chrome",
                "Chromium.app/Contents/MacOS/Chromium"))
        candidates.extend(Path(base) / name for base in ("/opt/homebrew/bin", "/usr/local/bin") for name in names)
    else:
        candidates.extend(Path(base) / name for base in ("/usr/bin", "/usr/local/bin", "/snap/bin") for name in names)
        candidates.append(Path("/opt/google/chrome/chrome"))
    for path in candidates:
        if path.is_file():
            return str(path)
    raise FileNotFoundError("Chrome/Chromium was not found; install it or pass --chrome <executable>")


def chrome_command(brain, config, chrome):
    cdp(config)  # Validate the same port the crawlers will connect to.
    url = site(config)
    name = str(config.get("profile") or f"chrome-{brain.name}")
    if name in {".", ".."} or any(c in name for c in "/\\:"):
        raise ValueError("crawl.yaml profile must be a directory name under .secrets/")
    root = brainlib.workspace_secrets(brain.parent).resolve()
    profile = root / name
    if not profile.resolve().is_relative_to(root):
        raise ValueError("Chrome profile must stay under the workspace's .secrets/")
    return [chrome, f"--user-data-dir={profile}", "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={config['cdp_port']}", url]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    brainlib.add_brain_arg(parser)
    parser.add_argument("--chrome", help="Chrome/Chromium executable path or command name")
    args = parser.parse_args()
    try:
        brain = brainlib.brain_dir(args.brain)
        command = chrome_command(brain, brainlib.crawl_config(brain), find_chrome(args.chrome))
        subprocess.Popen(command, start_new_session=sys.platform != "win32")
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(subprocess.list2cmdline(command) if sys.platform == "win32" else shlex.join(command))


if __name__ == "__main__":
    main()
