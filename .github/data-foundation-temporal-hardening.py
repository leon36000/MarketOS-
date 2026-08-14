#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one patch site in {path}, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_once(path: str, pattern: str, replacement: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise SystemExit(f"expected one regex patch site in {path}, found {count}: {pattern[:80]}")
    target.write_text(updated, encoding="utf-8")


# The latest revision known at the historical cutoff controls economic validity.
replace_once(
    "src/marketos/identity.py",
    '''    @staticmethod\n    def _latest_visible(records: Iterable[ListingVersion | IdentifierAssignment], *, economic_time_ns: int, knowledge_time_ns: int):\n        visible = [\n            record\n            for record in records\n            if record.visible(economic_time_ns=economic_time_ns, knowledge_time_ns=knowledge_time_ns)\n        ]\n        if not visible:\n            return None\n        return max(visible, key=lambda record: (record.revision_time_ns, record.version))\n''',
    '''    @staticmethod\n    def _latest_known(\n        records: Iterable[ListingVersion | IdentifierAssignment],\n        *,\n        knowledge_time_ns: int,\n    ) -> ListingVersion | IdentifierAssignment | None:\n        known = [\n            record\n            for record in records\n            if record.available_to_strategy_at_ns <= knowledge_time_ns\n        ]\n        if not known:\n            return None\n        return max(known, key=lambda record: (record.revision_time_ns, record.version))\n''',
)
replace_once(
    "src/marketos/identity.py",
    '''            latest = self._latest_visible(\n                history,\n                economic_time_ns=economic_time_ns,\n                knowledge_time_ns=knowledge_time_ns,\n            )\n            if latest is not None and latest.venue_id == venue_id and latest.symbol == normalized_symbol:\n                candidates.append(latest)\n''',
    '''            latest = self._latest_known(history, knowledge_time_ns=knowledge_time_ns)\n            if (\n                isinstance(latest, ListingVersion)\n                and latest.visible(\n                    economic_time_ns=economic_time_ns,\n                    knowledge_time_ns=knowledge_time_ns,\n                )\n                and latest.venue_id == venue_id\n                and latest.symbol == normalized_symbol\n            ):\n                candidates.append(latest)\n''',
)
replace_once(
    "src/marketos/identity.py",
    '''            latest = self._latest_visible(\n                history,\n                economic_time_ns=economic_time_ns,\n                knowledge_time_ns=knowledge_time_ns,\n            )\n            if latest is not None and latest.identifier_type is identifier_type and latest.value == normalized:\n                candidates.append(latest)\n''',
    '''            latest = self._latest_known(history, knowledge_time_ns=knowledge_time_ns)\n            if (\n                isinstance(latest, IdentifierAssignment)\n                and latest.visible(\n                    economic_time_ns=economic_time_ns,\n                    knowledge_time_ns=knowledge_time_ns,\n                )\n                and latest.identifier_type is identifier_type\n                and latest.value == normalized\n            ):\n                candidates.append(latest)\n''',
)

# Adjustment revisions follow the same latest-known rule.
replace_once(
    "src/marketos/corporate_actions.py",
    '''        selected: list[AdjustmentFactor] = []\n        for history in self._history.values():\n            visible = [\n                factor\n                for factor in history\n                if factor.instrument_id == instrument_id\n                and raw_time_ns < factor.applies_before_ns\n                and factor.available_to_strategy_at_ns <= knowledge_time_ns\n            ]\n            if visible:\n                selected.append(max(visible, key=lambda factor: factor.version))\n        return tuple(sorted(selected, key=lambda factor: (factor.applies_before_ns, str(factor.factor_id))))\n''',
    '''        selected: list[AdjustmentFactor] = []\n        for history in self._history.values():\n            known = [\n                factor\n                for factor in history\n                if factor.available_to_strategy_at_ns <= knowledge_time_ns\n            ]\n            if not known:\n                continue\n            latest = max(\n                known,\n                key=lambda factor: (factor.available_to_strategy_at_ns, factor.version),\n            )\n            if latest.instrument_id == instrument_id and raw_time_ns < latest.applies_before_ns:\n                selected.append(latest)\n        return tuple(sorted(selected, key=lambda factor: (factor.applies_before_ns, str(factor.factor_id))))\n''',
)

