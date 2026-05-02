from __future__ import annotations

import unittest
from unittest.mock import patch

from jobindex_scraper.persistence import pool


class _FakePyodbc:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.connection = object()

    def connect(self, connection_string: str):
        self.calls.append(connection_string)
        return self.connection


class PersistencePoolTests(unittest.TestCase):
    def test_connect_uses_pyodbc_with_connection_string(self) -> None:
        fake_pyodbc = _FakePyodbc()
        password_placeholder = "placeholder-password"
        connection_string = ";".join(
            [
                "Driver={ODBC Driver 18 for SQL Server}",
                "Server=localhost,1433",
                "Database=jobindex_scraper",
                "Uid=sa",
                f"Pwd={password_placeholder}",
                "Encrypt=yes",
                "TrustServerCertificate=yes",
                "",
            ]
        )

        with patch.object(pool, "_import_pyodbc", return_value=fake_pyodbc):
            connection = pool.connect(connection_string)

        self.assertIs(connection, fake_pyodbc.connection)
        self.assertEqual(fake_pyodbc.calls, [connection_string])

    def test_import_error_message_mentions_mssql(self) -> None:
        with patch.object(pool, "import_module", side_effect=ImportError("missing pyodbc")):
            with self.assertRaises(pool.MissingDependencyError) as raised:
                pool._import_pyodbc()

        self.assertIn("pyodbc is required for MSSQL persistence", str(raised.exception))

    def test_import_error_mentions_unixodbc_when_runtime_library_is_missing(self) -> None:
        import_error = ImportError("libodbc.so.2: cannot open shared object file")

        with patch.object(pool, "import_module", side_effect=import_error):
            with self.assertRaises(pool.MissingDependencyError) as raised:
                pool._import_pyodbc()

        message = str(raised.exception)
        self.assertIn("unixODBC runtime is missing", message)
        self.assertIn("msodbcsql18", message)


if __name__ == "__main__":
    unittest.main()