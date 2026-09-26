from fastapi.testclient import TestClient

from fridgebackend.main import (
    FridgeCheckResult,
    GeminiAnalysis,
    IngredientCheck,
    app,
    summarize_analysis,
)


def test_all_visible_ingredients_allow_cooking() -> None:
    analysis = GeminiAnalysis(
        detected_ingredients=["eggs", "spinach"],
        ingredient_checks=[
            IngredientCheck(status="visible", evidence="Eggs are visible."),
            IngredientCheck(status="visible", evidence="Spinach is visible."),
        ],
        note="Both ingredients appear in the photo.",
    )

    result = summarize_analysis("Omelet", ["eggs", "spinach"], analysis)

    assert result.can_cook is True
    assert result.shopping_list == []


def test_not_visible_ingredient_is_not_claimed_absent() -> None:
    analysis = GeminiAnalysis(
        detected_ingredients=["eggs"],
        ingredient_checks=[
            IngredientCheck(status="visible", evidence="Eggs are visible."),
            IngredientCheck(status="not_visible", evidence="Cheese is not visible."),
        ],
        note="Check other storage before shopping.",
    )

    result = summarize_analysis("Omelet", ["eggs", "cheese"], analysis)

    assert result.can_cook is None
    assert result.shopping_list == ["cheese"]
    assert "before shopping" in result.recommendation


def test_uncertain_ingredient_does_not_create_shopping_item() -> None:
    analysis = GeminiAnalysis(
        detected_ingredients=[],
        ingredient_checks=[
            IngredientCheck(status="uncertain", evidence="The container is opaque."),
        ],
        note="The photo is unclear.",
    )

    result = summarize_analysis("Pasta", ["sauce"], analysis)

    assert result.can_cook is None
    assert result.shopping_list == []
    assert "uncertain" in result.recommendation


def test_check_endpoint_rejects_unsupported_image_type() -> None:
    client = TestClient(app)

    response = client.post(
        "/api/fridge/check",
        files={"image": ("notes.txt", b"not an image", "text/plain")},
        data={
            "recipe_name": "Omelet",
            "required_ingredients": '["eggs"]',
        },
    )

    assert response.status_code == 415