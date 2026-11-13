# DriveFleet Agent

An **agent that uses tools** to answer plain-English questions about a fleet of hard drives.
A normal chatbot only talks; this agent decides which tool to call, reads the result, and answers.

| You ask | The agent uses |
|---|---|
| "Which drive models failed most last quarter?" | **SQL tool** (read-only SQLite) |
| "Is drive SN00157 at risk?" | **Prediction tool** (wraps your Project 1 failure model) |
| "What's the warranty on the Orion O12?" | **Datasheet search** (wraps your Project 2 retrieval) |
| "Which of my high-risk drives are still under warranty?" | **All three, together** |

The tools are exposed through an **MCP server** (Model Context Protocol), so any MCP-compatible
app (Claude Desktop, Claude Code, your own agent) can use them. The included agent is itself an MCP client.

```
 question ──► Agent (LLM, tool-use loop) ──MCP/stdio──► MCP server (drivefleet)
                      ▲                                    ├─ query_fleet_db        ─► SQLite (read-only)
                      └──────── tool results ◄─────────────├─ predict_drive_risk    ─► failure model (Project 1)
                                                           ├─ list_high_risk_drives ─► failure model (Project 1)
                                                           ├─ search_datasheets     ─► datasheet index (Project 2)
                                                           └─ describe_schema
```

## Quick start

Requires Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt && pip install -e .

drivefleet setup            # builds data/fleet.db (600 synthetic drives) and trains the failure model
pytest -q                   # 40 tests, no API key needed
python eval/run_eval.py --check-only   # validates the 20-question test set's ground truth

