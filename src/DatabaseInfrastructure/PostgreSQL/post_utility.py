# utility.py
"""
Shared helpers for the async PostgreSQL layer.

  * validate_identifier       — whitelist-validates identifiers (schema/table/
                                 column/constraint names) before they're
                                 interpolated into raw SQL text.
  * render_default_literal    — safely renders a Python value as a SQL
                                 `DEFAULT ...` clause fragment.
  * validate_pg_type_literal  — whitelist-validates a raw PostgreSQL type
                                 string (e.g. "VARCHAR(255)") before it's
                                 used in DDL.
  * PostgresUtility           — houses the `try_reconnect` retry decorator
                                 and the PG <-> Python type-mapping tables.
  * PostgresComponentBase     — shared base class for PostgresDDL and
                                 PostgresDML (logger, debug_statement,
                                 async context-manager plumbing).

`PostgresUtalitiy` (the original, misspelled class name) is kept as a
deprecated alias so existing imports keep working during migration.
"""

from __future__ import annotations

import functools
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Optional, Protocol, Type, Union, runtime_checkable
from uuid import UUID

import loguru
from sqlalchemy import Executable, TextClause
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
import numpy as np
import pandas as pd
# ═══════════════════════════════════════════════════════════════════════════
# VALIDATION HELPERS  (Phase 1 — security & correctness)
# ═══════════════════════════════════════════════════════════════════════════

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_IDENTIFIER_LENGTH = 63  # PostgreSQL's NAMEDATALEN limit (minus 1)

_PG_TYPE_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_ ]{0,29}"              # base type name, e.g. "VARCHAR", "DOUBLE PRECISION"
    r"(\(\s*\d{1,10}(\s*,\s*\d{1,10})?\s*\))?"    # optional (n) or (n,m)
    r"(\[\])?$"                                    # optional array suffix, e.g. "INTEGER[]"
)


def validate_identifier(name: str, *, label: str = "identifier") -> str:
    """
    Whitelist-validate a PostgreSQL identifier (schema, table, column, or
    constraint name) before it is interpolated into an f-string DDL
    statement. Raises ValueError on anything that isn't a plain ASCII
    word starting with a letter or underscore.

    This exists because identifiers can't be passed as bound SQL
    parameters — they must be validated (or properly quoted) manually.
    """
    if not isinstance(name, str) or not name:
        raise ValueError(f"Invalid {label}: expected a non-empty string, got {name!r}")
    if len(name) > _MAX_IDENTIFIER_LENGTH:
        raise ValueError(
            f"Invalid {label}: {name!r} exceeds PostgreSQL's "
            f"{_MAX_IDENTIFIER_LENGTH}-character identifier limit"
        )
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(
            f"Invalid {label}: {name!r}. Only letters, digits, and underscores "
            "are allowed, and it must start with a letter or underscore."
        )
    return name


