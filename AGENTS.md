# Repository Guidelines

## Project Overview

SketchUp Link is a dual-language live-sync system between SketchUp and Blender. A Ruby plugin running inside SketchUp acts as an HTTP-over-Unix-socket server, streaming model snapshots and change events. A Python Blender addon connects to the socket to import the active SketchUp model live into Blender.

The Blender addon (`blender_plugin/`) is self-contained: it includes `SceneImporter.load()` — the shared import codepath — plus duck-typed JSON adapters (`live_adapter.py`) that present the JSON socket response with the same interface as the Cython SLAPI bindings, and optional Cython/Rust bindings for native `.skp` file import via the SketchUp SDK.

## Repository Layout

```
Makefile                       # Top-level development tasks
sketchup_link/                 # Ruby SketchUp plugin (server)
blender_plugin/                # Python Blender addon (live sync + SKP import + Cython/Rust bindings)
integration/                   # VM infrastructure & integration tests
  compose.yml                  # Docker Compose for Windows 11 VM (SketchUp dev)
  Dockerfile.blender           # Blender Docker image for headless rendering
  scripts/                     # VM orchestration scripts
tests/                         # Test suite (pytest)
dist/                          # Built .rbz extension archive output

The monorepo root (`../../..`) also contains `docs/` (crawled API reference)
and `windows/` (Docker VM state), plus the three sibling extensions under
`shared/project/ext/`.
```


## Architecture & Data Flow

```
┌───────────── SketchUp (Windows VM) ─────────────┐
│                                                  │
│  AppObserver ──→ ModelObserver                   │
│                  EntitiesObserver                │
│                  SelectionObserver               │
│                  MaterialsObserver               │
│                  LayersObserver                  │
│       │                                          │
│       ▼                                          │
│  EventDispatcher (batching, debounce 50ms)       │
│       │                                          │
│       ▼                                          │
│  SubscriptionManager (event → subscriber map)    │
│       │                                          │
│       ▼                                          │
│  Server (UNIXServer + IO.select, timer 50ms)     │
│       │                                          │
└───────┼── /tmp/sketchup-link.sock (AF_UNIX) ────┘
        │              HTTP/1.1
        │    GET /model     → JSON snapshot
        │    GET /subscribe  → SSE (chunked NDJSON)
        │    GET /status     → subscription status
        ▼
┌─────────── Blender (Linux host) ────────────────┐
│                                                  │
│  _poll_loop (daemon thread, 2s interval)         │
│       │  GET /model → JSON dict                  │
│       ▼                                          │
│  queue.SimpleQueue                               │
│       │  _sync_timer drains, keeps latest        │
│       ▼                                          │
│  SceneImporter.load() (direct call, no bpy.ops)  │
│    ← duck-typed JsonModel/JsonFace/...           │
└──────────────────────────────────────────────────┘
```

**Key architectural decisions:**
- **Dual-language, dual-entrypoint**: Ruby runs inside SketchUp (Windows/macOS); Python runs inside Blender (cross-platform). The only interface between them is the Unix socket protocol.
- **Duck-typed adapter layer**: `live_adapter.py` in `blender_plugin/` provides `JsonModel`, `JsonFace`, `JsonGroup`, etc. classes that present the JSON socket response with the same interface as the Cython SLAPI bindings. This lets `SceneImporter.load()` work identically with both live JSON and native `.skp` files.
- **Event-driven with debounce**: Entity changes inside SketchUp transactions are batched until commit; direct edits are debounced (50ms timer). Selection, materials, and layers events fire immediately.
- **Poll-based live sync on Blender side**: A background daemon thread polls `GET /model` every 2s; the main-thread timer drains the queue (keeping only the most recent snapshot) and calls `SceneImporter.load()` directly (no `bpy.ops` round-trip).

## Key Directories

|Directory|Purpose|
|---|---|
|`sketchup_link/`|Ruby SketchUp plugin (server)|
|`blender_plugin/`|Python Blender addon (live sync + SKP import + Cython/Rust bindings)|
|`blender_plugin/slapi/`|Cython `.pxd` declaration files for SLAPI C headers|
|`blender_plugin/slapi_rs/`|Rust crate — alternative safe FFI wrapper for SLAPI via bindgen|
|`blender_plugin/headers/`|C header files for SketchUp SDK|
|`blender_plugin/libs/`|Platform-specific SketchUp SDK libraries|
|`tests/`|pytest integration tests|
|`integration/`|VM infrastructure (compose.yml, Dockerfile.blender, scripts)|
|`integration/scripts/`|VM orchestration (launch_sketchup.pl, install.bat, sketchup_launch_and_test.sh)|
|`../..` (monorepo root)|Crawled API reference (`docs/`), Docker VM state (`windows/`)|


