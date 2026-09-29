"""
conftest.py (raíz)
Instala un cx_Oracle falso en sys.modules antes de que pytest recolecte
cualquier test, para poder importar db.connection sin Oracle Instant Client.
"""
import sys
import types
from unittest.mock import MagicMock


def _install_fake_cx_oracle() -> None:
    if "cx_Oracle" in sys.modules:
        return

    fake = types.ModuleType("cx_Oracle")
    fake.init_oracle_client = lambda lib_dir=None, **kwargs: None
    fake.makedsn = lambda host, port, service_name=None, **kwargs: f"{host}:{port}/{service_name}"
    fake.connect = MagicMock(name="cx_Oracle.connect")
    fake.Connection = MagicMock(name="cx_Oracle.Connection")
    fake.DatabaseError = Exception
    fake.Error = Exception
    sys.modules["cx_Oracle"] = fake


_install_fake_cx_oracle()
