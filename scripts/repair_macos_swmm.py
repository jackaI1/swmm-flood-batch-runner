"""Repair invalid signatures in the installed SWMM wheel on macOS only.

Some arm64 wheels contain dylibs changed after signing. This checks each
bundled dylib and ad-hoc signs a private copy only when verification fails.
No system libraries or security settings are changed. Run before importing
PySWMM if Python is killed on import. It is safe to run on Linux (a no-op).
"""

from importlib.util import find_spec
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    if sys.platform != "darwin":
        print("No macOS wheel repair needed on this platform")
        return
    spec = find_spec("swmm")
    if spec is None:
        raise SystemExit("Install the project dependencies first")
    repaired = 0
    for root in spec.submodule_search_locations:
        for library in sorted((Path(root) / "toolkit").glob("*.dylib")):
            verified = subprocess.run(["codesign", "--verify", str(library)], capture_output=True)
            if verified.returncode == 0:
                continue
            # Break uv's cache hardlink before changing any wheel content.
            fd, name = tempfile.mkstemp(suffix=".dylib", dir=library.parent)
            os.close(fd)
            temporary = Path(name)
            try:
                shutil.copy2(library, temporary)
                subprocess.run(["codesign", "--force", "--sign", "-", str(temporary)],
                               check=True, capture_output=True)
                subprocess.run(["codesign", "--verify", str(temporary)], check=True, capture_output=True)
                temporary.replace(library)
            finally:
                temporary.unlink(missing_ok=True)
            repaired += 1
            print(f"Repaired installed wheel library: {library.name}")
    print(f"SWMM wheel signatures checked; repaired {repaired} libraries")


if __name__ == "__main__":
    main()