## Development Commands

### Ruby / SketchUp Plugin

All Ruby commands run from the plugin project root:


```bash
# Install Ruby dependencies (rubyzip for packaging only — runtime uses stdlib)
bundle install

# Package the plugin for SketchUp Extension Manager
bundle exec ruby package.rb
# → dist/sketchup-link-1.0.0.rbz

# Root-level packaging alias (same result)
# Run from repo root:
bundle exec ruby package.rb
```

The plugin has **no runtime gem dependencies** — only `socket`, `json`, and `securerandom` from stdlib. The `rubyzip` gem is only needed to produce `.rbz` archives.

### Python / Blender Plugin

Python commands run from the plugin project root:


```bash
# Install Python deps (uv is the package manager)
uv sync

# Run tests
uv run pytest tests/ -v

# Run a single test file
uv run pytest tests/integration/test_blender_plugin.py -v

# Run a single test class
uv run pytest tests/integration/test_blender_plugin.py::TestJsonFace -v
```

Python 3.13+ required (see `.python-version`).

### Docker Development Environment

```bash
# Start Windows 11 VM with SketchUp
docker compose -f integration/compose.yml up -d


# Access via RDP (credentials: Docker / admin)
# Port 3389 for RDP, 8006 for web UI, 6123 for VS Code debug
# Socket path for live sync: /tmp/sketchup-link.sock (Linux) or %TEMP%\sketchup-link.sock (Windows)
```

### Building SDK Bindings (Optional)

From the repo root:

```bash
# Build Cython extension (requires SketchUp SDK)
make build-importer

# Rust crate build
make build-rust

# Requires SKETCHUP_SDK_PATH env var for Rust bindgen
```

## Runtime & Tooling

|Concern|Choice|
|---|---|
|Ruby (SketchUp)|Embedded SketchUp Ruby 2.x; no external gems|
|Python (Blender)|**3.13+**, `uv` package manager|
|Python dependency|`bpy>=5.1.0` (Blender Python API, type stubs only at test time)|
|Test framework|**pytest >=9.0.2**|
|Ruby test server|Pure stdlib Ruby (no gems), used as subprocess in tests|
|Ruby packaging|`rubyzip` gem via Bundler|
|IDE (Ruby)|RubyMine (`.idea/` present); VS Code for Python|
|Container runtime|Docker with `dockurr/windows`|
|Build (Cython)|`setuptools` + `Cython>=0.29.24`, C++ compiler|

## Code Conventions & Common Patterns

### Ruby (SketchUp Plugin)

**File layout:** Every `.rb` file begins with `# frozen_string_literal: true`.

**Module namespace:** `SketchupLink` is the top-level module. Sub-modules:
- `SketchupLink::Serializer` — `EntitySerializer`, `ModelSerializer`, `TransformSerializer`
- `SketchupLink::Observer` — `AppObserver`, `ModelObserver`, `EntitiesObserver`, `SelectionObserver`, `MaterialsObserver`, `LayersObserver`

**Singleton pattern:** `SketchupLink::PLUGIN` is a single `Plugin` instance, created in `main.rb`.

**Observer pattern:** Observers wrap SketchUp API observer interfaces and delegate to `EventDispatcher`. The `AppObserver` reattaches all model-level observers when a model is opened/created.

**Event dispatch:** `EventDispatcher` uses a transaction-depth counter for batching. Direct (non-transaction) entity edits are debounced via a 50ms `UI.start_timer`. Deduplication by `persistent_id`.

**Error handling:**
- `rescue nil` / bare `rescue` for best-effort cleanup (socket close, file delete)
- `rescue StandardError` for serializer fallbacks (returns partial/error dict)
- Guard clauses against deleted materials (`&.` safe navigation)

**Unit conversion:** All spatial data converted from **inches (SketchUp native) to meters** on the Ruby side before JSON emission. `INCHES_TO_METERS = 0.0254`.

**Transform format:** 16-element row-major flat array. SketchUp's `Transformation#to_a` returns column-major, so `TransformSerializer` transposes it and converts translation components (indices 3, 7, 11) to meters.

