# HelloHacks Backend

FastAPI backend for checking whether recipe ingredients appear in a fridge photo. The API sends the image and recipe list to Gemini on Google Cloud Vertex AI; the Google service-account credential stays on the backend.

## Setup

Requirements: Python 3.10 or newer, a Google Cloud project with the Vertex AI API enabled, and a service account with permission to use Vertex AI.

The local `fridgebackend/keyapi.api` file should be the Google Cloud service-account JSON. Keep it private; it is ignored by Git and must never be bundled into the React Native app. In production, use your host's secret manager or workload identity instead of a local key file.

Copy the example settings and install dependencies from the repository root:

```powershell
Copy-Item fridgebackend/.env.example fridgebackend/fridgebackend.env
py -m pip install -r fridgebackend/requirements.txt
py -m uvicorn main:app --reload --app-dir fridgebackend --host 0.0.0.0 --port 8000
```

The API docs are available at `http://localhost:8000/docs`; the health check is `http://localhost:8000/health`.

## Check A Recipe

Send `multipart/form-data` to `POST /api/fridge/check` with:

- `image`: JPEG, PNG, or WebP, up to 10 MB
- `recipe_name`: recipe name
- `required_ingredients`: JSON array of ingredient names, optionally including amounts

Example response:

```json
{
	"recipe_name": "Omelet",
	"detected_ingredients": ["eggs", "spinach"],
	"ingredient_checks": [
		{"ingredient": "2 eggs", "status": "visible", "evidence": "Eggs are visible in the carton."},
		{"ingredient": "cheese", "status": "not_visible", "evidence": "No cheese is clearly visible."}
	],
	"can_cook": null,
	"shopping_list": ["cheese"],
	"recommendation": "Some ingredients were not visible. Check your pantry and containers before shopping.",
	"model_note": "Spinach is also visible.",
	"limitations": "A photo cannot confirm hidden items or exact quantities. Not visible does not mean you do not own it."
}
```

`can_cook` is `true` only when all required ingredients appear visible; otherwise it is `null` because a photo cannot prove an item is absent from a drawer, pantry, or opaque container. Treat `shopping_list` as items to check, not confirmed purchases.

From React Native, append the photo as a file object and send the other two fields as strings. Do not set the `Content-Type` header manually; `fetch` must add the multipart boundary. Use your computer's LAN address when testing on a physical phone, or the emulator's host address instead of `localhost`.

## Tests

```powershell
py -m pip install -r fridgebackend/requirements-dev.txt
py -m pytest fridgebackend/tests
```