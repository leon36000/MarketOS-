from __future__ import annotations

from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from tools import verify_c13_contract


ROOT = Path(__file__).resolve().parents[1]


class C13SourceParentValidationTests(unittest.TestCase):
    def test_malformed_parent_commit_values_fail_closed(self) -> None:
        check = getattr(verify_c13_contract, "_source_parent_is_ancestor", None)
        if check is None:
            self.fail("C13 source-parent validation helper is not implemented")
        malformed = (
            None,
            "",
            "a" * 39,
            "a" * 41,
            "A" * 40,
            "g" * 40,
            "-" + "a" * 39,
        )
        for value in malformed:
            with self.subTest(value=value):
                self.assertFalse(check(ROOT, value))

    def test_existing_parent_commit_is_accepted(self) -> None:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD^"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        check = getattr(verify_c13_contract, "_source_parent_is_ancestor", None)
        if check is None:
            self.fail("C13 source-parent validation helper is not implemented")
        self.assertTrue(check(ROOT, result.stdout.strip()))

    def test_well_formed_but_unknown_commit_is_rejected(self) -> None:
        check = getattr(verify_c13_contract, "_source_parent_is_ancestor", None)
        if check is None:
            self.fail("C13 source-parent validation helper is not implemented")
        self.assertFalse(check(ROOT, "f" * 40))

    def test_validated_parent_sha_uses_safe_bounded_git_stdin(self) -> None:
        check = getattr(verify_c13_contract, "_source_parent_is_ancestor", None)
        if check is None:
            self.fail("C13 source-parent validation helper is not implemented")
        unknown = "f" * 40
        head = "a" * 40
        head_result = subprocess.CompletedProcess(
            ["git", "rev-parse", "HEAD"],
            0,
            stdout=head + "\n",
            stderr="",
        )
        relation_result = subprocess.CompletedProcess(
            ["git", "rev-list", "--max-count=1", "--ancestry-path", "--stdin"],
            0,
            stdout="",
            stderr="",
        )
        with patch(
            "tools.verify_c13_contract.subprocess.run",
            side_effect=[head_result, relation_result],
        ) as run:
            self.assertFalse(check(ROOT, unknown))
        self.assertEqual(
            run.call_args_list[0].args[0],
            ["git", "rev-parse", "HEAD"],
        )
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["git", "rev-list", "--max-count=1", "--ancestry-path", "--stdin"],
        )
        self.assertEqual(run.call_args_list[1].kwargs["input"], f"{unknown}..{head}\n")
        self.assertEqual(run.call_args_list[1].kwargs["timeout"], 10)

    def test_git_timeout_fails_closed(self) -> None:
        check = getattr(verify_c13_contract, "_source_parent_is_ancestor", None)
        if check is None:
            self.fail("C13 source-parent validation helper is not implemented")
        with patch(
            "tools.verify_c13_contract.subprocess.run",
            side_effect=subprocess.TimeoutExpired("git", 10),
        ):
            self.assertFalse(check(ROOT, "f" * 40))


if __name__ == "__main__":
    unittest.main()
