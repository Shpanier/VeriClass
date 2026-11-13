"""Test setup shared by every test module: the exercise packages come from a
throwaway copy of tests/fixtures/data, never from the lecturer's private
../VeriClassPrivateData. Runs before any test module imports backend (which reads
VERICLASS_DATA_DIR at import time)."""
import os
import shutil
import tempfile
from pathlib import Path

_FIXTURE = Path(__file__).parent / "fixtures" / "data"
_DATA = Path(tempfile.mkdtemp(prefix="vericlass-data-")) / "data"
shutil.copytree(_FIXTURE, _DATA)
os.environ["VERICLASS_DATA_DIR"] = str(_DATA)

# The settings page writes the API key to .env: tests get a throwaway file.
os.environ["VERICLASS_ENV_FILE"] = str(_DATA.parent / "test.env")