cp .env.example .env        # add your ANTHROPIC_API_KEY
drivefleet ask "Is drive SN00157 at risk?" --trace
drivefleet chat             # interactive
python eval/run_eval.py     # full agent evaluation -> eval/results/latest.md
```

Shortcuts: `make install setup test chat eval`.

## The tools (exposed over MCP)

| MCP tool | Purpose |
|---|---|
| `query_fleet_db(sql)` | One read-only SQLite `SELECT`. Counts, rankings, failures, SMART stats, warranty dates. |
| `describe_schema()` | Tables/views/columns, the dataset's "as-of" date, SQL hints. |
| `predict_drive_risk(serial)` | Failure probability, tier (low/medium/high) and abnormal SMART signals for one drive. |
| `list_high_risk_drives(min_tier, limit)` | Scores all active drives, returns those at/above a tier, highest risk first. |
| `search_datasheets(query, top_k)` | Searches datasheets for specs and warranty terms. |

Database: `drive_models`, `drives`, `smart_latest`, `failures`, `meta`, plus the view `drive_status`
(status, `warranty_end`, `under_warranty`). The dataset's "today" is **2025-07-15** so "last quarter" is Q2 2025.

## Safety: the SQL tool cannot change data

Four independent layers (see `src/drivefleet/tools/sql_tool.py`; each is tested):

1. **Validation**: exactly one `SELECT`/`WITH` statement; `INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/ATTACH/PRAGMA…` rejected (string literals and comments are stripped first, so `'drop table'` as data is fine).
2. **Read-only connection**: SQLite opened with `mode=ro` and `PRAGMA query_only=ON`.
3. **Authorizer**: a SQLite authorizer denies everything except `SELECT`/`READ`/`FUNCTION`.
4. **Limits**: row cap (`DRIVEFLEET_MAX_ROWS`, default 200) and a query timeout (`DRIVEFLEET_QUERY_TIMEOUT_S`, default 5 s).

Errors come back as tool results so the model can correct its own SQL. The agent's system prompt also tells it to refuse change requests.

## Use the server from other MCP apps

Run it directly: `python -m drivefleet.mcp_server.server` (stdio). Inspect it: `npx @modelcontextprotocol/inspector python -m drivefleet.mcp_server.server`.

**Claude Desktop** (`claude_desktop_config.json`, use absolute paths):
```json
{
  "mcpServers": {
    "drivefleet": {
      "command": "/ABS/PATH/drivefleet-agent/.venv/bin/python",
      "args": ["-m", "drivefleet.mcp_server.server"],
      "env": {
        "DRIVEFLEET_DB": "/ABS/PATH/drivefleet-agent/data/fleet.db",
        "DRIVEFLEET_MODEL_DIR": "/ABS/PATH/drivefleet-agent/models",
        "DRIVEFLEET_DATASHEET_DIR": "/ABS/PATH/drivefleet-agent/data/datasheets"
      }
    }
  }
}
```
**Claude Code:** `claude mcp add drivefleet -- /ABS/PATH/.venv/bin/python -m drivefleet.mcp_server.server`

## Evaluation (the part that matters more than the demo)

`eval/test_set.json` holds **20 questions**: 9 SQL, 4 datasheet, 3 prediction, 4 multi-tool.
Ground truth is **computed live** from the database / model (not hard-coded), so it stays valid if you change the data.

`python eval/run_eval.py` reports, overall and per category:

* **Tool selection**: did the agent call every tool the question needs?
* **Exact tool match**: ...and nothing extra?
* **Answer correctness**: does the final answer contain the ground-truth value(s)?
* **End-to-end**: both.

Failures are listed with expected vs. actual tools and the answer. Output: `eval/results/latest.md` and `latest.json`.
`--check-only` validates the ground truth without calling an LLM; `--ids 1,14,17` runs a subset.
The scoring logic itself is unit-tested (`tests/test_eval_checks.py`).

> No evaluation numbers are included in this repo: they depend on the model you run. Run it, then
> paste your table here. Expect multi-tool questions (17-20) to be the hardest.

## Plug in your real Projects 1 and 2

The included implementations are small stand-ins so everything runs end to end. Swap them, keep the interfaces:

* **Project 1 (predictor)**: save your estimator to `models/failure_model.joblib` (anything with `predict_proba` on a DataFrame) and write `models/model_card.json` with `features`, `thresholds` (`medium`, `high`) and optionally `feature_p90`. Or edit `tools/predict_tool.py`. Point `smart_latest` at your real SMART features.
* **Project 2 (datasheets)**: replace `tools/datasheet_tool.py`'s TF-IDF index with your retrieval pipeline; keep `search_datasheets(query, top_k) -> {"results": [{model, section, source, score, text}]}`. Drop your documents in `data/datasheets/`.
* **Real fleet data**: load it into SQLite using `src/drivefleet/schema.sql` (or change the schema and update the tool descriptions + system prompt).

## Project layout

```
drivefleet-agent/
├── README.md  requirements*.txt  pyproject.toml  Makefile  .env.example  .gitignore  LICENSE
├── src/drivefleet/
│   ├── config.py  schema.sql  seed.py  train.py  cli.py
│   ├── tools/        sql_tool.py  predict_tool.py  datasheet_tool.py
│   ├── mcp_server/   server.py              # MCP server (FastMCP, stdio)
│   └── agent/        agent.py               # MCP client + LLM tool-use loop
├── data/datasheets/  *.md                   # sample (fictional) datasheets
├── eval/             test_set.json  run_eval.py  results/
├── tests/            SQL safety, predictor, datasheets, MCP end-to-end, agent loop, eval scoring
├── scripts/          generate_sample_datasheets.py
├── docs/             ARCHITECTURE.md  BUILD_PLAN.md
└── .github/workflows/ci.yml
```

## Configuration

Environment variables (or `.env`): `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` (default `claude-sonnet-5-5`), `DRIVEFLEET_DB`,
`DRIVEFLEET_MODEL_DIR`, `DRIVEFLEET_DATASHEET_DIR`, `DRIVEFLEET_MAX_ROWS`, `DRIVEFLEET_QUERY_TIMEOUT_S`, `DRIVEFLEET_MAX_AGENT_STEPS`.

## Troubleshooting

* **`Database not found` / `Model not found`**: run `drivefleet setup`.
* **`mcp.server.fastmcp` import error**: you have MCP SDK 2.x. This project targets 1.x (`pip install "mcp>=1.2,<2"`). When you move to 2.x, `FastMCP` becomes `MCPServer`; see the SDK migration guide.
* **Server works in a terminal but not in Claude Desktop**: use absolute paths and the venv's Python in the config.
* **Never `print()` in the server**: stdout is the MCP protocol channel; log to stderr.

## Data note

All drive data, serial numbers and datasheets here are **synthetic/fictional**, generated for demonstration. They do not describe any real product.

## License

MIT
