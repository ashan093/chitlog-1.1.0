"""Step 22 bounded internal migration-snapshot retention."""
import secrets

from chitlog.data.database import Database, MIGRATION_SNAPSHOT_RETENTION


def test_migration_snapshot_rotation_is_bounded(tmp_path):
    backup_dir = tmp_path / "snapshots"
    backup_dir.mkdir()

    db = Database(
        tmp_path / "db.chitlog",
        secrets.token_bytes(32),
        backup_dir,
    )

    # Rotation itself is filesystem-only and does not require an open DB.
    for index in range(MIGRATION_SNAPSHOT_RETENTION + 4):
        path = backup_dir / f"migration-20260918T12000{index}Z-{index}.db"
        path.write_bytes(b"encrypted-placeholder")

    db._rotate_migration_snapshots()

    remaining = list(backup_dir.glob("migration-*.db"))
    assert len(remaining) == MIGRATION_SNAPSHOT_RETENTION
