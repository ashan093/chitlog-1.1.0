"""Initialize ChitLog services, authenticate, then show the Step 6 main shell."""
import argparse
from pathlib import Path
import sys

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from chitlog.core.config import APP_NAME, APP_VERSION, ASSETS, default_paths
from chitlog.core.key_store import KeyStorageError, load_database_key
from chitlog.core.logging_config import close_logging, configure_logging
from chitlog.core.settings import AppearanceSettings
from chitlog.data.authentication_repository import AuthenticationRepository
from chitlog.data.database import Database, DatabaseError
from chitlog.data.budget_repository import BudgetRepository
from chitlog.data.liability_repository import LiabilityRepository
from chitlog.data.notification_repository import NotificationRepository
from chitlog.data.report_repository import ReportRepository
from chitlog.data.setup_repository import SetupRepository
from chitlog.data.settings_repository import SettingsRepository
from chitlog.data.transaction_repository import TransactionRepository
from chitlog.data.worker_repository import WorkerRepository
from chitlog.data.worker_payment_repository import WorkerPaymentRepository
from chitlog.data.worker_payroll_repository import WorkerPayrollRepository
from chitlog.data.worker_work_repository import WorkerWorkRepository
from chitlog.services.authentication_service import AuthenticationService
from chitlog.services.budget_service import BudgetService
from chitlog.services.backup_service import BackupService, recover_latest_pre_restore_backup
from chitlog.services.liability_service import LiabilityService
from chitlog.services.notification_service import NotificationError, NotificationService
from chitlog.services.windows_reminder_task import WindowsReminderTaskScheduler
from chitlog.services.report_service import ReportService
from chitlog.services.dashboard_service import DashboardService
from chitlog.services.setup_service import SetupService
from chitlog.services.settings_service import SettingsService
from chitlog.services.transaction_service import TransactionService
from chitlog.services.worker_service import WorkerService
from chitlog.services.worker_payment_service import WorkerPaymentService
from chitlog.services.worker_payroll_service import WorkerPayrollService
from chitlog.services.worker_work_service import WorkerWorkService
from chitlog.ui.background_notification import run_background_notification
from chitlog.ui.login_dialog import LoginDialog
from chitlog.ui.main_window import create_window
from chitlog.ui.setup_wizard import SetupWizard

# STEP24_GLOBAL_WINDOW_ICON_HELPER_BEGIN
def _apply_chitlog_window_icon(assets) -> None:
    # QApplication-level icon becomes the default for every top-level
    # window, including first-run PIN/password setup and login/lock.
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    icon_path = assets / "chit.png"
    if app is not None and icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
# STEP24_GLOBAL_WINDOW_ICON_HELPER_END


