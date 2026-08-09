# Angel Memory for NekroAgent

Native NekroAgent adaptation of
[`astrbot_plugin_angel_memory`](https://github.com/kawayiYokami/astrbot_plugin_angel_memory).
It does not require AstrBot or Angel Heart. The port uses NekroAgent lifecycle
hooks, prompt injection, sandbox methods, model groups, channel history, and
authenticated plugin routes.

## Features

- `angel_remember`: store durable facts, preferences, commitments,
  relationships, and reusable experience.
- `angel_recall`: search channel memories and structured notes.
- `angel_note_read`: read a note by its stable `N<number>` identifier.
- `angel_note_create`: create durable structured knowledge notes.
- Automatic prompt recall for relevant channel and user memories.
- Optional LLM consolidation using a configured NekroAgent model group.
- User profiles and four adjustable soul-state dimensions.
- Maintenance, archival, JSON import/export, and AstrBot migration helper.
- SQLite FTS5 retrieval with Chinese character and bigram normalization.

## Installation

Copy the complete `nekro_plugin_angel_memory` directory into the NekroAgent
working plugin directory:

```text
nekro-agent/
`-- plugins/
    `-- nekro_plugin_angel_memory/
        |-- __init__.py
        |-- plugin.py
        |-- main.py
        |-- engine.py
        |-- storage.py
        `-- ...
```

Restart NekroAgent, then enable and configure `Angel Memory` in the plugin
management page. The plugin has no additional Python package dependencies.

## Data Location

Runtime data is stored under the native NekroAgent plugin key:

```text
NEKRO_DATA_DIR/plugin_data/kawayiYokami_NekroPort.nekro_plugin_angel_memory/
```

The SQLite database is `angel_memory.sqlite3` inside that directory.

## Main Settings

- `ENABLE_AUTO_RECALL`: inject relevant historical evidence into the prompt.
- `AUTO_RECALL_LIMIT`: maximum automatic memory hits before soul-state scaling.
- `PROMPT_MAX_CHARS`: hard limit for the injected memory prompt.
- `ENABLE_AUTO_CONSOLIDATION`: periodically extract durable memories with an LLM.
- `CONSOLIDATE_EVERY_USER_MESSAGES`: user-message interval for consolidation.
- `CONSOLIDATION_MODEL_GROUP`: optional model group; empty uses the channel group.
- `ENABLE_HEURISTIC_REMEMBER`: remember explicit Chinese "remember this" messages.
- `ENABLE_USER_PROFILE`: maintain per-channel user profiles.
- `ENABLE_SOUL_STATE`: enable recall and expression tendency state.

If NekroAgent's built-in memory system is enabled at the same time, both systems
may inject overlapping context. Disable one system or reduce recall limits if
the prompt becomes repetitive.

## Admin API

NekroAgent mounts the authenticated plugin router at:

```text
/plugins/kawayiYokami_NekroPort.nekro_plugin_angel_memory
```

Endpoints require a NekroAgent super-user session:

- `GET /status`
- `GET /memories?chat_key=...`
- `PATCH /memories/{id}`
- `DELETE /memories/{id}`
- `GET /notes?chat_key=...`
- `DELETE /notes/{id}`
- `POST /consolidate?chat_key=...`
- `POST /maintenance`
- `GET /export`
- `POST /import`

## AstrBot Migration

Export the original plugin data as JSON, or point the helper at a compatible
SQLite database, then run it from the NekroAgent repository root:

```bash
python -m plugins.nekro_plugin_angel_memory.migrate_astrbot \
  /path/to/angel-memory-backup.json \
  /path/to/nekro-data/plugin_data/kawayiYokami_NekroPort.nekro_plugin_angel_memory/angel_memory.sqlite3 \
  --chat-key onebot_v11-group_123456
```

AstrBot scopes do not always map to a NekroAgent `chat_key`. Supply
`--chat-key` when the source records do not contain the correct target scope.
Back up both source and target databases before migration.

## Security

- The consolidation prompt explicitly excludes passwords, credentials, and secrets.
- Automatic and Agent-tool memory creation rejects obvious credentials and private keys.
- Recalled items are marked as historical evidence, not current instructions.
- Keep the plugin API behind NekroAgent authentication and HTTPS.
- Review exported data before sharing it because it may contain personal history.

## Compatibility Notes

This is a functional native adaptation, not a byte-for-byte port. The original
standalone WebUI, Tantivy index, FAISS/vector embeddings, and reranker are
replaced with NekroAgent-native APIs and lightweight SQLite FTS5 retrieval.

## License

This port preserves the original project's GNU GPL v3 licensing and attribution.
See `LICENSE` for the complete license text and `NOTICE` for attribution.
