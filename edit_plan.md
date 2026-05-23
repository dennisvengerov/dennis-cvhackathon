# Edit Plan & Task Routing Report

### Selected Files & Nodes
- `F6 src/routers/ui_routes.py`: This file contains the `create_checkout_session` endpoint (N21), which is the primary target for adding request validation before payment processing.
- `N21 src.routers.ui_routes::create_checkout_session`: This asynchronous function is the core of the task, as validation must be integrated directly into its execution flow.
- `F7 src/schemas.py`: This module (N50) is the designated location for defining Pydantic models, which are essential for structured request validation.
- `N50 src.schemas::<module>`: This module node represents the `schemas.py` file, where a new Pydantic model for the checkout request will be defined.

### Selected Dependency Path
`create_checkout_session` (N21) -> `src.schemas` (N50 for defining new CheckoutRequest schema)

*Detailed flow:*
1.  A client request arrives at the `create_checkout_session` endpoint (N21).
2.  FastAPI automatically performs validation of the request body against the `CheckoutRequest` Pydantic model (defined in N50) provided as a dependency in the function signature.
3.  If validation passes, the `create_checkout_session` function proceeds with its logic, utilizing the validated data from the `checkout_request` object.
4.  Payment processing via `stripe.checkout.Session.create` is initiated with the validated data.
5.  If validation fails, FastAPI automatically returns a `422 Unprocessable Entity` error before the function body is executed.

### Proposed Edit Plan

#### 1. Define a new Pydantic schema for the checkout request
**File**: `F7 src/schemas.py` (Node `N50 src.schemas::<module>`)

**Changes**:
*   **Add a new Pydantic model**: Define a `CheckoutRequest` class that inherits from `BaseModel`. This model will specify the expected fields and their types for the request body of the checkout endpoint.
*   **Reasoning**: This provides a clear, structured, and self-documenting way to define the input contract for the `create_checkout_session` endpoint, allowing FastAPI to perform automatic validation.

**Example Snippet (Illustrative - exact fields depend on requirements)**:
```python
# src/schemas.py

from pydantic import BaseModel
from typing import Optional

# ... other schemas like ProductBase might exist ...

class CheckoutRequest(BaseModel):
    product_id: str
    quantity: int
    coupon_code: Optional[str] = None # Example of an optional field
    # Add any other fields expected in the checkout request body
```

#### 2. Integrate the new schema into the checkout endpoint for validation
**File**: `F6 src/routers/ui_routes.py` (Node `N21 src.routers.ui_routes::create_checkout_session`)

**Changes**:
*   **Import the new schema**: Add an import statement at the top of the file to bring `CheckoutRequest` into scope.
*   **Modify function signature**: Update `create_checkout_session` to accept `checkout_request: CheckoutRequest` as a parameter. FastAPI will automatically parse and validate the request body against this Pydantic model.
*   **Update internal logic**: Adjust the function's implementation to use the attributes of `checkout_request` (e.g., `checkout_request.product_id`, `checkout_request.quantity`) instead of directly parsing `request.json()` or relying on the `path` parameter for product details if those are now part of the body. The existing `path` parameter can remain if it's a distinct route parameter.

**Pre-conditions**:
*   The incoming HTTP POST/PUT request body for `/create-checkout-session/{path}/` must conform to the structure defined by `CheckoutRequest`.

**Validations**:
*   FastAPI, using Pydantic, will automatically validate the `checkout_request` parameter. If the request body does not match the `CheckoutRequest` schema (e.g., missing required fields, incorrect types), a `422 Unprocessable Entity` HTTP error will be returned without executing the function's body.

**Business Logic**:
*   Once `checkout_request` is successfully validated and available, the existing logic for `stripe.checkout.Session.create` should be modified to use the clean, validated data from `checkout_request`.
    *   For example, instead of `item_id = request.json().get("item_id")`, it would become `item_id = checkout_request.product_id`.

**Post-conditions and Side Effects**:
*   If validation passes, the function proceeds to create a Stripe checkout session, potentially leading to external API calls (`stripe.checkout.Session.create`), `db_write` operations, and payment processing, as indicated by the node's original side effects.
*   If validation fails, an error response is returned to the client immediately.

**Handling Errors**:
*   Pydantic/FastAPI handles validation errors automatically, raising an `HTTPException` (specifically a `RequestValidationError` which FastAPI converts to a `422` response). No explicit `try-except` block is typically needed for basic schema validation within the function body itself.

**Example Snippet (Illustrative - full source is needed for precise modification)**:
```python
# src/routers/ui_routes.py

from fastapi import APIRouter, Request, HTTPException
# ... other imports ...
from src.schemas import CheckoutRequest # NEW IMPORT

# ... router setup ...

@router.post("/create-checkout-session/{path}/")
async def create_checkout_session(
    path: str, # Existing path parameter
    checkout_request: CheckoutRequest, # NEW: Pydantic model for body validation
    request: Request # Existing request object
):
    try:
        # Before: Potentially parsing request.json()
        # Now: Use validated checkout_request object directly
        # Example: Retrieve product_id and quantity from the validated request body
        product_id = checkout_request.product_id
        quantity = checkout_request.quantity

        # The 'path' parameter might be used to fetch more product details or for routing
        # Example: product_url = app.product_router.url_path_for("get_product", product_id=product_id)
        # Using the product_id from the validated body for internal logic
        
        # Original logic using path for example, adapt to use product_id from body
        # For demonstration, assuming 'path' might be a generic identifier and product_id is in body
        # If 'path' *is* the product ID, the schema should reflect that and remove product_id from body or rename 'path'.
        
        # Logic to fetch product details (if needed) based on product_id
        # http3client = http3.AsyncClient()
        # response = await http3client.get(f"http://localhost:8000/products/{product_id}")
        # product_data = response.json()

        # ... then use product_data and validated checkout_request for Stripe session ...

        # Example of using validated data for Stripe session creation
        # stripe.checkout.Session.create(
        #     line_items=[
        #         {
        #             'price_data': {
        #                 'currency': 'usd',
        #                 'product_data': {'name': product_data['name']},
        #                 'unit_amount': product_data['price'],
        #             },
        #             'quantity': quantity,
        #         },
        #     ],
        #     mode='payment',
        #     success_url=f"{request.base_url}success",
        #     cancel_url=f"{request.base_url}cancel",
        # )

        return {"message": "Checkout session initiated successfully"}

    except HTTPException:
        raise # Re-raise if it's an intended HTTPException
    except Exception as e:
        # Log error
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")
```

### Snippets Needed / Full Source Requests

-   **N21 `src.routers.ui_routes::create_checkout_session`**: Full source code is required to:
    1.  Modify its function signature to include the `CheckoutRequest` Pydantic model.
    2.  Update the internal logic to utilize the validated `checkout_request` object's attributes instead of direct request parsing.
    3.  Ensure existing `request` object usages (e.g., `request.base_url`) are preserved.
-   **N50 `src.schemas::<module>`**: Full source code for the `src/schemas.py` module is required to define the new `CheckoutRequest` Pydantic class.