def _configure_windows_app_identity() -> None:
    """Give Windows a ChitLog application identity when running from Python.

    A packaged ChitLog executable will ultimately provide its own executable
    metadata. During development (`python app.py`), this reduces Windows Shell
    attribution to the Python host where the OS honors an explicit AppUserModelID.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "ChitLog"
        )
    except Exception:
        # Notification delivery must never prevent ChitLog from starting.
        pass


def _sync_notification_task_after_startup(service) -> None:
    """Best-effort background-task reconciliation after the UI is visible.

    Saving notification settings still performs the authoritative scheduler
    update immediately. This startup reconciliation is only a safety check and
    must not delay the user's PIN -> Dashboard transition.
    """
    if service is None:
        return
    try:
        service.sync_background_task()
    except NotificationError:
        # A scheduler problem must never close or freeze the finance UI.
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="ChitLog desktop application")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument(
        "--show-paths",
        action="store_true",
        help="Print OS-selected folders without creating them",
    )
    parser.add_argument(
        "--check-database",
        action="store_true",
        help="Initialize/validate encrypted storage and print safe status",
    )
    parser.add_argument(
        "--preview-only",
        action="store_true",
        help="Open only the application shell without database access",
    )
    parser.add_argument(
        "--notification-only",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--recover-pre-restore",
        action="store_true",
        help="Recover the newest validated pre-restore safety backup",
    )
    options = parser.parse_args()

    if options.check_database and options.preview_only:
        parser.error("--check-database cannot be combined with --preview-only")

    _configure_windows_app_identity()
    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("")
    app.setFont(QFont("Segoe UI", 10))

    logger = None
    database = None
    lock = None
    setup_repository = None
    transaction_service = None
    dashboard_service = None
    budget_service = None
    backup_service = None
    settings_service = None
    liability_service = None
    report_service = None
    notification_service = None
    worker_service = None
    worker_work_service = None
    worker_payment_service = None
    worker_payroll_service = None

    try:
        paths = default_paths()

        if options.show_paths:
            for name in ("root", "data", "logs", "backups", "cache"):
                print(f"{name}: {getattr(paths, name)}")
            return 0

        paths.ensure()

        if options.notification_only:
            # Windows Task Scheduler launches this privacy-safe one-shot path.
            # It does not show login or open the main ChitLog window.
            database_path = paths.data / "chitlog.db"
            if not database_path.exists():
                return 0
            key = load_database_key(database_path)
            database = Database(
                database_path,
                key,
                paths.backups / "migrations",
            ).open()
            del key
            notification_service = NotificationService(
                NotificationRepository(database)
            )
            app.setQuitOnLastWindowClosed(False)
            return run_background_notification(
                app,
                notification_service,
                ASSETS / "chit.png",
            )

        lock = QLockFile(str(paths.root / "chitlog.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            raise DatabaseError(
                "ChitLog is already running or its application lock is unavailable. "
                "Close the other window and try again."
            )

        logger = configure_logging(paths.logs)
        logger.info("application_started")

        if options.recover_pre_restore:
            database_path = paths.data / "chitlog.db"
            if not database_path.exists():
                raise DatabaseError(
                    "The live database file is missing. Recovery was not attempted."
                )
            key = load_database_key(database_path)
            recovered_from, preserved_live = recover_latest_pre_restore_backup(
                database_path,
                key,
                paths.backups / "local" / "restore-safety",
            )
            del key
            print(f"Recovered from: {recovered_from}")
            if preserved_live is not None:
                print(f"Preserved failed restored database: {preserved_live}")
            print("Recovery validation: OK")
            logger.info("pre_restore_recovery_completed")
            return 0

        appearance = AppearanceSettings(paths.root / "appearance.json")
        setup_state = None
        setup_completed_this_run = False
        active_theme = appearance.load_theme()

        if not options.preview_only:
            database_path = paths.data / "chitlog.db"
            key = load_database_key(database_path)
            database = Database(
                database_path,
                key,
                paths.backups / "migrations",
            ).open()
            del key

            if options.check_database:
                print(f"SQLCipher: {database.cipher_version}")
                print(f"Schema version: {database.version}")
                print("Integrity: OK | Key storage: Windows Credential Manager")
                print("Database encryption: enabled | Portable encrypted backup: available")
                logger.info("application_stopped")
                return 0

            setup_repository = SetupRepository(database)
            setup_service = SetupService(setup_repository, appearance)
            settings_service = SettingsService(SettingsRepository(database))

            if not setup_service.is_setup_complete():
                _apply_chitlog_window_icon(ASSETS)
                wizard = SetupWizard(ASSETS, setup_service)
                if wizard.exec() != QDialog.DialogCode.Accepted:
                    logger.info("setup_cancelled")
                    return 0
                setup_completed_this_run = True

            setup_state = setup_repository.load_state()

            active_theme = appearance.load_theme(setup_state.theme or "light")
            if setup_state.theme != active_theme:
                setup_repository.update_theme(active_theme)
                setup_state = setup_repository.load_state()

            if not setup_completed_this_run:
                authentication = AuthenticationService(AuthenticationRepository(database))
                _apply_chitlog_window_icon(ASSETS)
                login = LoginDialog(ASSETS, authentication, active_theme)
                if options.smoke_test:
                    QTimer.singleShot(500, login.reject)
                if login.exec() != QDialog.DialogCode.Accepted:
                    logger.info("login_cancelled")
                    return 0

            transaction_repository = TransactionRepository(database)
            transaction_service = TransactionService(
                transaction_repository,
                setup_state.currency_code or "LKR",
            )
            dashboard_service = DashboardService(transaction_repository)
            budget_service = BudgetService(
                BudgetRepository(database),
                setup_state.currency_code or "LKR",
            )
            liability_service = LiabilityService(
                LiabilityRepository(database),
                setup_state.currency_code or "LKR",
            )
            report_service = ReportService(ReportRepository(database))
            backup_service = BackupService(
                database,
                paths.backups / "local",
            )
            notification_service = NotificationService(
                NotificationRepository(database),
                WindowsReminderTaskScheduler(
                    Path(sys.argv[0]).resolve(),
                    python_executable=sys.executable,
                ),
            )
            # Do not contact Windows Task Scheduler on the critical
            # PIN -> main-window startup path. Reconcile it after the UI opens.
            worker_repository = WorkerRepository(database)
            worker_service = WorkerService(
                worker_repository,
                setup_state.currency_code or "LKR",
            )
            worker_work_service = WorkerWorkService(
                WorkerWorkRepository(database),
                worker_repository,
                setup_state.currency_code or "LKR",
            )
            worker_payment_service = WorkerPaymentService(
                WorkerPaymentRepository(database),
                worker_repository,
                setup_state.currency_code or "LKR",
            )
            worker_payroll_service = WorkerPayrollService(
                worker_repository,
                worker_work_service,
                worker_payment_service,
                WorkerPayrollRepository(database),
            )

        # STEP24_FIRST_RUN_AUTH_REFRESH_V12
        # Setup can create the credential after the original auth service was built.
        # Refresh it immediately before the shared main-window startup path.
        authentication = AuthenticationService(AuthenticationRepository(database))
        window = create_window(
            settings=appearance,
            theme_saver=setup_repository.update_theme if setup_repository else None,
            transaction_service=transaction_service,
            dashboard_service=dashboard_service,
            budget_service=budget_service,
            liability_service=liability_service,
            report_service=report_service,
            notification_service=notification_service,
            backup_service=backup_service,
            settings_service=settings_service,
            lazy_pages=True,
            worker_service=worker_service,
            worker_work_service=worker_work_service,
            worker_payment_service=worker_payment_service,
            worker_payroll_service=worker_payroll_service,
            currency_code=(setup_state.currency_code if setup_state else "LKR") or "LKR",
            currency_symbol=(setup_state.currency_symbol if setup_state else "Rs") or "Rs",
        )

        # STEP24_SESSION_LOCK_BEGIN
        # STEP24_SESSION_LOCK_REPAIR_V9
        def _lock_current_session() -> None:
            # Build and display the authentication surface before hiding finance data.
            # This prevents a failed dialog construction from leaving ChitLog running hidden.
            lock_dialog = None
            try:
                lock_dialog = LoginDialog(
                    ASSETS,
                    authentication,
                    getattr(window, "theme_name", "system"),
                    locked=True,
                )
                lock_dialog.setModal(True)
                lock_dialog.show()
                lock_dialog.raise_()
                lock_dialog.activateWindow()
                from PySide6.QtWidgets import QApplication
                app = QApplication.instance()
                if app is not None:
                    app.processEvents()
                # The lock screen is now visible; only now hide all financial content.
                window.hide()
                accepted = bool(lock_dialog.exec())
            except Exception:
                # Fail safe: never strand the application as an invisible running process.
                window.show()
                window.raise_()
                window.activateWindow()
                return
            if accepted:
                window.show()
                window.raise_()
                window.activateWindow()
                return
            # Closing the locked authentication screen means exit ChitLog completely.
            window.close()
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                app.quit()

        window.lock_requested.connect(_lock_current_session)
        # STEP24_SESSION_LOCK_END
        window.setWindowTitle(APP_NAME)

        if setup_state is not None:
            # MainWindow already applies the saved appearance during construction.
            # Avoid a second full stylesheet pass unless setup normalization
            # actually produced a different effective theme.
            if getattr(window, "theme_name", None) != active_theme:
                window.apply_theme(active_theme)
            window.feedback.setText(
                "Dashboard, Transactions, Budget, Liabilities, Workers, work records, payments, advances, payroll summaries, Reports, completed Settings, local desktop reminders, and encrypted data-only backup/restore are connected to your encrypted local data. "
                f"Currency: {setup_state.currency_code or '—'}."
            )
        else:
            window.feedback.setText(
                "Application shell preview only. Transactions require the encrypted database."
            )

        window.show()

        # Windows Task Scheduler can take noticeable time on some PCs. Run the
        # safety reconciliation after the Dashboard is already visible instead
        # of blocking the successful-login path.
        if notification_service is not None:
            QTimer.singleShot(
                1200,
                lambda service=notification_service:
                    _sync_notification_task_after_startup(service),
            )

        if options.smoke_test:
            QTimer.singleShot(500, app.quit)

        result = app.exec()
        logger.info("application_stopped")
        return result

    except Exception as error:
        if logger is not None:
            logger.error("startup_failed")

        message = (
            "ChitLog could not start. Check that your local application data folder "
            "is writable and that dependencies are installed. No financial records "
            "were changed."
        )
        if isinstance(error, (DatabaseError, KeyStorageError)):
            message = str(error)

        print(message, file=sys.stderr)
        if (
            not options.smoke_test
            and not options.show_paths
            and not options.check_database
            and not options.notification_only
            and not options.recover_pre_restore
        ):
            QMessageBox.critical(None, "ChitLog could not start", message)
        return 1

    finally:
        if database is not None:
            database.close()
        if logger is not None:
            close_logging(logger)
        if lock is not None:
            lock.unlock()