**Naming conventions:** CamelCase method names matching Cython interface (`GetOrientation`, `numInstances`, `numUsedInstances`) are preserved in the Python adapter with `# noqa: N802` comments. Ruby uses snake_case.

### Python (Blender Plugin)

**Duck-typing the Cython interface:** Every JSON wrapper class mirrors the Cython SLAPI binding class it replaces. Property names and method signatures match exactly. This is the key architectural pattern — `SceneImporter.load()` works without change on either data source.

**Property-based access:** JSON data is accessed via `@property` descriptors that read from a private `self._d` dict, never exposed directly.

**Hashing/equality:** `JsonLayer` implements `__eq__` and `__hash__` by name only (ignoring `visible`), because `layers_skip` uses set membership checks.

**`_NameOnly` stub:** A minimal class with just `.name` used for material and definition references where the full entity isn't needed.

**Live sync state management:** Module-level `_sync_state` dict holds thread, queue, stop event, socket path, and interval. `_poll_loop` (daemon thread) does blocking `GET /model` calls; `_sync_timer` (main-thread `bpy.app.timers` callback) drains the queue and calls `SceneImporter.load()` directly.

### Shared Patterns

**Transport:** HTTP/1.1 over AF_UNIX (`http.client.HTTPConnection` subclass overriding `connect()`). No external HTTP libraries used on either side.

**Socket path:** Platform-aware via `ENV['TEMP']` (Windows) / `ENV['TMP']` / `/tmp` (Unix). Test suite uses `-test.sock` suffix to avoid collisions.

**JSON format:** Snake_case keys from Ruby (`model_guid`, `persistent_id`, `back_material`). No version field in the protocol — both sides are versioned together.

## Important Files

### Ruby Plugin Entry Points
|File|Role|
|---|---|
|`sketchup_link.rb` (extension root)|Registers `SketchupExtension`, loads `main.rb`|
|`sketchup_link/main.rb`|Requires all modules, creates `SketchupLink::PLUGIN`|
|`sketchup_link/plugin.rb`|Orchestrator — creates Server, EventDispatcher, SubscriptionManager, attaches AppObserver|
|`sketchup_link/constants.rb`|Version (1.0.0), extension ID, timer interval, socket path, event type constants|
|`sketchup_link/server.rb`|Unix socket HTTP server — `IO.select` tick loop, `GET /model`, `GET /subscribe` (chunked SSE), `DELETE /unsubscribe`|
|`sketchup_link/event_dispatcher.rb`|Transaction batching, debounce timer, deduplication, event envelope formatting|
|`sketchup_link/subscription_manager.rb`|Subscriber registry, NDJSON dispatch, dead socket pruning|
|`sketchup_link/serializer/entity_serializer.rb`|Serializes Face (tessellation), Edge, Group, Instance, ComponentDefinition, Material, Layer|
|`sketchup_link/serializer/model_serializer.rb`|Full model snapshot: entities, materials, layers, component_definitions|
|`sketchup_link/serializer/transform_serializer.rb`|Column-major → row-major transpose with inch→meter conversion|

### Python Plugin Entry Points
|File|Role|
|---|---|
|`blender_plugin/__init__.py`|Package init, unified `register()`/`unregister()`|
|`blender_plugin/blender_manifest.toml`|Blender extension metadata (id: `sketchup_link`, min Blender 4.2.0, GPL-3.0)|
|`blender_plugin/live_adapter.py`|Transport + Json* adapter classes (pure Python, no Blender dep)|
|`blender_plugin/live_sync.py`|Live sync operators, panel, poll loop + timer|
|`blender_plugin/scene_importer.py`|`SceneImporter.load()` — shared import codepath|
|`blender_plugin/skp_util.py`|Component depth analysis, layer skipping, helper utilities|
|`blender_plugin/preferences.py`|`SketchupAddonPreferences`|
|`blender_plugin/sketchup.pyx`|Cython bindings to SketchUp SDK (optional, SDK-required)|
|`blender_plugin/slapi/`|Cython `.pxd` declaration files|
|`blender_plugin/slapi_rs/`|Rust crate — alternative safe FFI wrapper for SLAPI|
|`blender_plugin/headers/`|C headers for SketchUp SDK|
|`blender_plugin/libs/`|Platform-specific SketchUp SDK libraries|
|`blender_plugin/setup.py`|Cython build (moved from Sketchup_Importer)|
|`blender_plugin/pyproject.toml`|Cython build config (moved from Sketchup_Importer)|