# Every temporal-fact read verifies the stored content hash.
regex_once(
    "src/marketos/datafabric.py",
    r'''    @staticmethod\n    def _from_row\(row: sqlite3\.Row\) -> TemporalFact:\n        payload = _canonical_decode\(json\.loads\(row\["payload_json"\]\)\)\n        return TemporalFact\((.*?)\n        \)\n\n    def append''',
    '''    @staticmethod\n    def _from_row(row: sqlite3.Row) -> TemporalFact:\n        payload = _canonical_decode(json.loads(row["payload_json"]))\n        fact = TemporalFact(\\1\n        )\n        if fact.sha256() != str(row["fact_sha256"]):\n            raise InvariantViolation(\n                f"TEMPORAL_FACT_HASH_MISMATCH:{fact.fact_id}:{fact.version}"\n            )\n        return fact\n\n    def append''',
)

# Select latest known revision per fact identity, then apply economic validity.
regex_once(
    "src/marketos/datafabric.py",
    r'''        rows = self\._connection\.execute\(\n            """\n            SELECT \* FROM temporal_facts\n            WHERE fact_key = \?\n              AND valid_from_ns <= \?\n              AND \(valid_to_ns IS NULL OR \? < valid_to_ns\)\n              AND available_to_strategy_at_ns <= \?\n            ORDER BY fact_id, revision_time_ns DESC, version DESC\n            """,\n            \(fact_key, economic_time_ns, economic_time_ns, knowledge_time_ns\),\n        \)\.fetchall\(\)\n        latest_by_fact_id: dict\[str, sqlite3\.Row\] = \{\}\n        for row in rows:\n            latest_by_fact_id\.setdefault\(str\(row\["fact_id"\]\), row\)\n        if len\(latest_by_fact_id\) > 1:\n            raise AmbiguousTemporalFact\(\n                f"AMBIGUOUS_TEMPORAL_FACT:\{fact_key\}:\{economic_time_ns\}:\{knowledge_time_ns\}"\n            \)\n        if not latest_by_fact_id:\n            return None\n        return self\._from_row\(next\(iter\(latest_by_fact_id\.values\(\)\)\)\)''',
    '''        rows = self._connection.execute(\n            """\n            SELECT * FROM temporal_facts\n            WHERE fact_key = ?\n              AND available_to_strategy_at_ns <= ?\n            ORDER BY fact_id, revision_time_ns DESC, version DESC\n            """,\n            (fact_key, knowledge_time_ns),\n        ).fetchall()\n        latest_by_fact_id: dict[str, TemporalFact] = {}\n        for row in rows:\n            fact_id = str(row["fact_id"])\n            if fact_id not in latest_by_fact_id:\n                latest_by_fact_id[fact_id] = self._from_row(row)\n        effective = [\n            fact\n            for fact in latest_by_fact_id.values()\n            if fact.valid_from_ns <= economic_time_ns\n            and (fact.valid_to_ns is None or economic_time_ns < fact.valid_to_ns)\n        ]\n        if len(effective) > 1:\n            raise AmbiguousTemporalFact(\n                f"AMBIGUOUS_TEMPORAL_FACT:{fact_key}:{economic_time_ns}:{knowledge_time_ns}"\n            )\n        return effective[0] if effective else None''',
)

# Dependency and rights identities may not be silently deduplicated.
replace_once(
    "src/marketos/datafabric.py",
    '''        object.__setattr__(self, "source_versions", tuple(sorted(set(self.source_versions))))\n        object.__setattr__(self, "rights_policy_ids", tuple(sorted(set(self.rights_policy_ids))))\n''',
    '''        if len(self.source_versions) != len(set(self.source_versions)):\n            raise InvariantViolation("DUPLICATE_SOURCE_VERSION")\n        if len(self.rights_policy_ids) != len(set(self.rights_policy_ids)):\n            raise InvariantViolation("DUPLICATE_RIGHTS_POLICY_ID")\n        object.__setattr__(self, "source_versions", tuple(sorted(self.source_versions)))\n        object.__setattr__(self, "rights_policy_ids", tuple(sorted(self.rights_policy_ids)))\n''',
)

