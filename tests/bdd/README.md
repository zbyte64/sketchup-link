# BDD Test Suite for SketchUp Link

Behavior-Driven Development tests using `pytest-bdd` + Gherkin `.feature` files.

## Overview

The BDD suite validates the SketchUp → Blender live sync round-trip using
Gherkin scenarios that describe the system behavior in plain language.

**Two modes:**

| Mode | Command | What it does |
|---|---|---|
| CI (no screenshots) | `uv run pytest tests/bdd/ -v --no-screenshots` | Fetches JSON from Ruby mock server, asserts against JsonModel adapters |
| Full (with screenshots) | `make test-bdd-screenshots` | Drives SketchUp via RDP, imports into Blender headless, captures renders |

## Running

### Prerequisites (CI mode)

- Ruby (for the mock server)
- Python 3.13+ with `uv`
- Dependencies installed: `uv sync`

### Prerequisites (Full mode)

- Docker Windows 11 VM running with SketchUp Pro
- SketchUp Link plugin installed in the VM
- `agent-rdp` installed and configured
- Blender (with `bpy`) installed host-side
- Test `.skp` model at `C:\shared\test_model.skp` inside the VM

### Run commands

```bash
# From shared/project/ext/sketchup-link/

# CI-safe mode (structural assertions only)
uv run pytest tests/bdd/ -v --no-screenshots

# Run a single feature with CI-safe mode
uv run pytest tests/bdd/ -v --no-screenshots -k "live_sync"

# Full mode with screenshots (requires VM)
uv run pytest tests/bdd/ -v

# Or from repo root via Make
make test-bdd
make test-bdd-screenshots
```

## Architecture

```
tests/bdd/
├── features/                         # Gherkin .feature files
│   ├── live_sync.feature             # Sync workflows
│   └── geometry_fidelity.feature     # Data correctness checks
├── step_defs/                        # pytest-bdd step implementations
│   ├── __init__.py
│   ├── conftest.py                   # BDD-specific fixtures
│   ├── test_sketchup_steps.py        # "Given SketchUp..." steps
│   ├── test_blender_steps.py         # "Then Blender..." steps
│   └── test_live_sync_steps.py       # "When sync..." steps
├── conftest.py                       # Top-level fixtures (server, model data, screenshots)
├── screenshots/                      # Output directory (gitignored except .gitkeep)
│   └── .gitkeep
├── run_blender_assertions.py         # Blender headless entry point
├── test_live_sync_scenarios.py       # Scenario runner for live_sync.feature
└── test_geometry_fidelity_scenarios.py # Scenario runner for geometry_fidelity.feature
```

## Test Model

The suite reuses the existing golden test model structure from
`tests/integration/factories.rb`:

- **2 faces** (Red front material, Blue back material)
- **2 materials** (Red[220,20,20], Blue[20,20,200])
- **3 layers** (Layer0[visible], Furniture[visible], Hidden[invisible])
- **1 group** (FurnitureGroup with face + edge children)
- **1 component instance** (Chair with 1 definition containing 2 faces)

## Writing New Scenarios

1. Add a scenario to an existing `.feature` file or create a new one
2. Implement the step definitions in the appropriate `step_defs/` module
3. Create a scenario runner `test_*.py` file that imports the feature
4. Add assertions following the CI-mode pattern (assert against JSON model)

### Step definition modules

| Module | Purpose |
|---|---|
| `test_sketchup_steps.py` | Given/When steps for SketchUp state and actions |
| `test_blender_steps.py` | Then steps validating imported model state |
| `test_live_sync_steps.py` | Orchestration steps bridging SketchUp and Blender |

## CI vs Full Mode

The `--no-screenshots` flag controls mode:

- **CI mode** (`--no-screenshots`): Steps fetch model JSON from the Ruby
  mock server (same as existing integration tests) and assert against the
  JsonModel adapter classes. No Blender, no Docker VM needed.
- **Full mode** (no flag): Steps drive SketchUp via RDP automation and spawn
  Blender headless to run `SceneImporter.load()`. Screenshots captured for
  manual review.

## Adding a New Step Definition

In the appropriate `step_defs/*.py` module:

```python
from pytest_bdd import given, when, then

@given('some condition')
def step_implementation(request):
    ...

@when('I do something')
def step_implementation(request):
    ...

@then('some outcome occurs')
def step_implementation(request):
    ...
```

The step function name does not matter; pytest-bdd matches by the string
pattern. All step modules are imported by the scenario runner files.
