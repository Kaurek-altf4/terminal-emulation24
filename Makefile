.PHONY: run test prepare

prepare:
	python3 scripts/build_vfs.py

run:
	bash run.sh

test:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
