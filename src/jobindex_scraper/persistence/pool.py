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
        raise MissingDependencyError(_missing_dependency_message(error)) from error


def _missing_dependency_message(error: ImportError) -> str:
    error_text = str(error)
    if "libodbc.so.2" in error_text:
        return (
            "pyodbc is installed, but the unixODBC runtime is missing "
            "(libodbc.so.2). On Ubuntu install unixodbc and the SQL Server "
            "ODBC driver package such as msodbcsql18, then retry."
        )
    return (
        "pyodbc is required for MSSQL persistence. Install project dependencies "
        "and the system ODBC runtime/SQL Server driver first."
    )