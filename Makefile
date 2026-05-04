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

.PHONY: test test-all
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
test-bdd:     ## Run BDD structural tests (no screenshots, CI-safe)
	uv run pytest tests/bdd/ -v --no-screenshots

test-bdd-screenshots:  ## Run BDD tests with screenshot capture
	uv run pytest tests/bdd/ -v

test-bdd-sketchup:  ## Launch SketchUp in VM, create test model, run screenshot tests
	./integration/scripts/sketchup_launch_and_test.sh


# ── Ruby (SketchUp plugin) ───────────────────────────────────────

.PHONY: install-ruby
install-ruby: ## Install Ruby gem dependencies (bundler)
	cd ../.. && bundle install

.PHONY: package dist
package:      ## Build the .rbz extension archive
dist:         ## Alias for package
	cd ../.. && bundle exec ruby package.rb

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

# Default target
.DEFAULT_GOAL := help