def render_default_literal(value: Any) -> str:
    """
    Safely render a Python value as a SQL `DEFAULT ...` clause fragment.
    Returns an empty string when `value` is None (i.e. no DEFAULT clause
    should be emitted at all).
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "DEFAULT TRUE" if value else "DEFAULT FALSE"
    if isinstance(value, (int, float)):
        return f"DEFAULT {value}"
    # Strings, dates, etc. — render as a quoted string literal, escaping
    # embedded single quotes so it can't break out of the literal.
    escaped = str(value).replace("'", "''")
    return f"DEFAULT '{escaped}'"


def validate_pg_type_literal(type_str: str) -> str:
    """
    Whitelist-validate a raw PostgreSQL type string (e.g. "VARCHAR(255)",
    "NUMERIC(10,2)", "INTEGER[]") before it is used in DDL. Returns the
    upper-cased, whitespace-normalized type string.
    """
    if not isinstance(type_str, str) or not type_str.strip():
        raise ValueError(f"Invalid PostgreSQL type: expected a non-empty string, got {type_str!r}")
    candidate = " ".join(type_str.strip().upper().split())
    if not _PG_TYPE_RE.match(candidate):
        raise ValueError(f"Refusing to use unvalidated PostgreSQL type string: {type_str!r}")
    return candidate




# ═══════════════════════════════════════════════════════════════════════════
# RETRY DECORATOR + TYPE MAPPINGS
# ═══════════════════════════════════════════════════════════════════════════

class PostgresUtility:
    """
    Module-level decorator + shared type-mapping tables for PostgresDDL and
    PostgresDML.
    """

    @staticmethod
    def try_reconnect(func):
        """
        Catches OperationalError / InterfaceError, triggers self.reconnect(),
        and retries the wrapped method ONCE.

        This decorator is the SOLE owner of connection-failure logging for
        any method it wraps — wrapped methods should not also log the same
        exception themselves. They may still do local cleanup (e.g.
        `await session.rollback()`) in their own try/except before
        re-raising; that's not duplication, it's necessary cleanup.
        """

        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            self.logger.debug(
                f"Entering '{func.__name__}' with args={args}, kwargs={kwargs}"
            )
            try:
                return await func(self, *args, **kwargs)

            except (OperationalError, InterfaceError) as e:
                error_name = type(e).__name__
                self.logger.exception(f"{error_name} in '{func.__name__}': {e}")
                self.logger.warning(
                    f"Reconnecting and retrying '{func.__name__}' once due to {error_name}"
                )
                try:
                    await self.reconnect()
                    result = await func(self, *args, **kwargs)
                    self.logger.info(
                        f"Retry succeeded for '{func.__name__}' after {error_name}"
                    )
                    return result
                except Exception as retry_e:
                    self.logger.exception(
                        f"Retry failed in '{func.__name__}' after reconnect: {retry_e}"
                    )
                    raise

            except IntegrityError as e:
                self.logger.exception(f"IntegrityError in '{func.__name__}': {e}")
                raise

            except Exception as e:
                self.logger.exception(f"Unexpected error in '{func.__name__}': {e}")
                raise

        return wrapper


    PG_TO_PY: Dict[str, Type] = {
        "integer": int,
        "bigint": int,
        "smallint": int,
        "serial": int,
        "bigserial": int,
        "smallserial": int,
        "character varying": str,
        "varchar": str,
        "text": str,
        "character": str,
        "char": str,
        "boolean": bool,
        "bool": bool,
        "double precision": float,
        "real": float,
        "numeric": float,
        "decimal": float,
        "money": float,
        "timestamp without time zone": datetime,
        "timestamp with time zone": datetime,
        "timestamp": datetime,
        "date": date,
        "time without time zone": time,
        "time with time zone": time,
        "time": time,
        "interval": timedelta,
        "json": dict,
        "jsonb": dict,
        "uuid": UUID,
        "bytea": bytes,
        "inet": str,
        "cidr": str,
        "macaddr": str,
        "xml": str,
        "array": list,
    }

    PY_TO_PG: Dict[Type, str] = {
        int: "INTEGER",
        str: "TEXT",
        bool: "BOOLEAN",
        float: "DOUBLE PRECISION",
        datetime: "TIMESTAMP",
        date: "DATE",
        time: "TIME",
        timedelta: "INTERVAL",
        dict: "JSONB",
        list: "JSONB",
        UUID: "UUID",
        bytes: "BYTEA",

        pd.Int8Dtype: "SMALLINT",
        pd.Int16Dtype: "SMALLINT",
        pd.Int32Dtype: "INTEGER",
        pd.Int64Dtype: "BIGINT",
        pd.UInt8Dtype: "SMALLINT",
        pd.UInt16Dtype: "INTEGER",
        pd.UInt32Dtype: "BIGINT",
        pd.UInt64Dtype: "NUMERIC",
        pd.Float32Dtype: "REAL",
        pd.Float64Dtype: "DOUBLE PRECISION",
        pd.BooleanDtype: "BOOLEAN",
        pd.StringDtype: "TEXT",

        np.int8: "SMALLINT",
        np.int16: "SMALLINT",
        np.int32: "INTEGER",
        np.int64: "BIGINT",
        np.uint8: "SMALLINT",
        np.uint16: "INTEGER",
        np.uint32: "BIGINT",
        np.uint64: "BIGINT",  
        np.float16: "REAL",
        np.float32: "REAL",
        np.float64: "DOUBLE PRECISION",
        np.bool_: "BOOLEAN",
        np.str_: "TEXT",
        np.bytes_: "BYTEA",
        np.datetime64: "TIMESTAMP",
        np.timedelta64: "INTERVAL",
}

    


# for easy import 
try_reconnect=PostgresUtility.try_reconnect
PG_TO_PY=PostgresUtility.PG_TO_PY
PY_TO_PG=PostgresUtility.PY_TO_PG


# ═══════════════════════════════════════════════════════════════════════════
# SHARED COMPONENT BASE  (Phase 3 — de-duplicates PostgresDDL / PostgresDML)
# ═══════════════════════════════════════════════════════════════════════════

class PostgresComponentBase:
    """
    Shared base for PostgresDDL and PostgresDML: logger setup, SQL-debug
    logging, and async context-manager plumbing. Subclasses compose a
    `ConnectionManagerLike` for all engine access.
    """

    def __init__(
        self,
        manager: ConnectionManagerLike,
        logger: Optional[Any] = None,
    ) -> None:
        self._manager = manager
        self.logger = logger if logger is not None else loguru.logger

    async def reconnect(self) -> None:
        """Delegate reconnect to the connection manager."""
        await self._manager.reconnect()

    async def __aenter__(self) -> "PostgresComponentBase":
        self.logger.debug(f"Entering async context manager for {type(self).__name__}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type:
            self.logger.exception(
                f"Exception inside async context manager: {exc_type.__name__}: {exc_val}"
            )

    def debug_statement(
        self,
        stmt: Union[Executable, TextClause],
        *,
        operation: Optional[str] = None,
        table_name: Optional[str] = None,
        log_params: bool = True,
    ) -> None:
        try:
            compiled = stmt.compile()
            self.logger.debug("=" * 80)
            if operation:
                self.logger.debug("Operation : {}", operation)
            if table_name:
                self.logger.debug("Table     : {}", table_name)
            self.logger.debug("Statement :\n{}", compiled)
            if log_params:
                self.logger.debug("Parameters:\n{}", compiled.params)
            self.logger.debug("=" * 80)
        except Exception:
            self.logger.exception("Failed to compile SQLAlchemy statement.")



            