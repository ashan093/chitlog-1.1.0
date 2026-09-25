"""Ordered application-owned SQL migrations, each applied in one transaction."""
APP_ID = 0x43684C67

MIGRATIONS = (
    (
        1,
        "database_foundation",
        (
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY CHECK(version>0), "
            "name TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        ),
    ),
    (
        2,
        "first_run_setup",
        (
            "CREATE TABLE application_settings ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL, "
            "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
            "CREATE TABLE auth_profile ("
            "id INTEGER PRIMARY KEY CHECK(id=1), "
            "login_method TEXT NOT NULL CHECK(login_method IN ('pin','password')), "
            "secret_hash TEXT NOT NULL, "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
            "CREATE TABLE security_questions ("
            "id INTEGER PRIMARY KEY, "
            "position INTEGER NOT NULL UNIQUE CHECK(position>=1), "
            "question TEXT NOT NULL, answer_hash TEXT NOT NULL, "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        ),
    ),
    (
        3,
        "categories_and_transactions",
        (
            "CREATE TABLE categories ("
            "id INTEGER PRIMARY KEY, "
            "kind TEXT NOT NULL CHECK(kind IN ('income','expense')), "
            "name TEXT NOT NULL COLLATE NOCASE CHECK(length(name) BETWEEN 1 AND 80), "
            "is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)), "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "UNIQUE(kind, name))",
            "CREATE TABLE transactions ("
            "id INTEGER PRIMARY KEY, "
            "transaction_type TEXT NOT NULL CHECK(transaction_type IN ('income','expense')), "
            "transaction_date TEXT NOT NULL CHECK(length(transaction_date)=10), "
            "amount_minor INTEGER NOT NULL CHECK(amount_minor>0), "
            "category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT, "
            "description TEXT NOT NULL DEFAULT '' CHECK(length(description)<=500), "
            "payment_method TEXT CHECK(payment_method IS NULL OR length(payment_method)<=80), "
            "is_deleted INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1)), "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "deleted_at TEXT, "
            "CHECK((is_deleted=0 AND deleted_at IS NULL) OR (is_deleted=1 AND deleted_at IS NOT NULL)))",
            "CREATE INDEX idx_transactions_active_date "
            "ON transactions(is_deleted, transaction_date DESC, id DESC)",
            "CREATE INDEX idx_transactions_category "
            "ON transactions(category_id, is_deleted)",
            "INSERT INTO categories(kind,name) VALUES "
            "('expense','Food'),('expense','Transport'),('expense','Bills'),"
            "('expense','Business'),('expense','Shopping'),('expense','Medical'),"
            "('expense','Entertainment'),('expense','Salary Payment'),('expense','Other'),"
            "('income','Salary'),('income','Business Income'),('income','Other Income')",
        ),
    ),
    (
        4,
        "dashboard_recent_activity",
        (
            "CREATE TABLE dismissed_recent_items ("
            "transaction_id INTEGER PRIMARY KEY "
            "REFERENCES transactions(id) ON DELETE CASCADE, "
            "hidden_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        ),
    ),
    (
        5,
        "budget_system",
        (
            "CREATE TABLE budgets ("
            "id INTEGER PRIMARY KEY, "
            "budget_month TEXT NOT NULL CHECK(length(budget_month)=7), "
            "category_id INTEGER REFERENCES categories(id) ON DELETE RESTRICT, "
            "amount_minor INTEGER NOT NULL CHECK(amount_minor>0), "
            "carry_forward_enabled INTEGER NOT NULL DEFAULT 0 "
            "CHECK(carry_forward_enabled IN (0,1)), "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "CHECK(category_id IS NULL OR carry_forward_enabled=0))",
            "CREATE UNIQUE INDEX idx_budgets_month_total "
            "ON budgets(budget_month) WHERE category_id IS NULL",
            "CREATE UNIQUE INDEX idx_budgets_month_category "
            "ON budgets(budget_month,category_id) WHERE category_id IS NOT NULL",
            "CREATE TABLE budget_carry_forward ("
            "target_month TEXT PRIMARY KEY CHECK(length(target_month)=7), "
            "source_month TEXT NOT NULL CHECK(length(source_month)=7), "
            "amount_minor INTEGER NOT NULL CHECK(amount_minor>=0), "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        ),
    ),
    (
        6,
        "liabilities",
        (
            "CREATE TABLE liabilities ("
            "id INTEGER PRIMARY KEY, "
            "name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120), "
            "lender TEXT NOT NULL DEFAULT '' CHECK(length(lender)<=120), "
            "original_amount_minor INTEGER NOT NULL CHECK(original_amount_minor>0), "
            "start_date TEXT NOT NULL CHECK(length(start_date)=10), "
            "due_date TEXT CHECK(due_date IS NULL OR length(due_date)=10), "
            "notes TEXT NOT NULL DEFAULT '' CHECK(length(notes)<=1000), "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
            "CREATE TABLE liability_payments ("
            "id INTEGER PRIMARY KEY, "
            "liability_id INTEGER NOT NULL REFERENCES liabilities(id) ON DELETE RESTRICT, "
            "payment_date TEXT NOT NULL CHECK(length(payment_date)=10), "
            "amount_minor INTEGER NOT NULL CHECK(amount_minor>0), "
            "note TEXT NOT NULL DEFAULT '' CHECK(length(note)<=500), "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
            "CREATE INDEX idx_liability_payments_liability_date "
            "ON liability_payments(liability_id,payment_date DESC,id DESC)",
            "CREATE INDEX idx_liabilities_due_date ON liabilities(due_date)",
        ),
    ),
    (
        7,
        "liability_soft_delete",
        (
            "ALTER TABLE liabilities ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0 "
            "CHECK(is_deleted IN (0,1))",
            "ALTER TABLE liabilities ADD COLUMN deleted_at TEXT",
            "CREATE INDEX idx_liabilities_active_due_date "
            "ON liabilities(is_deleted,due_date)",
        ),
    ),
    (
        8,
        "worker_profiles",
        (
            "CREATE TABLE workers ("
            "id INTEGER PRIMARY KEY, "
            "name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120), "
            "worker_type TEXT NOT NULL CHECK(worker_type IN ('permanent','temporary')), "
            "phone TEXT NOT NULL DEFAULT '' CHECK(length(phone)<=40), "
            "address TEXT NOT NULL DEFAULT '' CHECK(length(address)<=300), "
            "notes TEXT NOT NULL DEFAULT '' CHECK(length(notes)<=1000), "
            "payment_method TEXT NOT NULL CHECK(payment_method IN ('daily','job','period','monthly')), "
            "normal_rate_minor INTEGER CHECK(normal_rate_minor IS NULL OR normal_rate_minor>0), "
            "date_added TEXT NOT NULL CHECK(length(date_added)=10), "
            "is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)), "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
            "CREATE INDEX idx_workers_active_type_name "
            "ON workers(is_active,worker_type,name COLLATE NOCASE)",
        ),
    ),
    (
        9,
        "worker_work_records",
        (
            "CREATE TABLE worker_work_records ("
            "id INTEGER PRIMARY KEY, "
            "worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE RESTRICT, "
            "earning_type TEXT NOT NULL CHECK(earning_type IN ('daily','job','period','monthly')), "
            "start_date TEXT NOT NULL CHECK(length(start_date)=10), "
            "end_date TEXT NOT NULL CHECK(length(end_date)=10), "
            "amount_minor INTEGER NOT NULL CHECK(amount_minor>0), "
            "description TEXT NOT NULL DEFAULT '' CHECK(length(description)<=500), "
            "is_deleted INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1)), "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "deleted_at TEXT, "
            "CHECK(end_date>=start_date), "
            "CHECK((is_deleted=0 AND deleted_at IS NULL) OR (is_deleted=1 AND deleted_at IS NOT NULL)))",
            "CREATE INDEX idx_worker_work_worker_date "
            "ON worker_work_records(worker_id,is_deleted,start_date DESC,id DESC)",
            "CREATE UNIQUE INDEX idx_worker_monthly_earning "
            "ON worker_work_records(worker_id,start_date) "
            "WHERE earning_type='monthly' AND is_deleted=0",
        ),
    ),
    (
        10,
        "worker_attendance_monthly_records",
        (
            "CREATE TABLE worker_attendance ("
            "id INTEGER PRIMARY KEY, "
            "worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE RESTRICT, "
            "work_date TEXT NOT NULL CHECK(length(work_date)=10), "
            "amount_minor INTEGER NOT NULL DEFAULT 0 CHECK(amount_minor>=0), "
            "note TEXT NOT NULL DEFAULT '' CHECK(length(note)<=500), "
            "is_deleted INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1)), "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "deleted_at TEXT, "
            "CHECK((is_deleted=0 AND deleted_at IS NULL) OR (is_deleted=1 AND deleted_at IS NOT NULL)))",
            "INSERT INTO worker_attendance(worker_id,work_date,amount_minor,note,created_at,updated_at) "
            "SELECT worker_id,start_date,SUM(amount_minor),"
            "COALESCE(GROUP_CONCAT(NULLIF(description,''),' / '),''),"
            "MIN(created_at),MAX(updated_at) FROM worker_work_records "
            "WHERE earning_type='daily' AND is_deleted=0 GROUP BY worker_id,start_date",
            "UPDATE worker_work_records SET is_deleted=1,deleted_at=CURRENT_TIMESTAMP,"
            "updated_at=CURRENT_TIMESTAMP WHERE earning_type='daily' AND is_deleted=0",
            "CREATE UNIQUE INDEX idx_worker_attendance_active_day "
            "ON worker_attendance(worker_id,work_date) WHERE is_deleted=0",
            "CREATE INDEX idx_worker_attendance_worker_date "
            "ON worker_attendance(worker_id,is_deleted,work_date DESC,id DESC)",
        ),
    ),
    (
        11,
        "worker_payments_and_advances",
        (
            "CREATE TABLE worker_payments ("
            "id INTEGER PRIMARY KEY, "
            "worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE RESTRICT, "
            "payment_date TEXT NOT NULL CHECK(length(payment_date)=10), "
            "amount_minor INTEGER NOT NULL CHECK(amount_minor>0), "
            "payment_type TEXT NOT NULL CHECK(payment_type IN "
            "('normal','end_of_day','partial','salary','advance')), "
            "note TEXT NOT NULL DEFAULT '' CHECK(length(note)<=500), "
            "is_deleted INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1)), "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "deleted_at TEXT, "
            "CHECK((is_deleted=0 AND deleted_at IS NULL) OR "
            "(is_deleted=1 AND deleted_at IS NOT NULL)))",
            "CREATE INDEX idx_worker_payments_worker_date "
            "ON worker_payments(worker_id,is_deleted,payment_date DESC,id DESC)",
            "CREATE INDEX idx_worker_payments_type_date "
            "ON worker_payments(payment_type,is_deleted,payment_date DESC)",
        ),
    ),
    (
        12,
        "worker_payroll_carry_forward_choices",
        (
            "CREATE TABLE worker_payroll_carry_forward ("
            "worker_id INTEGER NOT NULL REFERENCES workers(id) ON DELETE CASCADE, "
            "source_month TEXT NOT NULL CHECK(length(source_month)=10), "
            "carry_forward INTEGER NOT NULL DEFAULT 1 CHECK(carry_forward IN (0,1)), "
            "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "PRIMARY KEY(worker_id,source_month))",
            "CREATE INDEX idx_worker_payroll_carry_month "
            "ON worker_payroll_carry_forward(source_month,worker_id)",
        ),
    ),
    (
        13,
        "worker_attendance_duration",
        (
            "ALTER TABLE worker_attendance ADD COLUMN duration_type TEXT NOT NULL "
            "DEFAULT 'full_day' CHECK(duration_type IN ('full_day','half_day','hours'))",
            "ALTER TABLE worker_attendance ADD COLUMN hours_minutes INTEGER NOT NULL "
            "DEFAULT 0 CHECK(hours_minutes>=0 AND hours_minutes<=1440)",
        ),
    ),
    (
        14,
        "worker_payment_transaction_link",
        (
            "ALTER TABLE transactions ADD COLUMN source_type TEXT NOT NULL "
            "DEFAULT 'manual' CHECK(source_type IN ('manual','worker_payment'))",
            "ALTER TABLE transactions ADD COLUMN source_id INTEGER",
            "CREATE UNIQUE INDEX idx_transactions_source "
            "ON transactions(source_type,source_id) WHERE source_id IS NOT NULL",
            "INSERT OR IGNORE INTO application_settings(key,value) "
            "VALUES ('worker_payments_in_transactions','1')",
            "INSERT INTO transactions("
            "transaction_type,transaction_date,amount_minor,category_id,description,"
            "payment_method,is_deleted,created_at,updated_at,deleted_at,source_type,source_id"
            ") SELECT 'expense',wp.payment_date,wp.amount_minor,"
            "COALESCE((SELECT id FROM categories WHERE kind='expense' AND lower(name)='salary payment' LIMIT 1),"
            "(SELECT id FROM categories WHERE kind='expense' ORDER BY id LIMIT 1)),"
            "substr(CASE WHEN wp.payment_type='advance' THEN 'Worker advance — ' ELSE 'Worker payment — ' END "
            "|| w.name || CASE WHEN wp.note<>'' THEN ' — ' || wp.note ELSE '' END,1,500),"
            "'Worker Payment',wp.is_deleted,wp.created_at,wp.updated_at,wp.deleted_at,"
            "'worker_payment',wp.id FROM worker_payments wp JOIN workers w ON w.id=wp.worker_id",
        ),
    ),
    (
        15,
        "liability_payment_transaction_link",
        (
            "ALTER TABLE transactions ADD COLUMN liability_payment_id INTEGER "
            "REFERENCES liability_payments(id) ON DELETE CASCADE",
            "CREATE UNIQUE INDEX idx_transactions_liability_payment "
            "ON transactions(liability_payment_id) WHERE liability_payment_id IS NOT NULL",
            "INSERT OR IGNORE INTO application_settings(key,value) "
            "VALUES ('liability_payments_in_transactions','1')",
            "INSERT INTO transactions("
            "transaction_type,transaction_date,amount_minor,category_id,description,"
            "payment_method,is_deleted,created_at,updated_at,deleted_at,source_type,source_id,"
            "liability_payment_id"
            ") SELECT 'expense',lp.payment_date,lp.amount_minor,"
            "COALESCE((SELECT id FROM categories WHERE kind='expense' AND lower(name)='bills' LIMIT 1),"
            "(SELECT id FROM categories WHERE kind='expense' ORDER BY id LIMIT 1)),"
            "substr('Liability payment — ' || l.name || "
            "CASE WHEN lp.note<>'' THEN ' — ' || lp.note ELSE '' END,1,500),"
            "'Liability Payment',0,lp.created_at,lp.created_at,NULL,'manual',NULL,lp.id "
            "FROM liability_payments lp JOIN liabilities l ON l.id=lp.liability_id",
        ),
    ),
    (
        16,
        "liability_payment_history_controls",
        (
            "ALTER TABLE liabilities ADD COLUMN keep_transaction_history_on_delete "
            "INTEGER NOT NULL DEFAULT 1 CHECK(keep_transaction_history_on_delete IN (0,1))",
            "ALTER TABLE liability_payments ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0 "
            "CHECK(is_deleted IN (0,1))",
            "ALTER TABLE liability_payments ADD COLUMN updated_at TEXT",
            "ALTER TABLE liability_payments ADD COLUMN deleted_at TEXT",
            "UPDATE liability_payments SET updated_at=created_at WHERE updated_at IS NULL",
            "CREATE INDEX idx_liability_payments_active_date "
            "ON liability_payments(liability_id,is_deleted,payment_date DESC,id DESC)",
        ),
    ),

    (
        17,
        "automatic_update_preferences",
        (
            "INSERT OR IGNORE INTO application_settings(key,value) "
            "VALUES ('update_auto_check_enabled','1')",
            "INSERT OR IGNORE INTO application_settings(key,value) "
            "VALUES ('update_auto_install_enabled','0')",
            "INSERT OR IGNORE INTO application_settings(key,value) "
            "VALUES ('update_channel','stable')",
            "INSERT OR IGNORE INTO application_settings(key,value) "
            "VALUES ('update_check_interval_seconds','86400')",
        ),
    ),
)


class SchemaError(RuntimeError):
    pass


def schema_version(connection) -> int:
    return connection.execute("PRAGMA user_version").fetchone()[0]


def migrate(connection, snapshot, migrations=MIGRATIONS) -> None:
    current = schema_version(connection)
    versions = [version for version, _, _ in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise SchemaError("Migration definitions must be consecutive.")
    if current > len(migrations):
        raise SchemaError("This database needs a newer ChitLog version.")

    app_id = connection.execute("PRAGMA application_id").fetchone()[0]
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()

    if current == 0:
        if app_id not in (0, APP_ID) or tables:
            raise SchemaError("Unrecognized database. No schema changes were made.")
    else:
        if app_id != APP_ID:
            raise SchemaError("This is not a recognized ChitLog database.")
        history = connection.execute(
            "SELECT version,name FROM schema_migrations ORDER BY version"
        ).fetchall()
        expected = [(v, name) for v, name, _ in migrations if v <= current]
        if history != expected:
            raise SchemaError("The migration history is inconsistent.")

    if current == len(migrations):
        return

    if current:
        snapshot()

    connection.execute("BEGIN IMMEDIATE")
    try:
        for version, name, statements in migrations:
            if version <= current:
                continue
            for statement in statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version,name) VALUES (?,?)",
                (version, name),
            )
            connection.execute(f"PRAGMA user_version={version}")
        connection.execute(f"PRAGMA application_id={APP_ID}")
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise SchemaError("Database integrity validation failed.")
        connection.execute("COMMIT")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
