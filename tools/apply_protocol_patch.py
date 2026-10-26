"""Apply the pinned ArticProtocol transport fix before building either server."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
protocol = root / "plugin/ArticProtocol"
patch = root / "patches/ArticProtocol.patch"
subprocess.run(["git", "-C", str(root), "submodule", "update", "--init", "--recursive"], check=True)
command = ["git", "-C", str(protocol), "apply"]
if subprocess.run([*command, "--reverse", "--check", str(patch)], capture_output=True).returncode == 0:
    print("ArticProtocol transport fix already applied")
else:
    subprocess.run([*command, "--check", str(patch)], check=True)
    subprocess.run([*command, str(patch)], check=True)
    print("ArticProtocol transport fix applied")
