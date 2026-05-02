from __future__ import annotations

import os
import unittest


class MssqlPersistenceIntegrationTests(unittest.TestCase):
    def test_live_mssql_target_is_reachable(self) -> None:
        connection_string = os.getenv("JOBINDEX_SCRAPER_TEST_DATABASE_URL")
        if not connection_string:
            raise unittest.SkipTest(
                "Set JOBINDEX_SCRAPER_TEST_DATABASE_URL to run the live MSSQL integration smoke test."
            )

        try:
            import pyodbc
        except ImportError as error:
            raise unittest.SkipTest("pyodbc is not installed in the active environment.") from error

        connection = pyodbc.connect(connection_string)
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
        finally:
            connection.close()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(int(row[0]), 1)


if __name__ == "__main__":
    unittest.main()