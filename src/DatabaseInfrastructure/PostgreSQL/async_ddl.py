# async_ddl.py
"""
DDL (schema / table / column / constraint management).

PostgresDDL — async PostgreSQL Data Definition Module. Composes a
PostgresConnectionManager for all engine access.

Security note: PostgreSQL doesn't support bound parameters for identifiers
(schema/table/column/constraint names) or type names, so every one of
those accepted here is whitelist-validated via `validate_identifier` /
`validate_pg_type_literal` BEFORE it's interpolated into a DDL string.
DEFAULT values go through `render_default_literal` for the same reason —
the original code emitted `DEFAULT {value}` unquoted, which was both
broken for string defaults and an injection point.
"""

from __future__ import annotations

from typing import Any, Optional, Type, Union

from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncEngine

from .async_connection import PostgresConnectionManager,retry
from .post_utility import (
    PG_TO_PY,
    PY_TO_PG,
    PostgresComponentBase,
    render_default_literal,
    validate_identifier,
    validate_pg_type_literal,
)

_VALID_FK_ACTIONS = {"NO ACTION", "RESTRICT", "CASCADE", "SET NULL", "SET DEFAULT"}


class PostgresDDL(PostgresComponentBase):
    """
    Async PostgreSQL Data Definition Module.
    """

    def __init__(
        self,
        manager: PostgresConnectionManager,
        logger: Optional[Any] = None,
    ) -> None:
        super().__init__(manager, logger)
        self.logger.info("PostgresDDL initialized")


    # ─── Factory ────────────────────────────────────────────────────────────

    @classmethod
    async def init_class(
        cls,
        manager: PostgresConnectionManager,
        logger: Optional[Any] = None,
    ) -> "PostgresDDL":
        """Factory — mirrors PostgresDML / PostgresConnectionManager init_class pattern."""
        instance = cls(manager=manager, logger=logger)
        return instance

    
    # ─── Static Type Converters ────────────────────────────────────────────
    @staticmethod
    def convert_data_type_from_pg_to_py(data_type: str) -> Type:
        normalized = data_type.lower().strip()
        py_type = PG_TO_PY.get(normalized)
        if py_type is None:
            raise ValueError(f"Unknown PostgreSQL data type: {data_type}")
        return py_type

    @staticmethod
    def convert_data_type_from_py_to_pg(data_type: Union[str, Type]) -> str:
        if isinstance(data_type, str):
            # Raw type strings are whitelist-validated before use in DDL —
            # this is the one place a caller could otherwise smuggle SQL
            # through a "type name" (e.g. "VARCHAR(255); DROP TABLE ...").
            return validate_pg_type_literal(data_type)
        pg_type = PY_TO_PG.get(data_type)
        if pg_type is None:
            raise ValueError(f"Unsupported Python type for PostgreSQL: {data_type}")
        return pg_type

    # ─── Private Helpers ───────────────────────────────────────────────────
    async def _execute_ddl(self, stmt: TextClause, engine: Optional[AsyncEngine] = None) -> None:
        target_engine = engine or self._manager.get_engine()
        async with target_engine.begin() as conn:
            await conn.execute(stmt)

    async def _constraint_exists(
        self, schema_name: str, table_name: str, constraint_name: str
    ) -> bool:
        """Backs the idempotency checks in the constraint methods below."""
        stmt = text(
            """
            SELECT 1
            FROM pg_constraint c
            JOIN pg_namespace n ON n.oid = c.connamespace
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE n.nspname = :schema
              AND t.relname = :table
              AND c.conname = :constraint
            """
        )
        async with self._manager.get_engine().connect() as conn:
            result = await conn.execute(
                stmt,
                {"schema": schema_name, "table": table_name, "constraint": constraint_name},
            )
            return result.scalar() is not None

    async def _column_is_not_null(
        self, schema_name: str, table_name: str, column_name: str
    ) -> bool:
        stmt = text(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = :schema
              AND table_name = :table
              AND column_name = :column
            """
        )
        async with self._manager.get_engine().connect() as conn:
            result = await conn.execute(
                stmt, {"schema": schema_name, "table": table_name, "column": column_name}
            )
            row = result.fetchone()
        return bool(row) and row[0] == "NO"

    # ═══════════════════════════════════════════════════════════════════════
    # DATABASE LEVEL OPERATIONS (temp engine — NOT decorated with @retry())
    # ═══════════════════════════════════════════════════════════════════════

    async def create_database(self, root_username: str, root_password: str, db_name: str) -> bool:
        validate_identifier(db_name, label="db_name")
        temp_engine = None
        try:
            temp_engine = self._manager.build_temp_engine(root_username, root_password, "postgres")
            self.logger.info(f"Creating database '{db_name}'")

            check_stmt = text("SELECT 1 FROM pg_database WHERE datname = :db_name")
            async with temp_engine.connect() as conn:
                result = await conn.execute(check_stmt, {"db_name": db_name})
                exists = result.scalar() is not None

            if exists:
                self.logger.warning(f"Database '{db_name}' already exists")
                return False

            create_stmt = text(f'CREATE DATABASE "{db_name}"')
            self.debug_statement(create_stmt, operation="CREATE DATABASE", table_name=db_name, log_params=False)

            async with temp_engine.begin() as conn:
                await conn.execute(create_stmt)

            self.logger.info(f"Database '{db_name}' created successfully")
            return True
        except Exception as e:
            self.logger.exception(f"Failed to create database '{db_name}': {e}")
            raise
        finally:
            if temp_engine:
                await temp_engine.dispose()

    async def drop_database(self, root_username: str, root_password: str, db_name: str) -> bool:
        validate_identifier(db_name, label="db_name")
        temp_engine = None
        try:
            temp_engine = self._manager.build_temp_engine(root_username, root_password, "postgres")
            self.logger.info(f"Dropping database '{db_name}'")

            check_stmt = text("SELECT 1 FROM pg_database WHERE datname = :db_name")
            async with temp_engine.connect() as conn:
                result = await conn.execute(check_stmt, {"db_name": db_name})
                exists = result.scalar() is not None

            if not exists:
                self.logger.warning(f"Database '{db_name}' does not exist")
                return False

            terminate_stmt = text(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = :db_name AND pid <> pg_backend_pid()
                """
            )
            self.debug_statement(terminate_stmt, operation="TERMINATE CONNECTIONS", table_name=db_name)

            async with temp_engine.begin() as conn:
                await conn.execute(terminate_stmt, {"db_name": db_name})

            drop_stmt = text(f'DROP DATABASE IF EXISTS "{db_name}"')
            self.debug_statement(drop_stmt, operation="DROP DATABASE", table_name=db_name, log_params=False)

            async with temp_engine.begin() as conn:
                await conn.execute(drop_stmt)

            self.logger.info(f"Database '{db_name}' dropped successfully")
            return True
        except Exception as e:
            self.logger.exception(f"Failed to drop database '{db_name}': {e}")
            raise
        finally:
            if temp_engine:
                await temp_engine.dispose()

    # ═══════════════════════════════════════════════════════════════════════
    # SCHEMA LEVEL OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════

    async def _create_schema_impl(self, schema_name: str) -> bool:
        """
        Undecorated impl, called directly by other DDL methods (e.g.
        create_table) that already carry their own @retry() — this
        avoids the nested-retry multiplication that would happen if two
        decorated layers both retried independently on the same failure.
        """
        validate_identifier(schema_name, label="schema_name")
        stmt = text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')
        self.debug_statement(stmt, operation="CREATE SCHEMA", table_name=schema_name, log_params=False)
        await self._execute_ddl(stmt)
        self.logger.info(f"Schema '{schema_name}' ensured")
        return True

    @retry()
    async def create_schema(self, schema_name: str) -> bool:
        return await self._create_schema_impl(schema_name)

    @retry()
    async def drop_schema(self, schema_name: str, cascade: bool = False) -> bool:
        validate_identifier(schema_name, label="schema_name")
        cascade_str = "CASCADE" if cascade else ""
        stmt = text(f'DROP SCHEMA IF EXISTS "{schema_name}" {cascade_str}')
        self.debug_statement(stmt, operation="DROP SCHEMA", table_name=schema_name, log_params=False)
        await self._execute_ddl(stmt)
        self.logger.info(f"Schema '{schema_name}' dropped (cascade={cascade})")
        return True

    # ═══════════════════════════════════════════════════════════════════════
    # TABLE LEVEL OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════

    @retry()
    async def create_table(self, schema_name: str, table_name: str, pk_name: str = "id") -> bool:
        validate_identifier(schema_name, label="schema_name")
        validate_identifier(table_name, label="table_name")
        validate_identifier(pk_name, label="pk_name")

        # Calls the undecorated impl directly (see _create_schema_impl's
        # docstring) so a transient connection failure retries only once
        # overall, via this method's own decorator.
        await self._create_schema_impl(schema_name)

        stmt = text(
            f'CREATE TABLE IF NOT EXISTS "{schema_name}"."{table_name}" ('
            f'"{pk_name}" BIGSERIAL PRIMARY KEY'
            f')'
        )
        self.debug_statement(
            stmt,
            operation="CREATE TABLE",
            table_name=f"{schema_name}.{table_name}",
            log_params=False,
        )
        await self._execute_ddl(stmt)
        self.logger.info(f"Table '{schema_name}.{table_name}' created with PK '{pk_name}'")
        return True

    @retry()
    async def drop_table(self, schema_name: str, table_name: str) -> bool:
        validate_identifier(schema_name, label="schema_name")
        validate_identifier(table_name, label="table_name")
        stmt = text(f'DROP TABLE IF EXISTS "{schema_name}"."{table_name}"')
        self.debug_statement(
            stmt,
            operation="DROP TABLE",
            table_name=f"{schema_name}.{table_name}",
            log_params=False,
        )
        await self._execute_ddl(stmt)
        self.logger.info(f"Table '{schema_name}.{table_name}' dropped")
        return True

    # ═══════════════════════════════════════════════════════════════════════
    # COLUMN LEVEL OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════

    @retry()
    async def create_column(
        self,
        schema_name: str,
        table_name: str,
        column_name: str,
        data_type: Union[str, Type],
        nullable: bool = True,
        default: Optional[Any] = None,
    ) -> bool:
        validate_identifier(schema_name, label="schema_name")
        validate_identifier(table_name, label="table_name")
        validate_identifier(column_name, label="column_name")

        pg_type = self.convert_data_type_from_py_to_pg(data_type)
        nullable_str = "" if nullable else "NOT NULL"
        default_str = render_default_literal(default)

        stmt = text(
            f'ALTER TABLE "{schema_name}"."{table_name}" '
            f'ADD COLUMN IF NOT EXISTS "{column_name}" {pg_type} {default_str} {nullable_str}'
        )
        self.debug_statement(
            stmt,
            operation="ADD COLUMN",
            table_name=f"{schema_name}.{table_name}",
            log_params=False,
        )
        await self._execute_ddl(stmt)
        self.logger.info(f"Column '{column_name}' ({pg_type}) added to '{schema_name}.{table_name}'")
        return True

    @retry()
    async def drop_column(self, schema_name: str, table_name: str, column_name: str) -> bool:
        validate_identifier(schema_name, label="schema_name")
        validate_identifier(table_name, label="table_name")
        validate_identifier(column_name, label="column_name")
        stmt = text(
            f'ALTER TABLE "{schema_name}"."{table_name}" '
            f'DROP COLUMN IF EXISTS "{column_name}"'
        )
        self.debug_statement(
            stmt,
            operation="DROP COLUMN",
            table_name=f"{schema_name}.{table_name}",
            log_params=False,
        )
        await self._execute_ddl(stmt)
        self.logger.info(f"Column '{column_name}' dropped from '{schema_name}.{table_name}'")
        return True

    # ═══════════════════════════════════════════════════════════════════════
    # CONSTRAINT LEVEL OPERATIONS  (idempotent — Phase 2, §3.7)
    # ═══════════════════════════════════════════════════════════════════════

    @retry()
    async def create_not_null_constraint(
        self,
        constraint_name: str,
        schema_name: str,
        table_name: str,
        column_name: str,
    ) -> bool:
        """
        NOTE: PostgreSQL has no named constraint object for NOT NULL —
        `constraint_name` is used only for logging, kept for signature
        consistency with the other constraint methods below.
        """
        validate_identifier(schema_name, label="schema_name")
        validate_identifier(table_name, label="table_name")
        validate_identifier(column_name, label="column_name")

        if await self._column_is_not_null(schema_name, table_name, column_name):
            self.logger.warning(
                f"Column '{schema_name}.{table_name}.{column_name}' is already NOT NULL — skipping"
            )
            return False

        stmt = text(
            f'ALTER TABLE "{schema_name}"."{table_name}" '
            f'ALTER COLUMN "{column_name}" SET NOT NULL'
        )
        self.debug_statement(
            stmt,
            operation=f"SET NOT NULL [{constraint_name}]",
            table_name=f"{schema_name}.{table_name}",
            log_params=False,
        )
        await self._execute_ddl(stmt)
        self.logger.info(
            f"NOT NULL applied to '{schema_name}.{table_name}.{column_name}' "
            f"(constraint name: '{constraint_name}')"
        )
        return True

    @retry()
    async def drop_not_null_constraint(
        self,
        schema_name: str,
        table_name: str,
        column_name: str,
    ) -> bool:
        validate_identifier(schema_name, label="schema_name")
        validate_identifier(table_name, label="table_name")
        validate_identifier(column_name, label="column_name")
        stmt = text(
            f'ALTER TABLE "{schema_name}"."{table_name}" '
            f'ALTER COLUMN "{column_name}" DROP NOT NULL'
        )
        self.debug_statement(
            stmt,
            operation="DROP NOT NULL",
            table_name=f"{schema_name}.{table_name}",
            log_params=False,
        )
        await self._execute_ddl(stmt)
        self.logger.info(f"NOT NULL dropped from '{schema_name}.{table_name}.{column_name}'")
        return True

    @retry()
    async def create_unique_constraint(
        self,
        constraint_name: str,
        schema_name: str,
        table_name: str,
        column_name: str,
    ) -> bool:
        validate_identifier(constraint_name, label="constraint_name")
        validate_identifier(schema_name, label="schema_name")
        validate_identifier(table_name, label="table_name")
        validate_identifier(column_name, label="column_name")

        if await self._constraint_exists(schema_name, table_name, constraint_name):
            self.logger.warning(
                f"Constraint '{constraint_name}' already exists on "
                f"'{schema_name}.{table_name}' — skipping"
            )
            return False

        stmt = text(
            f'ALTER TABLE "{schema_name}"."{table_name}" '
            f'ADD CONSTRAINT "{constraint_name}" UNIQUE ("{column_name}")'
        )
        self.debug_statement(
            stmt,
            operation="ADD UNIQUE",
            table_name=f"{schema_name}.{table_name}",
            log_params=False,
        )
        await self._execute_ddl(stmt)
        self.logger.info(
            f"UNIQUE constraint '{constraint_name}' added to "
            f"'{schema_name}.{table_name}.{column_name}'"
        )
        return True

    @retry()
    async def create_pk_constraint(
        self,
        constraint_name: str,
        schema_name: str,
        table_name: str,
        column_name: str,
    ) -> bool:
        validate_identifier(constraint_name, label="constraint_name")
        validate_identifier(schema_name, label="schema_name")
        validate_identifier(table_name, label="table_name")
        validate_identifier(column_name, label="column_name")

        if await self._constraint_exists(schema_name, table_name, constraint_name):
            self.logger.warning(
                f"Constraint '{constraint_name}' already exists on "
                f"'{schema_name}.{table_name}' — skipping"
            )
            return False

        stmt = text(
            f'ALTER TABLE "{schema_name}"."{table_name}" '
            f'ADD CONSTRAINT "{constraint_name}" PRIMARY KEY ("{column_name}")'
        )
        self.debug_statement(
            stmt,
            operation="ADD PRIMARY KEY",
            table_name=f"{schema_name}.{table_name}",
            log_params=False,
        )
        await self._execute_ddl(stmt)
        self.logger.info(
            f"PK constraint '{constraint_name}' added to "
            f"'{schema_name}.{table_name}.{column_name}'"
        )
        return True

    @retry()
    async def create_fk_constraint(
        self,
        constraint_name: str,
        schema_name: str,
        table_name: str,
        column_name: str,
        references_column: str,
        references_table: str,
        references_schema: str,
        on_delete: str = "NO ACTION",
        on_update: str = "NO ACTION",
    ) -> bool:
        validate_identifier(constraint_name, label="constraint_name")
        validate_identifier(schema_name, label="schema_name")
        validate_identifier(table_name, label="table_name")
        validate_identifier(column_name, label="column_name")
        validate_identifier(references_column, label="references_column")
        validate_identifier(references_table, label="references_table")
        validate_identifier(references_schema, label="references_schema")

        # `on_delete` / `on_update` were previously interpolated straight
        # into the DDL string with no validation at all — same bug class
        # as the identifier issue, just missed in the first pass. Whitelist
        # them against the fixed set of actions Postgres actually supports.
        on_delete_norm = on_delete.strip().upper()
        on_update_norm = on_update.strip().upper()
        if on_delete_norm not in _VALID_FK_ACTIONS or on_update_norm not in _VALID_FK_ACTIONS:
            raise ValueError(
                f"on_delete/on_update must be one of {sorted(_VALID_FK_ACTIONS)}, "
                f"got on_delete={on_delete!r}, on_update={on_update!r}"
            )

        if await self._constraint_exists(schema_name, table_name, constraint_name):
            self.logger.warning(
                f"Constraint '{constraint_name}' already exists on "
                f"'{schema_name}.{table_name}' — skipping"
            )
            return False

        stmt = text(
            f'ALTER TABLE "{schema_name}"."{table_name}" '
            f'ADD CONSTRAINT "{constraint_name}" '
            f'FOREIGN KEY ("{column_name}") '
            f'REFERENCES "{references_schema}"."{references_table}" ("{references_column}") '
            f'ON DELETE {on_delete_norm} ON UPDATE {on_update_norm}'
        )
        self.debug_statement(
            stmt,
            operation="ADD FOREIGN KEY",
            table_name=f"{schema_name}.{table_name}",
            log_params=False,
        )
        await self._execute_ddl(stmt)
        self.logger.info(
            f"FK constraint '{constraint_name}' added: "
            f"'{schema_name}.{table_name}.{column_name}' -> "
            f"'{references_schema}.{references_table}.{references_column}'"
        )
        return True

    @retry()
    async def drop_constraint(
        self,
        constraint_name: str,
        schema_name: str,
        table_name: str,
    ) -> bool:
        validate_identifier(constraint_name, label="constraint_name")
        validate_identifier(schema_name, label="schema_name")
        validate_identifier(table_name, label="table_name")
        stmt = text(
            f'ALTER TABLE "{schema_name}"."{table_name}" '
            f'DROP CONSTRAINT IF EXISTS "{constraint_name}"'
        )
        self.debug_statement(
            stmt,
            operation="DROP CONSTRAINT",
            table_name=f"{schema_name}.{table_name}",
            log_params=False,
        )
        await self._execute_ddl(stmt)
        self.logger.info(f"Constraint '{constraint_name}' dropped from '{schema_name}.{table_name}'")
        return True

    # ═══════════════════════════════════════════════════════════════════════
    # INTROSPECTION
    # ═══════════════════════════════════════════════════════════════════════

    @retry()
    async def get_column_data_type(
        self,
        schema_name: str,
        table_name: str,
        column_name: str,
    ) -> str:
        validate_identifier(schema_name, label="schema_name")
        validate_identifier(table_name, label="table_name")
        validate_identifier(column_name, label="column_name")

        stmt = text(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = :schema
              AND table_name = :table
              AND column_name = :column
            """
        )
        self.debug_statement(
            stmt,
            operation="GET COLUMN DATA TYPE",
            table_name=f"{schema_name}.{table_name}",
        )
        async with self._manager.get_engine().connect() as conn:
            result = await conn.execute(
                stmt,
                {"schema": schema_name, "table": table_name, "column": column_name},
            )
            row = result.fetchone()

        if not row:
            raise ValueError(f"Column '{column_name}' not found in '{schema_name}.{table_name}'")

        pg_type = row[0]
        self.logger.info(f"Column '{schema_name}.{table_name}.{column_name}' has type '{pg_type}'")
        return pg_type
    



    