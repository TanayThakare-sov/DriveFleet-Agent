.PHONY: install setup test serve chat eval eval-check lint clean

install:
	pip install -r requirements-dev.txt && pip install -e .

setup:            ## build SQLite DB + train the failure model
	python -m drivefleet.cli setup

test:
	pytest -q

serve:            ## run the MCP server over stdio
	python -m drivefleet.mcp_server.server

chat:
	python -m drivefleet.cli chat

eval-check:       ## validate the test set's ground truth (no LLM / API key needed)
	python eval/run_eval.py --check-only

eval:             ## run the 20-question agent evaluation (needs ANTHROPIC_API_KEY)
	python eval/run_eval.py

lint:
	ruff check src tests eval

clean:
	rm -f data/*.db models/*.joblib models/*.json eval/results/*.json eval/results/*.md
