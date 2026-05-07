# sketchup-link — top-level development Makefile
#
# Most commands dispatch into shared/project/ext/sketchup-link/
# (the primary project root for both the Ruby SketchUp plugin and
# Python Blender addon). The Cython/Rust SDK bindings now live
# inside blender_plugin/ under the main project root.

RUBY_PLUGIN    = .
BLENDER_PLUGIN = blender_plugin
RUST_MANIFEST  = $(BLENDER_PLUGIN)/slapi_rs/Cargo.toml
DOCKER_COMPOSE = integration/compose.yml
SKP_SDK       ?= $(SKETCHUP_SDK_PATH)

# ── Python (Blender addon) ────────────────────────────────────────

.PHONY: install
install:      ## Install Python dependencies (uv sync)
	uv sync

.PHONY: test test-unit test-all
test-unit:    ## Run unit tests only (fast, CI-safe)
	uv run pytest tests/unit/ -v

test:         ## Run all Python tests (pytest)
	uv run pytest tests/ -v $(ARGS)

test-all:     ## Same as `test` (alias for forwards-compat with --strict-markers)
	$(MAKE) test ARGS="$(ARGS)"

.PHONY: test-file test-class test-single
test-file:    ## Run a single test file  usage: make test-file FILE=<path>
	uv run pytest tests/$(FILE) -v
test-class:   ## Run a single test class usage: make test-class FILE=<path> CLASS=<ClassName>
	uv run pytest tests/$(FILE)::$(CLASS) -v
test-single:  ## Run a single test      usage: make test-single FILE=<path> TEST=<test_name>
	uv run pytest tests/$(FILE)::$(TEST) -v

.PHONY: test-blender
test-blender: ## Run Blender integration tests (headless, requires flatpak org.blender.Blender)
	flatpak run org.blender.Blender --background --python $(abspath tests/integration/run_blender_tests.py)

.PHONY: test-bdd test-bdd-screenshots test-bdd-sketchup
test-bdd: clean-pyc     ## Run BDD structural tests (no screenshots, CI-safe)
	uv run pytest tests/bdd/ -v --no-screenshots

test-bdd-screenshots:  ## Run BDD tests with screenshot capture
	uv run pytest tests/bdd/ -v

test-bdd-sketchup:  ## Launch SketchUp in VM, create test model, run screenshot tests
	./integration/shared/scripts/sketchup_launch_and_test.sh

#
# ── Version management ────────────────────────────────────────────
#

.PHONY: version-check
version-check: ## Validate all version references match the canonical VERSION file
	@V=$$(cat VERSION | tr -d '\n'); \
	RB=$$(grep -A0 "VERSION\s*=" sketchup_link/constants.rb | sed "s/.*'\(.*\)'.*/\1/"); \
	PY=$$(grep "^version " blender_plugin/pyproject.toml | sed 's/version = "\(.*\)"/\1/'); \
	MF=$$(grep "^version " blender_plugin/blender_manifest.toml | sed 's/version = "\(.*\)"/\1/'); \
	ALL_OK=true; \
	if [ "$$V" != "$$RB" ]; then echo "MISMATCH: VERSION=$$V, constants.rb=$$RB"; ALL_OK=false; fi; \
	if [ "$$V" != "$$PY" ]; then echo "MISMATCH: VERSION=$$V, pyproject.toml=$$PY"; ALL_OK=false; fi; \
	if [ "$$V" != "$$MF" ]; then echo "MISMATCH: VERSION=$$V, blender_manifest.toml=$$MF"; ALL_OK=false; fi; \
	$$ALL_OK || (echo "Version mismatch! Run 'make set-version VERSION=x.y.z' to fix."; exit 1); \
	if $$ALL_OK; then echo "All version references match: $$V"; fi

.PHONY: set-version
set-version: ## Set a new version across all files  usage: make set-version VERSION=x.y.z
	@if [ -z "$(VERSION)" ]; then echo "Usage: make set-version VERSION=x.y.z"; exit 1; fi; \
	echo "$(VERSION)" > VERSION; \
	python3 scripts/stamp_version.py; \
	perl -i -pe "s/(VERSION\s*=\s*')[^']*(')/\1$(VERSION)\2/" sketchup_link/constants.rb; \
	echo "Version set to $(VERSION)"; \
	$(MAKE) version-check

# ── Ruby (SketchUp plugin) ───────────────────────────────────────

