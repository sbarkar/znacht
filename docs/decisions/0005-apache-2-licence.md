# ADR-0005: Apache-2.0 licence

Status: accepted · 2026-10-24

## Context
Mealie, KitchenOwl and myMeal are AGPL-3.0. Znacht is an engine plus adapters that third parties should be able to ship as separate packages, and a HACS integration that HA users install without thinking about licences. The project wants a community of adapter authors, including people who might wrap commercial store APIs.

## Decision
Apache-2.0 for every package in the repository. Contributions are accepted under the same licence (no CLA; the Apache-2.0 inbound=outbound default applies).

## Consequences
- Adapter packages can be published under any licence their authors choose, including proprietary ones; the ports stay open.
- No copyleft pressure on HA users or on households running it privately.
- Explicit patent grant for contributors and users.
- We cannot vendor AGPL code from Mealie or myMeal, nor PolyForm-Shield code from swissgroceries-mcp. Endpoint facts are fine; code is not.
