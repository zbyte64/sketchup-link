# SketchUp Link

**Live sync from SketchUp to Blender** — a dual-language system for real-time model streaming and native `.skp` file import.

A Ruby plugin inside SketchUp acts as an HTTP server over a Unix socket (or TCP), streaming model snapshots and change events. A Python Blender addon connects to the socket to import the active SketchUp model live into Blender.

## Components

| Directory | Purpose |
|---|---|
| `sketchup_link/` | Ruby SketchUp plugin (HTTP server + observers) |
| `blender_plugin/` | Python Blender addon (live sync + SKP import + optional Cython/Rust bindings) |
| `tests/` | Test suite (unit, integration, BDD, fuzz) |
| `integration/` | Docker Windows 11 VM + headless Blender testing |
| `dist/` | Built `.rbz` extension archives |

## Quick Start

### Prerequisites

- **Python 3.13+** with `uv` package manager
- **Ruby 2.x+** (SketchUp embedded, or standalone for development)
- **Blender 4.2+** (for the addon)
- **SketchUp** (for the plugin — Windows/macOS)

### Install Python Dependencies

```bash
uv sync
```

### Run Tests

```bash
# All tests
uv run pytest tests/ -v

# By category
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -v
uv run pytest tests/bdd/ -v --no-screenshots
uv run pytest tests/fuzz/ -v --fuzz-mock
```

Alternatively, use the Makefile:

```bash
make test          # All tests
make test-unit     # Unit tests only
make test-file FILE=integration/test_blender_plugin.py
make test-class FILE=integration/test_blender_plugin.py CLASS=TestJsonFace
```

## SketchUp Plugin

### Install in SketchUp

1. Build the extension archive:

```bash
bundle install
bundle exec ruby package.rb
# → dist/sketchup-link-1.0.0.rbz
```

2. In SketchUp, open **Extensions > Extension Manager**
3. Click **Install Extension** and select the `.rbz` file
4. The plugin starts automatically, exposing a Unix socket at `/tmp/sketchup-link.sock` (or `%TEMP%\sketchup-link.sock` on Windows). TCP mode is available on port 9876.

### How It Works

The Ruby plugin registers observers on the active SketchUp model:
- `EntitiesObserver` — entity creation, modification, deletion
- `SelectionObserver` — selection changes
- `MaterialsObserver` — material changes
- `LayersObserver` — layer changes

Entity changes inside transactions are batched until commit; direct edits are debounced (50ms timer). All spatial data is converted from inches (SketchUp native) to meters before JSON emission.

## Blender Addon

### Install in Blender

1. Copy the `blender_plugin/` directory to Blender's addons folder
2. Enable **SketchUp Link & Importer** in Blender's Preferences > Add-ons
3. Configure the socket path in addon preferences

### Live Sync Mode

A background daemon thread polls `GET /model` every 2 seconds. The main-thread timer drains the queue (keeping only the most recent snapshot) and calls `SceneImporter.load()` directly.

### SKP Import Mode (SDK Bindings)

The addon includes optional Cython and Rust bindings for native `.skp` file import via the SketchUp SDK. These require a licensed SketchUp SDK installation:

```bash
# Cython extension
make build-importer

# Rust crate
SKETCHUP_SDK_PATH=/path/to/sdk make build-rust
```

Without the SDK, the addon loads fully for live-sync-only usage — the native import is guarded by a `try/except ImportError`.

### Duck-Typed Adapter Layer

The `live_adapter.py` module provides `JsonModel`, `JsonFace`, `JsonGroup`, etc. classes that mirror the Cython SLAPI binding interface. This lets `SceneImporter.load()` work with both live JSON and native `.skp` files without branching.

## Docker Development Environment

A Docker Compose setup provides a Windows 11 VM with SketchUp for end-to-end testing:

```bash
# Start the VM
make docker-up

# Access via RDP (port 3389) or web UI (port 8006)
# Credentials: Docker / admin
# Socket path: %TEMP%\sketchup-link.sock
# TCP port: 9876

# View logs
make docker-logs

# Stop the VM
make docker-down
```

## Test Suites

| Suite | Command | Description |
|---|---|---|
| Unit | `make test-unit` | Pure Python, no external dependencies |
| Integration | `make test` | Spawns mock Ruby server, validates JSON adapter classes |
| BDD | `make test-bdd` | Gherkin-style behavioral tests (CI-safe, no screenshots) |
| BDD Screenshots | `make test-bdd-screenshots` | Full visual regression with screenshot capture |
| BDD SketchUp | `make test-bdd-sketchup` | Launches SketchUp in VM, creates model, captures screenshots |
| Blender | `make test-blender` | Headless Blender integration (requires flatpak) |
| Fuzz (mock) | `make test-fuzz-mock` | Mutation-based fuzzing against Ruby mock server |
| Fuzz (VM) | `make test-fuzz` | Fuzzing against real SketchUp VM |

## Protocol

### HTTP API

| Method | Path | Description |
|---|---|---|
| GET | `/model` | Full model snapshot as JSON |
| GET | `/subscribe` | SSE stream of NDJSON change events |
| DELETE | `/unsubscribe` | Disconnect subscriber |
| GET | `/status` | Subscription status |

### Events

| Event | Description |
|---|---|
| `transaction.commit` | Entity changes committed |
| `transaction.undo` | Transaction undone |
| `transaction.redo` | Transaction redone |
| `selection.change` | Selection changed |
| `materials.change` | Material added/removed/modified |
| `layers.change` | Layer added/removed/modified |
| `model.save` | Model saved |
| `model.open` | Model opened |
| `model.close` | Model closed |

All spatial data is in **meters** (converted from SketchUp's native inches). Transforms are 16-element row-major flat arrays.

