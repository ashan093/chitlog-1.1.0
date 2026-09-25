"""Parameterized SQLite access for categories and financial transactions."""
from __future__ import annotations

from dataclasses import dataclass

from chitlog.data.database import Database


@dataclass(frozen=True)
class CategoryRecord:
    id: int
    kind: str
    name: str
    is_active: bool


@dataclass(frozen=True)
class TransactionRecord:
    id: int
    transaction_type: str
    transaction_date: str
    amount_minor: int
    category_id: int
    category_name: str
    description: str
    payment_method: str | None
    created_at: str
    updated_at: str


class TransactionRepository:
    def __init__(self, database: Database):
        self.database = database

    def list_categories(self, kind: str | None = None, *, include_inactive: bool = False) -> list[CategoryRecord]:
        sql = "SELECT id,kind,name,is_active FROM categories"
        conditions: list[str] = []
        params: list[object] = []
        if kind is not None:
            conditions.append("kind=?")
            params.append(kind)
        if not include_inactive:
            conditions.append("is_active=1")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += (" ORDER BY kind, "
                "CASE WHEN lower(name) IN ('other','other income') THEN 1 ELSE 0 END, "
                "name COLLATE NOCASE")
        rows = self.database.connection.execute(sql, params).fetchall()
        return [CategoryRecord(row[0], row[1], row[2], bool(row[3])) for row in rows]

    def get_category(self, category_id: int) -> CategoryRecord | None:
        row = self.database.connection.execute(
            "SELECT id,kind,name,is_active FROM categories WHERE id=?",
            (category_id,),
        ).fetchone()
        return CategoryRecord(row[0], row[1], row[2], bool(row[3])) if row else None

    def add_category(self, kind: str, name: str) -> int:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO categories(kind,name) VALUES (?,?)",
                (kind, name),
            )
            return int(cursor.lastrowid)

    def rename_category(self, category_id: int, name: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE categories SET name=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (name, category_id),
            )

    def set_category_active(self, category_id: int, active: bool) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE categories SET is_active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (1 if active else 0, category_id),
            )

    def create_transaction(
        self,
        *,
        transaction_type: str,
        transaction_date: str,
        amount_minor: int,
        category_id: int,
        description: str,
        payment_method: str | None,
    ) -> int:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO transactions("
                "transaction_type,transaction_date,amount_minor,category_id,description,payment_method"
                ") VALUES (?,?,?,?,?,?)",
                (
                    transaction_type,
                    transaction_date,
                    amount_minor,
                    category_id,
                    description,
                    payment_method,
                ),
            )
            return int(cursor.lastrowid)

    def update_transaction(
        self,
        transaction_id: int,
        *,
        transaction_type: str,
        transaction_date: str,
        amount_minor: int,
        category_id: int,
        description: str,
        payment_method: str | None,
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE transactions SET transaction_type=?,transaction_date=?,amount_minor=?,"
                "category_id=?,description=?,payment_method=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND is_deleted=0",
                (
                    transaction_type,
                    transaction_date,
                    amount_minor,
                    category_id,
                    description,
                    payment_method,
                    transaction_id,
                ),
            )

    def get_transaction(self, transaction_id: int) -> TransactionRecord | None:
        row = self.database.connection.execute(
            "SELECT t.id,t.transaction_type,t.transaction_date,t.amount_minor,t.category_id,"
            "c.name,t.description,t.payment_method,t.created_at,t.updated_at "
            "FROM transactions t JOIN categories c ON c.id=t.category_id "
            "WHERE t.id=? AND t.is_deleted=0",
            (transaction_id,),
        ).fetchone()
        if not row:
            return None
        return TransactionRecord(*row)

    def list_transactions(
        self,
        *,
        transaction_type: str | None = None,
        search: str = "",
        category_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 200,
    ) -> list[TransactionRecord]:
        sql = (
            "SELECT t.id,t.transaction_type,t.transaction_date,t.amount_minor,t.category_id,"
            "c.name,t.description,t.payment_method,t.created_at,t.updated_at "
            "FROM transactions t JOIN categories c ON c.id=t.category_id "
            "WHERE t.is_deleted=0"
        )
        params: list[object] = []
        if transaction_type is not None:
            sql += " AND t.transaction_type=?"
            params.append(transaction_type)
        if category_id is not None:
            sql += " AND t.category_id=?"
            params.append(category_id)
        if start_date is not None:
            sql += " AND t.transaction_date>=?"
            params.append(start_date)
        if end_date is not None:
            sql += " AND t.transaction_date<=?"
            params.append(end_date)
        cleaned = search.strip()
        if cleaned:
            sql += (
                " AND (t.description LIKE ? ESCAPE '\\' COLLATE NOCASE "
                "OR c.name LIKE ? ESCAPE '\\' COLLATE NOCASE "
                "OR COALESCE(t.payment_method,'') LIKE ? ESCAPE '\\' COLLATE NOCASE)"
            )
            escaped = cleaned.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            params.extend((pattern, pattern, pattern))
        sql += " ORDER BY t.transaction_date DESC,t.id DESC LIMIT ?"
        params.append(limit)
        rows = self.database.connection.execute(sql, params).fetchall()
        return [TransactionRecord(*row) for row in rows]

    def source_for(self, transaction_id: int) -> tuple[str, int | None] | None:
        row = self.database.connection.execute(
            "SELECT source_type,source_id FROM transactions WHERE id=?",
            (transaction_id,),
        ).fetchone()
        if row is None:
            return None
        return str(row[0]), (int(row[1]) if row[1] is not None else None)

    def liability_payment_for(self, transaction_id: int) -> int | None:
        row = self.database.connection.execute(
            "SELECT liability_payment_id FROM transactions WHERE id=?",
            (transaction_id,),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])

    def soft_delete(self, transaction_id: int) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE transactions SET is_deleted=1,deleted_at=CURRENT_TIMESTAMP,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=? AND is_deleted=0",
                (transaction_id,),
            )
            return cursor.rowcount == 1

    def restore(self, transaction_id: int) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE transactions SET is_deleted=0,deleted_at=NULL,updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND is_deleted=1",
                (transaction_id,),
            )
            return cursor.rowcount == 1

    def totals(self) -> tuple[int, int]:
        rows = self.database.connection.execute(
            "SELECT transaction_type,COALESCE(SUM(amount_minor),0) "
            "FROM transactions WHERE is_deleted=0 GROUP BY transaction_type"
        ).fetchall()
        values = {kind: int(amount) for kind, amount in rows}
        return values.get("income", 0), values.get("expense", 0)

    def totals_between(self, start_date: str, end_date: str) -> tuple[int, int]:
        rows = self.database.connection.execute(
            "SELECT transaction_type,COALESCE(SUM(amount_minor),0) "
            "FROM transactions WHERE is_deleted=0 "
            "AND transaction_date>=? AND transaction_date<=? "
            "GROUP BY transaction_type",
            (start_date, end_date),
        ).fetchall()
        values = {kind: int(amount) for kind, amount in rows}
        return values.get("income", 0), values.get("expense", 0)

    def list_recent_activity(self, *, limit: int = 8) -> list[TransactionRecord]:
        rows = self.database.connection.execute(
            "SELECT t.id,t.transaction_type,t.transaction_date,t.amount_minor,t.category_id,"
            "c.name,t.description,t.payment_method,t.created_at,t.updated_at "
            "FROM transactions t JOIN categories c ON c.id=t.category_id "
            "LEFT JOIN dismissed_recent_items d ON d.transaction_id=t.id "
            "WHERE t.is_deleted=0 AND d.transaction_id IS NULL "
            "ORDER BY t.transaction_date DESC,t.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [TransactionRecord(*row) for row in rows]

    def dismiss_recent(self, transaction_id: int) -> bool:
        with self.database.transaction() as connection:
            exists = connection.execute(
                "SELECT 1 FROM transactions WHERE id=? AND is_deleted=0",
                (transaction_id,),
            ).fetchone()
            if exists is None:
                return False
            cursor = connection.execute(
                "INSERT OR IGNORE INTO dismissed_recent_items(transaction_id) VALUES (?)",
                (transaction_id,),
            )
            return cursor.rowcount == 1

    def restore_recent(self, transaction_id: int) -> bool:
        """Remove a Dashboard-only dismissal without changing the transaction."""
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM dismissed_recent_items WHERE transaction_id=?",
                (transaction_id,),
            )
            return cursor.rowcount == 1
