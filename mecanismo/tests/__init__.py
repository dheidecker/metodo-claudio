# La raíz mecanismo/ en sys.path para `from lib import comun`, corra desde donde corra.
import sys, pathlib
_r = str(pathlib.Path(__file__).resolve().parent.parent)
if _r not in sys.path:
    sys.path.insert(0, _r)
