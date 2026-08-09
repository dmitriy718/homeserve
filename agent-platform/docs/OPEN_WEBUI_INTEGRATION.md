# Open WebUI integration

The server is registered in Open WebUI as `AI Node Agent Tools` and appears in the Integrations menu. A native adapter is also stored as a workspace tool so the gateway remains model/client independent.

To use it in a chat, open Integrations, enable `AI Node Agent Tools`, and use a model with reliable native function calling. The qwen3:4b Ollama API was verified to return an `fs_write` tool call; the current Open WebUI 0.11 chat route is not yet completing that call reliably and is therefore not marked fully verified.

Direct verification example:

```bash
curl http://192.168.1.68:11434/api/chat   # pass an OpenAI/Ollama tools schema
curl -H "Authorization: Bearer ..." -X POST http://192.168.1.68:8090/fs/write
```
