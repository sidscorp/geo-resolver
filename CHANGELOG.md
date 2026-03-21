# Changelog

## 0.1.0 — 2026-03-20

Initial release.

### Features

- Natural language geographic query resolution via LLM tool-calling loop
- Multi-source data: administrative divisions, land features, water features, land use, and points of interest from Overture Maps
- Spatial operations: union, intersection, difference, buffer, directional clipping
- Streaming API with Server-Sent Events for real-time progress
- CLI with `resolve`, `download-data`, and `build-db` subcommands
- Works with any OpenAI-compatible LLM provider (OpenRouter, OpenAI, Ollama, etc.)
- LRU query cache with disk persistence
- Coordinate-based disambiguation for search results
