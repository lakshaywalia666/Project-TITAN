PYTHON ?= python3

.PHONY: run control-api ai-api controller cli ops test lint portal-test clean

run:
	PYTHONPATH=src $(PYTHON) -m titan_api

control-api:
	PYTHONPATH=src $(PYTHON) -m titan_control.api_main

ai-api:
	PYTHONPATH=src $(PYTHON) -m titan_ai.api_main

controller:
	PYTHONPATH=src $(PYTHON) -m titan_control.controller

cli:
	PYTHONPATH=src $(PYTHON) -m titan_control $(ARGS)

ops:
	PYTHONPATH=src $(PYTHON) -m titan_ops $(ARGS)

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

lint:
	$(PYTHON) -m compileall -q src tests

portal-test:
	cd portal && pnpm run lint && pnpm run test

clean:
	find src tests -type d -name __pycache__ -prune -exec rm -rf {} +
