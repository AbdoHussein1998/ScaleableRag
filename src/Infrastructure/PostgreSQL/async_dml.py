# async_dml.py
"""
Async PostgreSQL Data Manipulation Layer (DML).

PostgresDML — owns the async session factory, automap reflection cache,
and all CRUD/query operations. Composes PostgresConnectionManager for
engine access and inherits shared plumbing from PostgresComponentBase.

Changes from original:
  • Inherits PostgresComponentBase (removes duplicated debug_statement,
    __aenter__/__aexit__, logger setup).
  • Inner try/except blocks now only perform rollback and re-raise;
    @retry() owns all exception-level logging.
  • Identifier validation added to public entrypoints for defense in depth.
  • Upsert support: insert_into_table / insert_into_table_bulk accept
    on_conflict="do_nothing" | "do_update".
  • Bulk insert gains commit_every_batch flag (default True) so a failure
    mid-load doesn't silently roll back already-committed work.
  • execute_custom_statement statement log downgraded from INFO to DEBUG
    to avoid leaking sensitive values into production logs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union, cast

import loguru
import pandas as pd
from sqlalchemy import inspect, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.ext.automap import automap_base
from sqlalchemy import Table
from .async_connection import PostgresConnectionManager,retry
from .post_utility import PostgresComponentBase ,validate_identifier


class PostgresDML(PostgresComponentBase):
    """
    Async PostgreSQL Data Manipulation Layer.
    Composes PostgresConnectionManager for engine access.
    Owns session factory and reflection cache.
    """

    def __init__(
        self,
        manager: PostgresConnectionManager,
        schema: str = "public",
        logger: Optional[Any] = None,
    ) -> None:
        super().__init__(manager, logger)
        self.default_schema = schema
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None
        self._bases: Dict[str, Any] = {}
        self.logger.info(f"PostgresDML initialized for schema={schema}")

    # ─── Factory ────────────────────────────────────────────────────────────
    @classmethod
    async def init_class(
        cls,
        manager: PostgresConnectionManager,
        schema: str = "public",
        logger: Optional[Any] = None,
    ) -> "PostgresDML":
        instance = cls(manager=manager, schema=schema, logger=logger)
        await instance.connect()
        return instance

    # ─── Lifecycle ──────────────────────────────────────────────────────────
    async def connect(self) -> None:
        self.logger.info("Connecting DML layer...")
        self._session_factory = self._build_async_session_factory()
        await self._reflect_default_schema()
        self.logger.info("DML layer connected and default schema reflected")

    async def close(self) -> None:
        """
        Clear DML-specific caches. Does NOT dispose the engine —
        the manager owns it.
        """
        self._session_factory = None
        self._bases = {}
        self.logger.info("DML caches cleared (engine left to manager)")

    async def __aenter__(self) -> "PostgresDML":
        self.logger.debug("Entering async context manager for PostgresDML")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await super().__aexit__(exc_type, exc_val, exc_tb)
        try:
            await self.close()
        except Exception:
            self.logger.exception("Error during DML __aexit__")
            raise

    async def reconnect(self) -> None:
        """
        Reconnect via manager, then rebuild DML-specific resources.
        """
        self.logger.warning("DML reconnect requested")
        await self._manager.reconnect()
        self._session_factory = self._build_async_session_factory()
        self._bases = {}
        self.logger.info(
            "DML reconnected: session factory rebuilt, reflection cache cleared"
        )

    def _build_async_session_factory(self) -> async_sessionmaker[AsyncSession]:
        session_factory = async_sessionmaker(
            bind=self._manager.get_engine(),
            class_=AsyncSession,
            autoflush=False,
            expire_on_commit=False,
        )
        self.logger.info("Async session factory created successfully")
        return session_factory

    # ─── Private Reflection ─────────────────────────────────────────────────
    async def _reflect_default_schema(self) -> None:
        self.logger.info(f"Reflecting default schema '{self.default_schema}'")
        await self._get_base_for_schema(self.default_schema)
        self.logger.info(f"Default schema '{self.default_schema}' reflected successfully")

    async def _get_base_for_schema(self, schema: str) -> Any:
        if schema in self._bases:
            self.logger.debug(f"Schema '{schema}' found in cache")
            return self._bases[schema]

        self.logger.info(f"Reflecting schema '{schema}'...")
        base = automap_base()

        async with self._manager.get_engine().connect() as conn:
            await conn.run_sync(
                base.prepare,
                reflect=True,
                schema=schema,
            )

        self._bases[schema] = base
        self.logger.info(f"Schema '{schema}' reflected and cached")
        return base

    # ─── Public Reflection ──────────────────────────────────────────────────
    async def reflect_all_schemas(self) -> None:
        schemas = await self.list_user_schemas()
        for schema in schemas:
            await self._get_base_for_schema(schema)
        self.logger.info(f"All user schemas reflected: {schemas}")

    # ─── Public Introspection ───────────────────────────────────────────────
    async def health_check(self) -> bool:
        try:
            async with self._manager.get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            self.logger.info("Health check passed")
            return True
        except OperationalError as e:
            self.logger.exception(f"Health check failed — OperationalError: {e}")
            return False
        except InterfaceError as e:
            self.logger.exception(f"Health check failed — InterfaceError: {e}")
            return False
        except Exception as e:
            self.logger.exception(f"Health check failed — Unexpected error: {e}")
            return False

    async def list_schemas(self) -> List[str]:
        async with self._manager.get_engine().connect() as conn:
            schemas = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_schema_names()
            )
        self.logger.info(f"Schemas retrieved successfully: {schemas}")
        return schemas

    async def list_user_schemas(self) -> List[str]:
        schemas = await self.list_schemas()
        user_schemas = [
            s for s in schemas
            if not s.startswith("pg_") and s != "information_schema"
        ]
        self.logger.info(f"User schemas: {user_schemas}")
        return user_schemas

    async def list_tables_in_schema(self, schema: Optional[str] = None) -> List[str]:
        schema = schema or self.default_schema
        if schema:
            validate_identifier(schema, label="schema")
        async with self._manager.get_engine().connect() as conn:
            tables = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names(schema=schema)
            )
        self.logger.info(f"Tables in '{schema}': {tables}")
        return tables

    async def list_columns_in_table(
            self,
            table_name: str,
            schema: Optional[str] = None,
        ) -> List[Dict[str, Any]]:
            """
            List all columns in a given table with their metadata.

            Returns a list of dicts, each containing:
                - name: column name
                - type: SQLAlchemy type object
                - nullable: bool
                - default: default value or None
                - autoincrement: str or bool
                - comment: column comment or None
            """
            schema = schema or self.default_schema

            validate_identifier(table_name, label="table_name")
            if schema:
                validate_identifier(schema, label="schema")

            async with self._manager.get_engine().connect() as conn:
                columns = await conn.run_sync(
                    lambda sync_conn: inspect(sync_conn).get_columns(
                        table_name=table_name,
                        schema=schema,
                    )
                )

            self.logger.info(
                f"Retrieved {len(columns)} columns from '{schema}.{table_name}'"
            )
            return columns


    # ─── Session ────────────────────────────────────────────────────────────

    def session(self) -> AsyncSession:
        if not self._session_factory:
            raise RuntimeError(
                "Session factory not initialized. Call connect() first."
            )
        self.logger.debug("Creating new async session")
        return self._session_factory()

    async def get_table_model(
        self,
        table_name: str,
        schema: Optional[str] = None,
    ) -> Table:
        schema = schema or self.default_schema
        if schema:
            validate_identifier(schema, label="schema")
        validate_identifier(table_name, label="table_name")

        base = await self._get_base_for_schema(schema)

        try:
            model = base.classes[table_name]
            self.logger.info(
                f"Retrieved model for table '{table_name}' in schema '{schema}'"
            )
            return model
        except KeyError:
            self.logger.error(
                f"Table '{table_name}' not found in schema '{schema}'"
            )
            raise ValueError(
                f"Table '{table_name}' not found in schema '{schema}'"
            )

    # ─── Private Helpers ────────────────────────────────────────────────────
    def _build_insert_stmt(
        self,
        model: Any,
        rows: List[dict],
        on_conflict: str,
        conflict_columns: Optional[List[str]] = None,
        update_columns: Optional[List[str]] = None,
    ) -> Any:
        """Construct a pg_insert statement with optional upsert clause."""


        ### Normalzing the incosisitency ###
        all_keys = set().union(*(r.keys() for r in rows))
        rows = [
            {k: row.get(k, None) for k in all_keys}
            for row in rows
        ]


        stmt = pg_insert(model).values(rows)
        if on_conflict == "do_nothing":
            return stmt.on_conflict_do_nothing()

        if on_conflict == "do_update":
            if not conflict_columns or not update_columns:
                raise ValueError(
                    "conflict_columns and update_columns are required "
                    "when on_conflict='do_update'"
                )
            for col in conflict_columns:
                validate_identifier(col, label="conflict_column")
            for col in update_columns:
                validate_identifier(col, label="update_column")
            return stmt.on_conflict_do_update(
                index_elements=conflict_columns,
                set_={col: stmt.excluded[col] for col in update_columns},
            )

        raise ValueError(
            f"on_conflict must be 'do_nothing' or 'do_update', got {on_conflict!r}"
        )

    # ─── Public Query / CRUD ────────────────────────────────────────────────
    
    @retry()
    async def update_table(
        self,
        table_name: str,
        updates: dict,
        conditions: dict,
        schema: Optional[str] = None,
    ) -> int:
        validate_identifier(table_name, label="table_name")
        if schema:
            validate_identifier(schema, label="schema")

        model = await self.get_table_model(table_name, schema)

        for field in updates:
            if not hasattr(model, field):
                raise ValueError(
                    f"Field '{field}' not found in table '{table_name}'"
                )

        for field in conditions:
            if not hasattr(model, field):
                raise ValueError(
                    f"Condition field '{field}' not found in table '{table_name}'"
                )

        stmt = update(model).values(**updates)
        for field, value in conditions.items():
            stmt = stmt.where(getattr(model, field) == value)

        async with self.session() as session:
            try:
                self.logger.info(
                    f"Executing update on table '{table_name}' "
                    f"with updates={updates}, conditions={conditions}"
                )
                result = await session.execute(stmt)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

        cast_result = cast(CursorResult[Any], result)
        rowcount = cast_result.rowcount or 0

        if rowcount == 0:
            self.logger.warning(
                f"No rows updated in '{table_name}' with conditions: {conditions}"
            )
        else:
            self.logger.info(f"Updated {rowcount} row(s) in '{table_name}'")

        return rowcount

    @retry()
    async def insert_into_table(
        self,
        table_name: str,
        data: Union[dict, List[dict]],
        schema: Optional[str] = None,
        on_conflict: str = "do_nothing",
        conflict_columns: Optional[List[str]] = None,
        update_columns: Optional[List[str]] = None,
    ) -> int:
        validate_identifier(table_name, label="table_name")
        if schema:
            validate_identifier(schema, label="schema")

        model = await self.get_table_model(table_name, schema)

        rows = data if isinstance(data, list) else [data]

        if not rows:
            self.logger.warning(f"No data provided for insert into '{table_name}'")
            return 0

        if not all(isinstance(row, dict) for row in rows):
            raise ValueError("Insert data must be a dict or list of dicts")

        stmt = self._build_insert_stmt(
            model, rows, on_conflict, conflict_columns, update_columns
        )

        async with self.session() as session:
            try:
                self.logger.info(
                    f"Executing insert into '{table_name}' for {len(rows)} row(s)"
                )
                result = await session.execute(stmt)
                cursor_result = cast(CursorResult[Any], result)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

        inserted = cursor_result.rowcount or 0
        total = len(rows)
        skipped = total - inserted

        if skipped > 0:
            self.logger.warning(
                f"Inserted {inserted}/{total} row(s) into '{table_name}' "
                f"— {skipped} skipped due to conflict"
            )
        else:
            self.logger.info(f"Inserted {inserted} row(s) into '{table_name}'")

        return inserted

    @retry()
    async def insert_into_table_bulk(
        self,
        table_name: str,
        data: Union[dict, List[dict]],
        schema: Optional[str] = None,
        batch_size: int = 1000,
        commit_every_batch: bool = True,
        on_conflict: str = "do_nothing",
        conflict_columns: Optional[List[str]] = None,
        update_columns: Optional[List[str]] = None,
    ) -> int:
        validate_identifier(table_name, label="table_name")
        if schema:
            validate_identifier(schema, label="schema")

        model = await self.get_table_model(table_name, schema)

        rows = data if isinstance(data, list) else [data]

        if not rows:
            self.logger.warning(f"No data provided for insert into '{table_name}'")
            return 0

        if not all(isinstance(row, dict) for row in rows):
            raise ValueError("Insert data must be dict or list of dicts")

        total_inserted = 0
        total_rows = len(rows)

        if commit_every_batch:
            # One session per batch; commit immediately so partial progress survives.
            for i in range(0, total_rows, batch_size):
                batch = rows[i : i + batch_size]
                batch_num = i // batch_size + 1

                stmt = self._build_insert_stmt(
                    model, batch, on_conflict, conflict_columns, update_columns
                )

                async with self.session() as session:
                    try:
                        self.logger.info(
                            f"Inserting batch {batch_num} ({len(batch)} rows) "
                            f"into '{table_name}'"
                        )
                        self.debug_statement(
                            stmt=stmt,
                            operation="Bulk Insert",
                            table_name=table_name,
                        )
                        result = await session.execute(stmt)
                        cursor_result = cast(CursorResult[Any], result)
                        await session.commit()
                        total_inserted += cursor_result.rowcount or 0
                    except Exception:
                        await session.rollback()
                        raise
        else:
            # Single session & transaction for all batches.
            async with self.session() as session:
                try:
                    for i in range(0, total_rows, batch_size):
                        batch = rows[i : i + batch_size]
                        batch_num = i // batch_size + 1

                        stmt = self._build_insert_stmt(
                            model, batch, on_conflict, conflict_columns, update_columns
                        )

                        self.logger.info(
                            f"Inserting batch {batch_num} ({len(batch)} rows) "
                            f"into '{table_name}'"
                        )
                        self.debug_statement(
                            stmt=stmt,
                            operation="Bulk Insert",
                            table_name=table_name,
                        )
                        result = await session.execute(stmt)
                        total_inserted += result.rowcount or 0

                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        skipped = total_rows - total_inserted

        if skipped > 0:
            self.logger.warning(
                f"Inserted {total_inserted}/{total_rows} rows into '{table_name}' "
                f"— {skipped} skipped due to conflict"
            )
        else:
            self.logger.info(
                f"Inserted {total_inserted} rows into '{table_name}'"
            )

        return total_inserted

    @retry()
    async def execute_custom_statement(self, stmt) -> None:
        async with self.session() as session:
            try:
                # Downgraded to DEBUG to avoid leaking sensitive data in prod logs.
                self.logger.debug(f"Executing custom statement: {stmt}")
                await session.execute(stmt)
                await session.commit()
                self.logger.debug("Custom statement executed successfully")
            except Exception:
                await session.rollback()
                raise

    @retry()
    async def get_table_data(
        self,
        table_name: str,
        schema: Optional[str] = None,
        limit: int = 100,
        order_by: Optional[str] = None,
        ascending: Optional[bool] = True,
    ) -> List[Any]:
        validate_identifier(table_name, label="table_name")
        if schema:
            validate_identifier(schema, label="schema")

        model = await self.get_table_model(table_name, schema)
        stmt = select(model)

        if order_by:
            if not hasattr(model, order_by):
                raise ValueError(
                    f"Order by field '{order_by}' not found in table '{table_name}'"
                )
            if ascending:
                stmt = stmt.order_by(getattr(model, order_by).asc())
            else:
                stmt = stmt.order_by(getattr(model, order_by).desc())

        stmt = stmt.limit(limit)

        self.logger.info(
            f"Executing query on table {schema or self.default_schema}.{table_name}"
        )

        async with self.session() as session:
            result = await session.execute(stmt)
            rows = result.scalars().all()
            self.logger.info(
                f"Fetched {len(rows)} row(s) from table '{table_name}'"
            )
            return rows

    # ─── Static Converters ──────────────────────────────────────────────────
    @staticmethod
    def from_sqlalchemy_to_pandas(rows: List[Any]) -> "pd.DataFrame":
        if not rows:
            return pd.DataFrame()

        return pd.DataFrame([
            {
                column.name: getattr(row, column.name)
                for column in row.__table__.columns
            }
            for row in rows
        ])

    @staticmethod
    def from_sqlalchemy_to_json(rows: List[Any]) -> List[dict]:
        if not rows:
            return []

        return [
            {
                column.name: getattr(row, column.name)
                for column in row.__table__.columns
            }
            for row in rows
        ]





    