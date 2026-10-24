# ADR-0002: Standalone engine in an LXC, thin HACS integration, add-on as packaging later

Status: accepted · 2026-10-24

## Context
HA runs as HAOS (VM 105 `haos12.3`) on Proxmox node `teodor`, at 95 % memory. A Caddy LXC already fronts other services. The planner does LLM calls and long network sessions with Cookidoo and Migros, which must not run in HA's event loop.

## Decision
- Engine: Python 3.12+/FastAPI service in a Docker image, run in a new LXC on `teodor` behind Caddy.
- HA side: a thin HACS custom integration that talks HTTP to the engine and owns the entities, actions and notifications.
- Phase 6: wrap the same image as an HA add-on for HAOS households without a separate host. Not the primary deployment here.

## Consequences
- Memory pressure on the HAOS VM is not increased.
- The HA integration contains no business logic and is testable with `pytest-homeassistant-custom-component` against a fake engine.
- Two deployment paths to document (LXC, add-on); one image.