# Re-verify every committed dataset byte before treating publication as idempotent.
replace_once(
    "src/marketos/datafabric.py",
    '''    def publish(\n        self,\n        spec: DatasetSpec,\n''',
    '''    @staticmethod\n    def _verify_committed_files(final_dir: Path, manifest: Mapping[str, Any]) -> None:\n        records = manifest.get("files")\n        if not isinstance(records, list):\n            raise InvariantViolation("INVALID_DATASET_COMMIT_MANIFEST")\n        expected_paths = {"COMMIT.json"}\n        for record in records:\n            if not isinstance(record, Mapping):\n                raise InvariantViolation("INVALID_DATASET_COMMIT_RECORD")\n            relative = _safe_relative(str(record.get("path", "")))\n            expected_paths.add(relative.as_posix())\n            path = final_dir.joinpath(*relative.parts)\n            if not path.is_file():\n                raise InvariantViolation(f"DATASET_FILE_MISSING:{relative.as_posix()}")\n            data = path.read_bytes()\n            if len(data) != record.get("bytes"):\n                raise InvariantViolation(\n                    f"DATASET_FILE_BYTE_COUNT_MISMATCH:{relative.as_posix()}"\n                )\n            if _sha256_bytes(data) != record.get("sha256"):\n                raise InvariantViolation(\n                    f"DATASET_FILE_HASH_MISMATCH:{relative.as_posix()}"\n                )\n        actual_paths = {\n            path.relative_to(final_dir).as_posix()\n            for path in final_dir.rglob("*")\n            if path.is_file()\n        }\n        unexpected = sorted(actual_paths - expected_paths)\n        if unexpected:\n            raise InvariantViolation(f"DATASET_UNEXPECTED_FILE:{unexpected[0]}")\n\n    def publish(\n        self,\n        spec: DatasetSpec,\n''',
)
replace_once(
    "src/marketos/datafabric.py",
    '''            existing = commit_path.read_bytes()\n            if existing != manifest_bytes:\n                raise DuplicateConflict(\n                    f"DATASET_VERSION_CONFLICT:{spec.dataset_id}:{spec.version}"\n                )\n            return PublicationResult(\n''',
    '''            existing = commit_path.read_bytes()\n            if existing != manifest_bytes:\n                raise DuplicateConflict(\n                    f"DATASET_VERSION_CONFLICT:{spec.dataset_id}:{spec.version}"\n                )\n            try:\n                committed_manifest = json.loads(existing)\n            except json.JSONDecodeError as exc:\n                raise InvariantViolation("INVALID_DATASET_COMMIT_MANIFEST") from exc\n            self._verify_committed_files(final_dir, committed_manifest)\n            return PublicationResult(\n''',
)
replace_once(
    "src/marketos/datafabric.py",
    '''            final_dir.parent.mkdir(parents=True, exist_ok=True)\n            os.replace(stage, final_dir)\n        except Exception:\n''',
    '''            final_dir.parent.mkdir(parents=True, exist_ok=True)\n            os.replace(stage, final_dir)\n            self._verify_committed_files(final_dir, manifest)\n        except Exception:\n''',
)

# Dedicated workflow must execute the new temporal/corruption tests explicitly.
replace_once(
    ".github/workflows/data-foundation.yml",
    '''      - "tests/test_data_foundation_acceptance.py"\n      - "tools/verify_data_foundation.py"\n''',
    '''      - "tests/test_data_foundation_acceptance.py"\n      - "tests/test_data_foundation_temporal_semantics.py"\n      - "tools/verify_data_foundation.py"\n''',
)
replace_once(
    ".github/workflows/data-foundation.yml",
    '''      - "tests/test_data_foundation_acceptance.py"\n      - "tools/verify_data_foundation.py"\n''',
    '''      - "tests/test_data_foundation_acceptance.py"\n      - "tests/test_data_foundation_temporal_semantics.py"\n      - "tools/verify_data_foundation.py"\n''',
)
replace_once(
    ".github/workflows/data-foundation.yml",
    '''            tests.test_data_foundation_adversarial \\\n            tests.test_data_foundation_acceptance -v\n''',
    '''            tests.test_data_foundation_adversarial \\\n            tests.test_data_foundation_acceptance \\\n            tests.test_data_foundation_temporal_semantics -v\n''',
)

# Preserve the strengthened semantics in implementation documentation.
replace_once(
    "docs/implementation/SECURITY_MASTER_DATA_FABRIC.md",
    '''- SQLite bitemporal facts with explicit knowledge cutoffs and conflict quarantine;\n- staged, rights/quality/lineage-gated atomic dataset publication;\n''',
    '''- SQLite bitemporal facts with latest-known revision semantics, hash verification and conflict quarantine;\n- staged, rights/quality/lineage-gated atomic dataset publication with committed-byte re-verification;\n''',
)