.PHONY: install-ruby
install-ruby: ## Install Ruby gem dependencies (bundler)
	cd ../.. && bundle install

.PHONY: package dist
package:      ## Build the .rbz extension archive
	bundle exec ruby package.rb

dist: package  ## Alias for package

#
# ── Python addon packaging (Blender extension) ───────────────────
#

.PHONY: package-python
package-python: ## Build the .zip extension archive for Blender
	@V=$$(cat VERSION | tr -d '\n'); \
	OUT="dist/sketchup_link-$${V}.zip"; \
	mkdir -p dist; \
	rm -f "$$OUT"; \
	cd blender_plugin && \
	zip -r "../$$OUT" \
		__init__.py \
		blender_manifest.toml \
		live_adapter.py \
		live_sync.py \
		log_config.py \
		preferences.py \
		scene_importer.py \
		skp_util.py; \
	echo "Created: $$OUT"

.PHONY: release
release: version-check package package-python ## Run version-check, package, and package-python sequentially
# ── Docker (Windows 11 VM for SketchUp) ──────────────────────────

.PHONY: docker-up docker-down docker-restart docker-logs
docker-up:    ## Start the Windows 11 VM (Docker Compose)
	docker compose -f $(DOCKER_COMPOSE) up -d
docker-down:  ## Stop the Windows 11 VM
	docker compose -f $(DOCKER_COMPOSE) down
docker-restart: ## Restart the Windows 11 VM
	docker compose -f $(DOCKER_COMPOSE) restart
docker-logs:  ## Tail VM logs (follow)
	docker compose -f $(DOCKER_COMPOSE) logs -f

# ── Cython SLAPI extension (blender_plugin/sketchup.pyx) ───────

.PHONY: build-importer
build-importer: ## Build the Cython extension in-place
	cd $(BLENDER_PLUGIN) && python setup.py build_ext --inplace

# ── Rust slapi_rs (blender_plugin/slapi_rs) ────────────────────

.PHONY: build-rust
build-rust:   ## Build the Rust slapi_rs crate
	cd $(BLENDER_PLUGIN) && cargo build --manifest-path $(RUST_MANIFEST)

# ── Utility ──────────────────────────────────────────────────────

.PHONY: clean
clean:        ## Remove Python/Ruby/Cargo build artifacts
	rm -rf ../../dist/
	rm -rf .pytest_cache __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	cd $(BLENDER_PLUGIN) && rm -rf build/ sketchup.cpp *.so *.egg-info .pytest_cache 2>/dev/null || true
	cd $(BLENDER_PLUGIN) && cargo clean --manifest-path $(RUST_MANIFEST) 2>/dev/null || true
.PHONY: clean-pyc
clean-pyc:     ## Remove all __pycache__ directories under tests/
	find tests/ -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

.PHONY: info
info:         ## Show project metadata and paths
	@echo "Ruby plugin:   $(RUBY_PLUGIN)"
	@echo "Blender addon: $(BLENDER_PLUGIN)"
	@echo "Rust crate:    $(RUST_MANIFEST)"
	@echo "Docker compose: $(DOCKER_COMPOSE)"
	@echo "Python:        $(shell python3 --version 2>/dev/null || echo 'not found')"
	@echo "Ruby:          $(shell ruby --version 2>/dev/null || echo 'not found')"
	@echo "Cargo:         $(shell cargo --version 2>/dev/null || echo 'not found')"
	@echo "uv:            $(shell uv --version 2>/dev/null || echo 'not found')"
	@echo "Docker:        $(shell docker compose version 2>/dev/null || echo 'not found')"
	@echo "SketchUp SDK:  $(SKP_SDK)"
.PHONY: help
help:         ## Show this help
	@grep -Eh '^[a-zA-Z_-]+:.*?## .+$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Fuzz Testing ────────────────────────────────────────────────────

.PHONY: test-fuzz test-fuzz-mock test-fuzz-single
test-fuzz:      ## Run fuzz tests against real SketchUp VM
	./integration/scripts/run-fuzz.sh
test-fuzz-mock: ## Run fuzz tests against Ruby mock server (CI-safe)
	uv run pytest tests/fuzz/ -v --fuzz-mock
test-fuzz-single: ## Run a single mutation strategy  usage: make test-fuzz-single STRATEGY=<name>
	uv run pytest tests/fuzz/ -v --fuzz-mock -k "$(STRATEGY)"
# Default target
.DEFAULT_GOAL := help
