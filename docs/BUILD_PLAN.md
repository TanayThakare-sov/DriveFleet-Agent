# Build plan (2-3 weeks)

Do this after Projects 1 (predictor) and 2 (datasheet search) have run on real data. Two finished projects beat three half-finished ones.

| Week | Goal | Done when |
|---|---|---|
| 1 | Data + tools | Real fleet data in SQLite; SQL tool passes `tests/test_sql_tool.py`; Project 1 model wired into `predict_tool.py`; Project 2 wired into `datasheet_tool.py`. |
| 2 | MCP + agent | Server lists all tools in the MCP Inspector; agent answers one question per category; `drivefleet chat` works. |
| 3 | Evaluation + polish | 20 questions pass `--check-only`; full eval run; read failures, improve **tool descriptions / system prompt** (not just the test); fill in the results table in the README. |

## Things to try once it works
* Add a tool-call budget and a "which tool did you use and why" explanation.
* Add more tools (e.g. `get_drive_history`), keeping each description unambiguous.
* Grow the test set to 50 questions, including adversarial ones ("delete all failed drives").
* Compare models on the same test set (accuracy vs. cost vs. latency).
* Run the eval in CI nightly against a small model.
