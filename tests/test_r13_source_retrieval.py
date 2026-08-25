from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.r13_source_retrieval import (
    FetchResponse,
    ManifestError,
    RetrievalError,
    build_receipt_bundle,
    fetch_sources,
    load_manifest,
    validate_manifest,
    validate_receipt_bundle,
)


FAIL_CLOSED = "RETRIEVAL_AND_HASH_ONLY_NO_REDISTRIBUTION_OR_TRAINING_RIGHT_ASSERTED"


def source(
    source_id: str,
    url: str = "https://example.org/doc",
    **overrides: object,
) -> dict[str, object]:
    item: dict[str, object] = {
        "source_id": source_id,
        "title": source_id,
        "url": url,
        "category": "OFFICIAL_TOOL_DOCS",
        "authority_class": "OFFICIAL_DOCUMENTATION",
        "rights_class": FAIL_CLOSED,
        "required": True,
        "max_bytes": 4096,
        "expected_content_types": ["text/html", "text/plain"],
    }
    item.update(overrides)
    return item


def manifest(
    items: list[dict[str, object]],
    **overrides: object,
) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "marketos.r13-source-content-manifest.v1",
        "classification": "PREPHASE_RESEARCH_INPUT_NOT_PHASE_CLOSURE",
        "allowed_domains": ["example.org", "raw.githubusercontent.com"],
        "thresholds": {
            "minimum_successes": 1,
            "minimum_by_category": {"OFFICIAL_TOOL_DOCS": 1},
        },
        "sources": items,
        "hard_locks": {
            "live_trading": "HARD_LOCKED",
            "profitability": "UNPROVEN",
            "project_complete": False,
            "production_ready": False,
        },
    }
    value.update(overrides)
    return value


class ManifestValidationTests(unittest.TestCase):
    def test_rejects_non_https_url(self) -> None:
        with self.assertRaises(ManifestError):
            validate_manifest(manifest([source("bad", "http://example.org/doc")]))

    def test_rejects_non_allowlisted_domain(self) -> None:
        with self.assertRaises(ManifestError):
            validate_manifest(manifest([source("bad", "https://evil.example/doc")]))

    def test_rejects_non_fail_closed_rights(self) -> None:
        with self.assertRaises(ManifestError):
            validate_manifest(manifest([source("bad", rights_class="PUBLIC")]))

    def test_rejects_duplicate_ids_and_urls(self) -> None:
        with self.assertRaises(ManifestError):
            validate_manifest(
                manifest([source("dup"), source("dup", "https://example.org/other")])
            )
        with self.assertRaises(ManifestError):
            validate_manifest(manifest([source("one"), source("two")]))

    def test_load_manifest_rejects_unknown_schema(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "manifest.json"
            path.write_text(
                json.dumps(manifest([source("one")]) | {"schema_version": "wrong"})
            )
            with self.assertRaises(ManifestError):
                load_manifest(path)

    def test_load_manifest_assembles_content_addressed_source_shards(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shard = root / "sources.json"
            shard.write_text(
                json.dumps(
                    {
                        "schema_version": (
                            "marketos.r13-source-content-source-shard.v1"
                        ),
                        "category": "OFFICIAL_TOOL_DOCS",
                        "sources": [source("one")],
                    }
                )
            )
            root_manifest = manifest([])
            root_manifest.pop("sources")
            root_manifest["source_files"] = ["sources.json"]
            path = root / "manifest.json"
            path.write_text(json.dumps(root_manifest))
            loaded = load_manifest(path)
            self.assertEqual(
                [item["source_id"] for item in loaded["sources"]],
                ["one"],
            )
            self.assertEqual(len(loaded["source_shard_receipts"]), 1)
            self.assertRegex(
                loaded["source_shard_receipts"][0]["sha256"],
                r"^[0-9a-f]{64}$",
            )

    def test_load_manifest_rejects_source_shard_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            root_manifest = manifest([])
            root_manifest.pop("sources")
            root_manifest["source_files"] = ["../outside.json"]
            path = root / "manifest.json"
            path.write_text(json.dumps(root_manifest))
            with self.assertRaises(ManifestError):
                load_manifest(path)


class FetchResponseContractTests(unittest.TestCase):
    def test_fetch_response_is_constructible_and_immutable(self) -> None:
        response = FetchResponse(
            200,
            "https://example.org/final",
            "text/plain",
            b"x",
            {},
        )
        self.assertEqual(response.status, 200)
        with self.assertRaises(Exception):
            response.status = 201  # type: ignore[misc]


class RetrievalTests(unittest.TestCase):
    def test_hashes_exact_response_bytes_and_records_final_url(self) -> None:
        body = b"exact source bytes\n"

        def fake_fetch(
            url: str,
            *,
            timeout: float,
            user_agent: str,
        ) -> FetchResponse:
            self.assertEqual(url, "https://example.org/doc")
            self.assertGreater(timeout, 0)
            self.assertIn("MarketOS", user_agent)
            return FetchResponse(
                status=200,
                final_url="https://example.org/final",
                content_type="text/html; charset=utf-8",
                body=body,
                headers={"etag": '"abc"'},
            )

        with tempfile.TemporaryDirectory() as td:
            result = fetch_sources(
                manifest([source("one")]),
                Path(td),
                captured_at="2026-08-25T00:00:00Z",
                fetcher=fake_fetch,
            )
            receipt = result["receipts"][0]
            self.assertEqual(receipt["sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(receipt["byte_count"], len(body))
            self.assertEqual(receipt["final_url"], "https://example.org/final")
            self.assertTrue((Path(td) / receipt["private_raw_path"]).is_file())

    def test_rejects_redirect_to_non_allowlisted_domain(self) -> None:
        def fake_fetch(
            url: str,
            *,
            timeout: float,
            user_agent: str,
        ) -> FetchResponse:
            return FetchResponse(
                200,
                "https://evil.example/final",
                "text/plain",
                b"x",
                {},
            )

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RetrievalError):
                fetch_sources(
                    manifest([source("one")]),
                    Path(td),
                    "2026-08-25T00:00:00Z",
                    fake_fetch,
                )

    def test_rejects_oversized_content(self) -> None:
        def fake_fetch(
            url: str,
            *,
            timeout: float,
            user_agent: str,
        ) -> FetchResponse:
            return FetchResponse(200, url, "text/plain", b"x" * 10, {})

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RetrievalError):
                fetch_sources(
                    manifest([source("one", max_bytes=5)]),
                    Path(td),
                    "2026-08-25T00:00:00Z",
                    fake_fetch,
                )

    def test_rejects_unexpected_content_type(self) -> None:
        def fake_fetch(
            url: str,
            *,
            timeout: float,
            user_agent: str,
        ) -> FetchResponse:
            return FetchResponse(
                200,
                url,
                "application/octet-stream",
                b"x",
                {},
            )

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RetrievalError):
                fetch_sources(
                    manifest([source("one")]),
                    Path(td),
                    "2026-08-25T00:00:00Z",
                    fake_fetch,
                )

    def test_optional_failure_is_recorded_but_required_failure_fails(self) -> None:
        def fake_fetch(
            url: str,
            *,
            timeout: float,
            user_agent: str,
        ) -> FetchResponse:
            raise OSError("network down")

        with tempfile.TemporaryDirectory() as td:
            optional = manifest(
                [source("one", required=False)],
                thresholds={"minimum_successes": 0, "minimum_by_category": {}},
            )
            result = fetch_sources(
                optional,
                Path(td),
                "2026-08-25T00:00:00Z",
                fake_fetch,
            )
            self.assertEqual(len(result["failures"]), 1)

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RetrievalError):
                fetch_sources(
                    manifest([source("one")]),
                    Path(td),
                    "2026-08-25T00:00:00Z",
                    fake_fetch,
                )


