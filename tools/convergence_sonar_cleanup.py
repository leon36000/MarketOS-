from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def patch_store() -> None:
    path = Path("src/marketos/store.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''_BEGIN_IMMEDIATE = "BEGIN IMMEDIATE"
_CANONICAL_TAGS = frozenset({"$decimal", "$datetime", "$path", "$uuid"})''',
        '''_BEGIN_IMMEDIATE = "BEGIN IMMEDIATE"
_DECIMAL_TAG = "$decimal"
_CANONICAL_TAGS = frozenset({_DECIMAL_TAG, "$datetime", "$path", "$uuid"})''',
        "decimal tag constant",
    )
    text = replace_once(
        text,
        '''        if set(value) == {"$decimal"}:
            return Decimal(value["$decimal"])''',
        '''        if set(value) == {_DECIMAL_TAG}:
            return Decimal(value[_DECIMAL_TAG])''',
        "decimal decoder constant",
    )
    text = replace_once(
        text,
        '''def _reject_ambiguous_decimal_maps(value: Any) -> None:
    if isinstance(value, Mapping):
        normalized_items = tuple((str(key), item) for key, item in value.items())
        normalized_keys = tuple(key for key, _ in normalized_items)
        normalized_key_set = set(normalized_keys)
        if len(normalized_key_set) != len(normalized_keys):
            raise InvariantViolation("NON_CANONICAL_PAYLOAD_KEYS")
        if normalized_key_set == {"$decimal"}:
            raise InvariantViolation("AMBIGUOUS_DECIMAL_MARKER")
        if len(normalized_keys) == 1 and normalized_keys[0] in _CANONICAL_TAGS:
            raise InvariantViolation(f"AMBIGUOUS_CANONICAL_TAG:{normalized_keys[0]}")
        for _, item in normalized_items:
            _reject_ambiguous_decimal_maps(item)
        return
''',
        '''def _validated_mapping_values(value: Mapping[Any, Any]) -> tuple[Any, ...]:
    normalized_items = tuple((str(key), item) for key, item in value.items())
    normalized_keys = tuple(key for key, _ in normalized_items)
    if len(set(normalized_keys)) != len(normalized_keys):
        raise InvariantViolation("NON_CANONICAL_PAYLOAD_KEYS")
    if normalized_keys == (_DECIMAL_TAG,):
        raise InvariantViolation("AMBIGUOUS_DECIMAL_MARKER")
    if len(normalized_keys) == 1 and normalized_keys[0] in _CANONICAL_TAGS:
        raise InvariantViolation(f"AMBIGUOUS_CANONICAL_TAG:{normalized_keys[0]}")
    return tuple(item for _, item in normalized_items)


def _reject_ambiguous_decimal_maps(value: Any) -> None:
    if isinstance(value, Mapping):
        for item in _validated_mapping_values(value):
            _reject_ambiguous_decimal_maps(item)
        return
''',
        "mapping validation refactor",
    )
    if text.count('"$decimal"') != 1:
        raise SystemExit("store.py must contain exactly one $decimal literal")
    path.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    path = Path("tests/test_store.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''                    with self.assertRaisesRegex(
                        InvariantViolation,
                        "AMBIGUOUS_DECIMAL_MARKER",
                    ):
                        store.append(
                            self.event(
                                f"wrapped-event-{index}",
                                payload={"wrapped": wrapper},
                            )
                        )''',
        '''                    event = self.event(
                        f"wrapped-event-{index}",
                        payload={"wrapped": wrapper},
                    )
                    with self.assertRaisesRegex(
                        InvariantViolation,
                        "AMBIGUOUS_DECIMAL_MARKER",
                    ):
                        store.append(event)''',
        "wrapped event exception isolation",
    )
    text = replace_once(
        text,
        '''        with SQLiteEventStore(self.path) as store:
            with self.assertRaisesRegex(InvariantViolation, "NON_CANONICAL_PAYLOAD_KEYS"):
                store.append(
                    self.event(
                        "normalized-key-event",
                        payload={"wrapped": marker_mapping},
                    )
                )''',
        '''        event = self.event(
            "normalized-key-event",
            payload={"wrapped": marker_mapping},
        )
        with SQLiteEventStore(self.path) as store:
            with self.assertRaisesRegex(InvariantViolation, "NON_CANONICAL_PAYLOAD_KEYS"):
                store.append(event)''',
        "normalized key exception isolation",
    )
    text = replace_once(
        text,
        '''                    with self.assertRaisesRegex(
                        InvariantViolation,
                        "NON_RECONSTRUCTIBLE_PAYLOAD_TYPE",
                    ):
                        store.append(
                            self.event(
                                f"unsupported-event-{index}",
                                payload={"value": value},
                            )
                        )''',
        '''                    event = self.event(
                        f"unsupported-event-{index}",
                        payload={"value": value},
                    )
                    with self.assertRaisesRegex(
                        InvariantViolation,
                        "NON_RECONSTRUCTIBLE_PAYLOAD_TYPE",
                    ):
                        store.append(event)''',
        "unsupported event exception isolation",
    )
    text = replace_once(
        text,
        '''                    with self.assertRaisesRegex(
                        InvariantViolation,
                        "AMBIGUOUS_CANONICAL_TAG",
                    ):
                        store.append(
                            self.event(
                                f"tagged-event-{index}",
                                payload={"value": value},
                            )
                        )''',
        '''                    event = self.event(
                        f"tagged-event-{index}",
                        payload={"value": value},
                    )
                    with self.assertRaisesRegex(
                        InvariantViolation,
                        "AMBIGUOUS_CANONICAL_TAG",
                    ):
                        store.append(event)''',
        "tagged event exception isolation",
    )
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_store()
    patch_tests()
