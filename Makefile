# osmPhone Makefile — Component IF-001.2
#
# Top-level build orchestration for all three processes:
#   osm-bt   (Swift)  — Bluetooth HFP helper
#   osm-core (Python) — AI/LLM backend
#   osm-ui   (Next.js) — Web frontend
#
# Quick start:
#   make install    # first-time: installs brew/pip/npm deps
#   make setup-bt   # first-time: enables HFP sink mode (needs reboot)
#   make dev        # starts all 3 processes
#   make test       # runs all test suites
#
# For development, run each process in its own terminal:
#   make dev-bt     # terminal 1
#   make dev-core   # terminal 2
#   make dev-ui     # terminal 3

.PHONY: help build build-bt build-core build-ui dev dev-bt dev-core dev-ui install test test-bt test-core test-ui clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ---- Build ----

build: build-bt build-core build-ui ## Build all components

build-bt: ## Build Swift Bluetooth helper
	cd osm-bt && swift build -c release

build-core: ## Install Python backend dependencies
	cd osm-core && pip install -e ".[all]"

build-ui: ## Build Next.js frontend
	cd osm-ui && npm install && npm run build

# ---- Dev ----

dev: ## Start all components in development mode (use scripts/launch.sh for production)
	@echo "Starting all osmPhone components..."
	@./scripts/launch.sh

dev-bt: ## Run Swift Bluetooth helper (debug)
	cd osm-bt && swift run OsmBT

dev-core: ## Run Python backend (debug)
	cd osm-core && python -m osm_core.main

dev-ui: ## Run Next.js frontend (dev server)
	cd osm-ui && npm run dev

# ---- Install ----

install: ## Install all system dependencies
	@./scripts/install.sh

setup-bt: ## Enable HFP sink mode on macOS (requires reboot)
	@./scripts/enable-hfp-sink.sh

# ---- Test ----

test: test-bt test-core test-ui ## Run all tests

test-bt: ## Run Swift tests
	cd osm-bt && swift test

test-core: ## Run Python tests
	cd osm-core && python -m pytest tests/ -v

test-ui: ## Run frontend tests
	cd osm-ui && npm test

# ---- Clean ----

clean: ## Clean all build artifacts
	cd osm-bt && swift package clean
	cd osm-core && rm -rf build dist *.egg-info
	cd osm-ui && rm -rf .next node_modules
	rm -f /tmp/osmphone.sock
