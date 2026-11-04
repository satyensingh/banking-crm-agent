"""Read-only, parameterized PostgreSQL access. No agent-generated SQL."""
from __future__ import annotations
import os
from typing import Any

FEATURES = 'banking_crm_demo.customer_features'
PRODUCTS = 'banking_crm_demo.products'


class DatabaseUnavailable(RuntimeError):
    pass


class PostgresRepository:
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.getenv(
            'DATABASE_URL',
            'postgresql://banking_user:banking_dev_password@localhost:5432/banking_crm',
        )

    def _query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise DatabaseUnavailable('Install requirements.txt (psycopg is missing)') from exc
        try:
            with psycopg.connect(self.database_url, connect_timeout=5, row_factory=dict_row) as conn:
                with conn.cursor() as cursor:
                    cursor.execute('SET TRANSACTION READ ONLY')
                    cursor.execute(sql, params)
                    return cursor.fetchall()
        except psycopg.Error as exc:
            raise DatabaseUnavailable('PostgreSQL unavailable or query failed') from exc

    def search_customers(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        conditions: list[str] = []
        values: list[Any] = []
        mapping = {
            'city': ('city ILIKE %s', lambda v: v),
            'min_income_inr': ('monthly_income_inr >= %s', lambda v: v),
            'min_credit_score': ('credit_score >= %s', lambda v: v),
            'min_balance_inr': ('current_balance_inr >= %s', lambda v: v),
            'occupation': ('occupation = %s', lambda v: v),
        }
        for key, (condition, transform) in mapping.items():
            if filters.get(key) is not None:
                conditions.append(condition)
                values.append(transform(filters[key]))
        where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        # SQL structure is static except fragments selected from a fixed whitelist.
        sql = f'SELECT * FROM {FEATURES}{where} ORDER BY customer_id LIMIT %s OFFSET %s'
        values.extend((filters.get('limit', 20), filters.get('offset', 0)))
        return self._query(sql, tuple(values))

    def get_customer(self, customer_id: int) -> dict[str, Any] | None:
        rows = self._query(f'SELECT * FROM {FEATURES} WHERE customer_id = %s', (customer_id,))
        return rows[0] if rows else None

    def get_products(self, product_code: str | None = None) -> list[dict[str, Any]]:
        if product_code:
            return self._query(f'SELECT * FROM {PRODUCTS} WHERE active = TRUE AND product_code = %s ORDER BY product_id', (product_code,))
        return self._query(f'SELECT * FROM {PRODUCTS} WHERE active = TRUE ORDER BY product_id')

    def list_customers_for_ranking(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        # Scan all matching rows to score globally, then apply limit/offset in the service.
        # For large datasets migrate to indexed, database-side scoring/pagination.
        clean = {k: v for k, v in filters.items() if k not in ('limit', 'offset')}
        results = []
        for offset in range(0, 10000, 100):
            batch = self.search_customers({**clean, 'limit': 100, 'offset': offset})
            results.extend(batch)
            if len(batch) < 100:
                break
        return results

    def ping(self) -> bool:
        return bool(self._query('SELECT 1 AS ok'))