### Config & Build
|File|Role|
|---|---|
|`pyproject.toml`|Python project metadata, deps (`bpy>=5.1.0`, `pytest>=9.0.2`), Python ≥3.13|
|`Gemfile`|Ruby dependency: `rubyzip`|
|`package.rb`|Builds `.rbz` extension archive|
	|`integration/compose.yml`|Docker Windows 11 VM, GPU passthrough, RDP/VS Code debug ports|
|`.python-version`|`3.13`|
|`.vscode/launch.json`|Ruby debug attachment config (remote 127.0.0.1:6123)|
|`.vscode/tasks.json`|SketchUp debug launch tasks|

## Cython / Rust SDK Bindings

The `blender_plugin/` directory contains the SketchUp SDK bindings merged from the former `Sketchup_Importer` project:

```
sketchup.pyx (Cython, 1074 lines)
   ↓ transpiles to
sketchup.cpp (~43K LOC C++)
   ↓ links against
libs/SketchUpAPI/SketchUpAPI.lib (proprietary SDK)
   ↓ wraps C API from
headers/SketchUpAPI/*.h (SketchUp SDK C headers)
```

Additionally, `slapi_rs/` provides a **Rust** crate with safe FFI wrappers via `bindgen`, offering RAII wrappers (`Model`, `Entities`, `GeometryInput`) with `Drop` implementations. This is an alternative/imminent replacement for the Cython bindings.

**Build requirements:** SketchUp SDK (proprietary, requires license). The Cython extension links `SketchUpAPI.lib` on Windows, `SketchUpAPI.framework` on macOS. Rust bindgen requires `SKETCHUP_SDK_PATH` env var.

**Loading without SDK:** The Cython extension is optional. `scene_importer.py` guards `from . import sketchup` with a `try/except ImportError`, setting a `_has_sketchup` flag. The addon loads fully for live-sync-only usage even when the extension isn't built.

## Testing & QA

### Test Structure

```
tests/
  integration/
    conftest.py              # Session-scoped fixtures
    server.rb                # Ruby mock HTTP-over-Unix-socket server (stdlib only)
    factories.rb             # Data factories generating structurally-fixed test model
    test_blender_plugin.py   # Test cases across 10 test classes
    test_blender_import.py   # Blender integration tests (requires Blender's bpy)
```

### How Tests Work
1. `conftest.py` spawns `server.rb` as a subprocess, waits for `"ready"` signal on stdout
2. `model_data` fixture fetches JSON from the mock server via `GET /model` (once per session)
3. `json_model` fixture wraps it in `JsonModel(…)` (once per session)
4. Individual test classes fetch sub-components from the shared `json_model`

The test model is structurally fixed but value-randomized: 2 faces, 2 materials, 3 layers, 1 group, 1 component instance with 1 definition. See `test_blender_plugin.py` module docstring for the exact structure.

### Running Tests

```bash
# Commands run from the plugin project root:

uv run pytest tests/ -v
```

Tests run **without Blender installed** — they import `blender_plugin.live_adapter` directly and validate the JSON adapter classes against known factory data. No `bpy` module is needed at test time.

### Test Coverage Expectations
- New adapter classes require test classes with structural validation (shape, types, invariants)
- New serialization fields require corresponding assertions
- Transport-level tests verify HTTP contract (required keys, error on bad path)

## Common Tasks for AI Assistants

**Adding a new entity property to live sync:**
1. Add serialization to `entity_serializer.rb` (Ruby side)
2. Add corresponding property to the relevant `Json*` class in `blender_plugin/live_adapter.py`
3. Add test assertions in `test_blender_plugin.py`
4. If `SceneImporter.load()` needs the new property, update `scene_importer.py`

**Adding a new event type:**
1. Define constant in `constants.rb`
2. Wire observer in appropriate `observer/*.rb` file
3. Add dispatch call in `event_dispatcher.rb`
4. Add event to `ALL_EVENTS` constant

**Debugging live sync:**
- Check socket exists: `ls -la /tmp/sketchup-link.sock`
- Test server manually: `python -c "from blender_plugin.live_adapter import fetch_model_json; print(fetch_model_json().keys())"`
- Check SketchUp plugin loaded: Look for "SketchUp Link" in Extension Manager
|- VS Code debugger: Attach to port 6123 (set in `integration/compose.yml` and `.vscode/launch.json`)
