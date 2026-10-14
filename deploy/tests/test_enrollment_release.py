"""Regression for the actual backup.sh output; no network or database calls."""

import importlib.util
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "production/deploy_enrollment_20261014.py"
spec = importlib.util.spec_from_file_location("enrollment_release", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BackupOutputTests(unittest.TestCase):
    def test_labeled_backup_output(self):
        value = "/var/backups/course-management/20261014T125143Z.ObdYfk"
        self.assertEqual(
            module.parse_backup_output("Backup completed: " + value + "\n"), value
        )

    def test_unexpected_plain_output_is_not_assumed(self):
        with self.assertRaises(ValueError):
            module.parse_backup_output(
                "/var/backups/course-management/20261014T125143Z.ObdYfk"
            )

    def test_other_directory_is_rejected(self):
        with self.assertRaises(ValueError):
            module.parse_backup_output(
                "Backup completed: /var/backups/another-project/20261014T125143Z.ObdYfk"
            )

    def test_extra_output_is_not_a_path(self):
        with self.assertRaises(ValueError):
            module.parse_backup_output(
                "unexpected\nBackup completed: /var/backups/course-management/20261014T125143Z.ObdYfk"
            )


if __name__ == "__main__":
    unittest.main()
