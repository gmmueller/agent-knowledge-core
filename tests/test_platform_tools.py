"""Offline portability checks; no installed browser, GPU, or optional models needed."""
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import brainlib
import launch_chrome
import whisper_runtime

TOOLS = Path(__file__).resolve().parents[1] / "tools"


class ChromeTests(unittest.TestCase):
    def lookup(self, platform, expected, environment=None):
        with patch.object(sys, "platform", platform), \
                patch.object(launch_chrome.shutil, "which", return_value=None), \
                patch.dict(launch_chrome.os.environ, environment or {}, clear=True), \
                patch.object(Path, "home", return_value=Path("home")), \
                patch.object(Path, "is_file", lambda path: path == expected):
            self.assertEqual(launch_chrome.find_chrome(), str(expected))

    def test_windows_install_and_local_appdata(self):
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            with self.subTest(variable=variable):
                base = Path("browser-install")
                self.lookup("win32", base / "Google/Chrome/Application/chrome.exe", {variable: str(base)})

    def test_macos_app_bundle_and_homebrew(self):
        for path in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                     "/Applications/Chromium.app/Contents/MacOS/Chromium",
                     "/opt/homebrew/bin/chromium", "/usr/local/bin/chromium"):
            with self.subTest(path=path):
                self.lookup("darwin", Path(path))

    def test_linux_standard_and_snap_paths(self):
        for path in ("/usr/bin/google-chrome", "/snap/bin/chromium", "/opt/google/chrome/chrome"):
            with self.subTest(path=path):
                self.lookup("linux", Path(path))

    def test_path_lookup_and_explicit_override(self):
        with patch.object(launch_chrome.shutil, "which", return_value="browser-command"):
            self.assertEqual(launch_chrome.find_chrome(), "browser-command")
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "custom browser"
            executable.touch()
            self.assertEqual(launch_chrome.find_chrome(str(executable)), str(executable.resolve()))

    def test_missing_browser(self):
        with patch.object(launch_chrome.shutil, "which", return_value=None), \
                patch.object(Path, "is_file", return_value=False):
            with self.assertRaisesRegex(FileNotFoundError, "--chrome"):
                launch_chrome.find_chrome()
            with self.assertRaisesRegex(FileNotFoundError, "not found"):
                launch_chrome.find_chrome("missing-browser")

    def test_main_starts_and_prints_the_configured_command(self):
        with tempfile.TemporaryDirectory() as directory:
            brain = Path(directory) / "my-course"
            brainlib.write_text(brain / "brain.md", "# My Course\n")
            brainlib.write_text(brain / "crawl.yaml", "site: https://example.com/login\ncdp_port: 9333\nprofile: chrome-course\n")
            with patch.object(sys, "argv", ["launch_chrome.py", "--brain", str(brain)]), \
                    patch.object(launch_chrome, "find_chrome", return_value="browser"), \
                    patch.object(launch_chrome.subprocess, "Popen") as launch, \
                    patch("builtins.print") as output:
                launch_chrome.main()
            self.assertIn("--remote-debugging-port=9333", launch.call_args.args[0])
            self.assertIn("--remote-debugging-port=9333", output.call_args.args[0])

    def test_profile_and_port_use_brain_config(self):
        with tempfile.TemporaryDirectory() as directory:
            brain = Path(directory) / "my-course"
            config = {"site": "https://example.com/login", "cdp_port": 9333, "profile": "chrome-course"}
            command = launch_chrome.chrome_command(brain, config, "browser")
            self.assertIn(f"--user-data-dir={Path(directory).resolve() / '.secrets/chrome-course'}", command)
            self.assertIn("--remote-debugging-port=9333", command)
            self.assertEqual(command[-1], config["site"])
            for invalid in ("../outside", "..\\outside", "a:b", ".."):
                with self.subTest(profile=invalid), self.assertRaises(ValueError):
                    launch_chrome.chrome_command(brain, {**config, "profile": invalid}, "browser")
            for port in (True, 0, 65536, "9222"):
                with self.subTest(port=port), self.assertRaises(SystemExit):
                    launch_chrome.chrome_command(brain, {**config, "cdp_port": port}, "browser")


class RuntimeTests(unittest.TestCase):
    def test_cuda_or_cpu_without_torch(self):
        for count, device, compute_type in ((1, "cuda", "float16"), (0, "cpu", "int8")):
            with self.subTest(device=device), patch.object(whisper_runtime, "load_cuda_dlls"), \
                    patch.dict(sys.modules, {"ctranslate2": SimpleNamespace(get_cuda_device_count=lambda: count)}):
                self.assertEqual(whisper_runtime.model_options(), {"device": device, "compute_type": compute_type})

    def test_cuda_probe_failure_uses_cpu(self):
        def unavailable():
            raise RuntimeError("driver unavailable")
        with patch.object(whisper_runtime, "load_cuda_dlls"), \
                patch.dict(sys.modules, {"ctranslate2": SimpleNamespace(get_cuda_device_count=unavailable)}):
            self.assertEqual(whisper_runtime.model_options()["device"], "cpu")

    def test_non_windows_never_registers_dlls(self):
        for platform in ("darwin", "linux"):
            with self.subTest(platform=platform), patch.object(sys, "platform", platform), \
                    patch.object(whisper_runtime.os, "add_dll_directory", create=True) as add:
                whisper_runtime.load_cuda_dlls()
                add.assert_not_called()

    def test_windows_keeps_dll_handles_and_registers_only_once(self):
        folder = Path("cuda-wheel/bin")
        with patch.object(sys, "platform", "win32"), \
                patch.object(whisper_runtime, "_dll_handles", []), \
                patch.dict(sys.modules, {"nvidia": SimpleNamespace(__path__=["cuda-wheel"])}), \
                patch.object(Path, "glob", return_value=[folder]), \
                patch.dict(whisper_runtime.os.environ, {"PATH": "existing"}), \
                patch.object(whisper_runtime.os, "add_dll_directory", create=True) as add:
            whisper_runtime.load_cuda_dlls()
            whisper_runtime.load_cuda_dlls()
            add.assert_called_once_with(str(folder))
            self.assertEqual(whisper_runtime._dll_handles, [add.return_value])
            self.assertTrue(whisper_runtime.os.environ["PATH"].startswith(str(folder)))

    def test_external_program_error_is_actionable(self):
        with patch.object(brainlib.shutil, "which", return_value=None):
            with self.assertRaisesRegex(FileNotFoundError, "ffmpeg.*PATH"):
                brainlib.executable("ffmpeg")
        with patch.object(brainlib.shutil, "which", return_value="resolved-program"):
            self.assertEqual(brainlib.executable("ffmpeg"), "resolved-program")

    def test_all_tools_help_without_optional_models(self):
        for tool in sorted(TOOLS.glob("*.py")):
            with self.subTest(tool=tool.name):
                result = subprocess.run([sys.executable, "-X", "utf8", "-I", "-B", str(tool), "--help"],
                                        capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
