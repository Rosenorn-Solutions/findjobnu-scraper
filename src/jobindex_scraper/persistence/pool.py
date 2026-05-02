from __future__ import annotations

from contextlib import contextmanager
from importlib import import_module
from typing import Any, Iterator


class PersistenceConfigurationError(RuntimeError):
    pass


class MissingDependencyError(RuntimeError):
    pass


def connect(database_url: str) -> Any:
    pyodbc = _import_pyodbc()
    return pyodbc.connect(database_url)


@contextmanager
def connection_context(database_url: str) -> Iterator[Any]:
    connection = connect(database_url)
    try:
        yield connection
    finally:
        connection.close()


def _import_pyodbc() -> Any:
    try:
        return import_module("pyodbc")
    except ImportError as error:
        raise MissingDependencyError(
            "pyodbc is required for MSSQL persistence. Install project dependencies and a SQL Server ODBC driver first."
        ) from error