class BundleTests(unittest.TestCase):
    def make_retrieval(self, root: Path) -> dict[str, object]:
        raw = root / "private_raw" / "one.html"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(b"source bytes")
        return {
            "schema_version": "marketos.r13-source-content-retrieval.v1",
            "captured_at": "2026-08-25T00:00:00Z",
            "manifest_sha256": "0" * 64,
            "thresholds": {
                "minimum_successes": 1,
                "minimum_by_category": {"OFFICIAL_TOOL_DOCS": 1},
            },
            "receipts": [
                {
                    "source_id": "one",
                    "title": "one",
                    "url": "https://example.org/doc",
                    "final_url": "https://example.org/doc",
                    "category": "OFFICIAL_TOOL_DOCS",
                    "authority_class": "OFFICIAL_DOCUMENTATION",
                    "rights_class": FAIL_CLOSED,
                    "status": 200,
                    "content_type": "text/html",
                    "byte_count": 12,
                    "sha256": hashlib.sha256(b"source bytes").hexdigest(),
                    "private_raw_path": "private_raw/one.html",
                    "captured_at": "2026-08-25T00:00:00Z",
                    "raw_bytes_shared": False,
                }
            ],
            "failures": [],
            "summary": {
                "successful_sources": 1,
                "failed_sources": 0,
                "successful_by_category": {"OFFICIAL_TOOL_DOCS": 1},
                "total_retrieved_bytes": 12,
            },
            "hard_locks": manifest([])["hard_locks"],
        }

    def test_bundle_omits_raw_source_bytes_and_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = build_receipt_bundle(
                self.make_retrieval(root),
                root,
                root / "bundle.zip",
            )
            validation = validate_receipt_bundle(result["bundle_path"])
            self.assertEqual(validation["status"], "PASS")
            with zipfile.ZipFile(result["bundle_path"]) as zf:
                names = zf.namelist()
                self.assertFalse(
                    any(name.startswith("private_raw/") for name in names)
                )
                self.assertNotIn("one.html", "\n".join(names))

    def test_bundle_is_byte_identical_for_same_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            retrieval = self.make_retrieval(root)
            one = build_receipt_bundle(retrieval, root / "one", root / "one.zip")
            two = build_receipt_bundle(retrieval, root / "two", root / "two.zip")
            self.assertEqual(one["bundle_sha256"], two["bundle_sha256"])
            self.assertEqual(
                (root / "one.zip").read_bytes(),
                (root / "two.zip").read_bytes(),
            )

    def test_validator_rejects_raw_bytes_in_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.zip"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("private_raw/secret.pdf", b"secret")
            with self.assertRaises(RetrievalError):
                validate_receipt_bundle(path)


if __name__ == "__main__":
    unittest.main()
