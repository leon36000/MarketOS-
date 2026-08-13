.PHONY: test validate verify

test:
	python -m unittest discover -s tests -v

validate:
	python tools/validate_repository.py --root . --json

verify: test validate
