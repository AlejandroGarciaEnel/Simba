"""
conftest.py (raíz)
Instala un oracledb falso en sys.modules antes de que pytest recolecte
cualquier test, para poder importar db.connection sin driver ni Oracle Client.
"""
import sys
import types
from unittest.mock import MagicMock


def _install_fake_oracledb() -> None:
    if "oracledb" in sys.modules:
        return

    fake = types.ModuleType("oracledb")
    fake.init_oracle_client = lambda lib_dir=None, **kwargs: None
    fake.makedsn = lambda host, port, service_name=None, **kwargs: f"{host}:{port}/{service_name}"
    fake.connect = MagicMock(name="oracledb.connect")
    fake.Connection = MagicMock(name="oracledb.Connection")
    fake.DatabaseError = Exception
    fake.Error = Exception
    sys.modules["oracledb"] = fake


_install_fake_oracledb()
