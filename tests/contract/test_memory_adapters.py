"""The in-memory adapters pass the same contract suites every real adapter must pass."""

from datetime import date

import pytest

from znacht.domain.plan import Week
from znacht.planner import RuleBasedPlanner
from znacht.ports.planner import PlanningContext
from znacht.testing.contracts import (
    GroceryStoreContract,
    MealPlanSinkContract,
    NotifierContract,
    PlannerProviderContract,
    RecipeSourceContract,
    ReconciliationContract,
)
from znacht_memory import MemoryMealPlanSink, MemoryNotifier
from znacht_memory.fixtures import (
    IN_STORE_LIST,
    ONLINE_LIST,
    POSTCODE,
    grocery_store,
    recipe_source,
    recipes,
    rid,
)


class TestMemoryRecipeSource(RecipeSourceContract):
    @pytest.fixture
    def source(self):
        return recipe_source()

    @pytest.fixture
    def known_recipe_id(self, source):
        return rid("salmon-tray")


class TestMemoryMealPlanSink(MealPlanSinkContract):
    @pytest.fixture
    def sink(self):
        return MemoryMealPlanSink()

    @pytest.fixture
    def sample_recipe_id(self):
        return rid("salmon-tray")


class TestMemoryGroceryStore(GroceryStoreContract):
    @pytest.fixture
    def store(self):
        return grocery_store()

    @pytest.fixture
    def postcode(self):
        return POSTCODE

    @pytest.fixture
    def search_term(self):
        return "pasta"

    @pytest.fixture
    def list_id(self):
        return IN_STORE_LIST


class TestMemoryReconciliation(ReconciliationContract):
    @pytest.fixture
    def store(self):
        return grocery_store()

    @pytest.fixture
    def search_term(self):
        return "pasta"

    @pytest.fixture
    def online_list_id(self):
        return ONLINE_LIST

    @pytest.fixture
    def in_store_list_id(self):
        return IN_STORE_LIST


class TestRuleBasedPlanner(PlannerProviderContract):
    @pytest.fixture
    def planner(self):
        return RuleBasedPlanner()

    @pytest.fixture
    def context(self, household):
        return PlanningContext(
            household=household, week=Week(start=date(2026, 10, 26)), candidates=tuple(recipes())
        )


class TestMemoryNotifier(NotifierContract):
    @pytest.fixture
    def notifier(self):
        return MemoryNotifier()
