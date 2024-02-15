.PHONY: test
test:
	python -m unittest tests/test_*.py


.PHONY: format
format:
	black --line-length 80 ./amt
	black --line-length 80 ./tests
