.PHONY: run test

run:
	bash run.sh

test:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
