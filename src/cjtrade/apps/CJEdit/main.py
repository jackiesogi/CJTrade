import sys
import tempfile
from pathlib import Path

from cjtrade.apps.CJEdit.editor import CJEditor
from cjtrade.apps.CJEdit.template import get_general_import_str
from cjtrade.pkgs.logger import get_console
from cjtrade.pkgs.logger import get_logger
from cjtrade.pkgs.logger import setup_logging
from cjtrade.pkgs.ui.engine import FormEngine

BASE_DIR = Path(__file__).resolve().parent

setup_logging()
log = get_logger("CJEdit")
out = get_console("CJEdit")

index = FormEngine(
    schema_path=BASE_DIR / "pages" / "index.toml",
    renderer="cli",
)

tmp_file = tempfile.NamedTemporaryFile(
    delete=False, suffix=".py", prefix="cjedit_"
)
file = tmp_file.name
result = index.run()
log.info("form result: %s", result)
import_str = get_general_import_str(broker=result["broker"],
                                    arenax_backend=result["backend_selection"])
editor = CJEditor(app=result["app"], file=file, template_str=import_str)
editor.run()

# This interpreter, so the command works wherever cjtrade is installed.
out.info(f"""\
Run your strategy with:
{sys.executable} {file}
""")
