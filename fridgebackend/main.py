import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / "fridgebackend.env")

MAX_IMAGE_BYTES = 10 * 1024 * 1024
SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
logger = logging.getLogger(__name__)


class IngredientCheck(BaseModel):
    status: Literal["visible", "not_visible", "uncertain"]
    evidence: str


class GeminiAnalysis(BaseModel):
    detected_ingredients: list[str]
    ingredient_checks: list[IngredientCheck]
    note: str


class IngredientResult(BaseModel):
    ingredient: str
    status: Literal["visible", "not_visible", "uncertain"]
    evidence: str


class FridgeCheckResult(BaseModel):
    recipe_name: str
    detected_ingredients: list[str]
    ingredient_checks: list[IngredientResult]
    can_cook: bool | None
    shopping_list: list[str]
    recommendation: str
    model_note: str
    limitations: str


class GeminiConfigurationError(Exception):
    pass


@lru_cache(maxsize=1)
def get_gemini_client() -> genai.Client:
    credentials_path = Path(
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS", str(BASE_DIR / "keyapi.api"))
    )
    if not credentials_path.is_absolute():
        credentials_path = BASE_DIR / credentials_path

    if not credentials_path.is_file():
        raise GeminiConfigurationError("Google service-account file was not found")

    try:
        credentials_config = json.loads(credentials_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GeminiConfigurationError("Google service-account file is invalid") from error

    project_id = credentials_config.get("project_id")
    if credentials_config.get("type") != "service_account" or not project_id:
        raise GeminiConfigurationError("A Google Cloud service-account JSON file is required")

    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(credentials_path))
    return genai.Client(
        vertexai=True,
        project=project_id,
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
    )


def summarize_analysis(
    recipe_name: str,
    required_ingredients: list[str],
    analysis: GeminiAnalysis,
) -> FridgeCheckResult:
    if len(analysis.ingredient_checks) != len(required_ingredients):
        raise ValueError("Gemini returned a different number of ingredient checks")

    checks = [
        IngredientResult(
            ingredient=ingredient,
            status=check.status,
            evidence=check.evidence,
        )
        for ingredient, check in zip(required_ingredients, analysis.ingredient_checks)
    ]
    statuses = [check.status for check in checks]
    can_cook = True if all(status == "visible" for status in statuses) else None
    shopping_list = [
        check.ingredient for check in checks if check.status == "not_visible"
    ]

    if can_cook:
        recommendation = "The required ingredients appear visible. Check quantities before cooking."
    elif shopping_list:
        recommendation = (
            "Some ingredients were not visible. Check your pantry and containers before shopping."
        )
    else:
        recommendation = "Some ingredients are uncertain. Retake the photo or check them manually."

    return FridgeCheckResult(
        recipe_name=recipe_name,
        detected_ingredients=analysis.detected_ingredients,
        ingredient_checks=checks,
        can_cook=can_cook,
        shopping_list=shopping_list,
        recommendation=recommendation,
        model_note=analysis.note,
        limitations=(
            "A photo cannot confirm hidden items or exact quantities. "
            "Not visible does not mean you do not own it."
        ),
    )


def analyze_fridge(
    image_bytes: bytes,
    mime_type: str,
    recipe_name: str,
    required_ingredients: list[str],
) -> FridgeCheckResult:
    client = get_gemini_client()
    prompt = (
        f"Check this fridge photo for the recipe {recipe_name!r}. "
        f"Required ingredients, in order: {json.dumps(required_ingredients)}. "
        "List only ingredients you can identify in the image. For each required ingredient, "
        "return one check in the same order: use visible only when it is clearly identifiable "
        "and any stated amount is visually plausible; use not_visible when you cannot see it; "
        "use uncertain when the image is ambiguous or the amount cannot be judged. "
        "Do not assume items hidden in drawers, containers, or elsewhere are absent. "
        "Keep evidence brief and factual. Follow the response schema."
    )
    response = client.models.generate_content(
        model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            prompt,
        ],
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=GeminiAnalysis,
        ),
    )
    if not response.text:
        raise ValueError("Gemini returned an empty response")

    analysis = GeminiAnalysis.model_validate_json(response.text)
    return summarize_analysis(recipe_name, required_ingredients, analysis)


app = FastAPI(title="Fridge Ingredient Checker")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/fridge/check", response_model=FridgeCheckResult)
async def check_fridge(
    image: UploadFile = File(...),
    recipe_name: str = Form(..., min_length=1, max_length=120),
    required_ingredients: str = Form(
        ...,
        description='JSON array, for example ["2 eggs", "1 onion"]',
    ),
) -> FridgeCheckResult:
    if image.content_type not in SUPPORTED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Use a JPEG, PNG, or WebP image")

    image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image must be 10 MB or smaller")
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Image file is empty")

    try:
        ingredients = json.loads(required_ingredients)
    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=422,
            detail="required_ingredients must be a JSON array of strings",
        ) from error

    if (
        not isinstance(ingredients, list)
        or not ingredients
        or len(ingredients) > 40
        or any(
            not isinstance(item, str) or not item.strip() or len(item) > 120
            for item in ingredients
        )
    ):
        raise HTTPException(
            status_code=422,
            detail="Provide 1 to 40 non-empty ingredient names, each at most 120 characters",
        )

    recipe_name = recipe_name.strip()
    if not recipe_name:
        raise HTTPException(status_code=422, detail="recipe_name cannot be blank")

    try:
        return await run_in_threadpool(
            analyze_fridge,
            image_bytes,
            image.content_type,
            recipe_name,
            [item.strip() for item in ingredients],
        )
    except GeminiConfigurationError as error:
        raise HTTPException(
            status_code=503,
            detail="Gemini is not configured. Check the server's Google Cloud credentials.",
        ) from error
    except (ValidationError, ValueError) as error:
        logger.exception("Gemini returned an unusable fridge analysis")
        raise HTTPException(status_code=502, detail="Gemini returned an invalid analysis") from error
    except Exception as error:
        logger.exception("Gemini fridge analysis failed")
        raise HTTPException(status_code=502, detail="Gemini fridge analysis failed") from error