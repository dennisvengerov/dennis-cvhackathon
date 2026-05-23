

# File: app/api/checkout.py
## Context: Lines 1-40 (Full File (Tiny File))
```python
from app.models.checkout import CheckoutRequest
from app.services.inventory import InventoryService
from app.services.fraud import FraudService
from app.services.payments import PaymentService
from app.utils.logging import log_info, log_error

def checkout_endpoint(request: CheckoutRequest) -> dict:
    """Submit a checkout request, verify stock, assess fraud risk, and capture payment."""
    log_info(f"Received checkout request for user {request.user_id}")

    # 1. Verify stock for each item
    inventory_service = InventoryService()
    for item in request.items:
        item_id = item.get("item_id", "")
        quantity = item.get("quantity", 1)
        if not inventory_service.check_stock(item_id, quantity):
            log_error(f"Stock check failed for item {item_id}")
            return {"success": False, "error": "OutOfStock"}

    # 2. Risk check
    fraud_service = FraudService()
    if fraud_service.is_fraudulent_attempt(request.user_id, request.amount):
        log_error(f"Fraud check rejected for user {request.user_id}")
        return {"success": False, "error": "FraudRejected"}

    # 3. Process payment
    payment_service = PaymentService()
    result = payment_service.process_payment(request.user_id, request.amount)
    
    if not result.success:
        log_error(f"Payment failed: {result.error_message}")
        return {"success": False, "error": "PaymentFailed", "details": result.error_message}

    # 4. Success Response
    log_info(f"Checkout completed successfully for user {request.user_id}")
    return {
        "success": True,
        "transaction_id": result.transaction_id,
        "amount": request.amount
    }

```

---

# File: tests/test_checkout.py
## Context: Lines 1-24 (Full File (Tiny File))
```python
from app.models.checkout import CheckoutRequest
from app.api.checkout import checkout_endpoint

def test_successful_checkout():
    """Test that a standard valid request goes through successfully."""
    req = CheckoutRequest(
        user_id="alice",
        items=[{"item_id": "item_101", "quantity": 2}],
        amount=21.98
    )
    response = checkout_endpoint(req)
    assert response["success"] is True
    assert "transaction_id" in response

def test_out_of_stock_checkout():
    """Test that ordering an out-of-stock item returns stock failure."""
    req = CheckoutRequest(
        user_id="bob",
        items=[{"item_id": "item_303", "quantity": 1}],
        amount=5.00
    )
    response = checkout_endpoint(req)
    assert response["success"] is False
    assert response["error"] == "OutOfStock"

```

---

# File: app/services/payments.py
## Context: Lines 1-24 (Full File (Tiny File))
```python
import uuid
from app.models.payment import PaymentResult
from app.utils.logging import log_info, log_error
from app.utils.money import format_currency

class PaymentService:
    """Service to process charges against payment gateways."""

    def __init__(self, provider_name: str = "Stripe"):
        self.provider_name = provider_name

    def process_payment(self, user_id: str, amount: float) -> PaymentResult:
        """Process payment through the remote provider gateway."""
        formatted = format_currency(amount)
        log_info(f"Processing charge of {formatted} for user {user_id} via {self.provider_name}")
        
        if amount <= 0.0:
            log_error(f"Cannot process charge for invalid amount {amount}")
            return PaymentResult(success=False, error_message="Invalid payment amount")

        # Simulate remote API call success
        transaction_id = str(uuid.uuid4())
        log_info(f"Payment successful. Transaction ID: {transaction_id}")
        return PaymentResult(success=True, transaction_id=transaction_id)

```

---

# File: app/services/inventory.py
## Context: Lines 1-29 (Full File (Tiny File))
```python
from app.utils.logging import log_info, log_error

class InventoryService:
    """Service to handle stock checks and inventory allocations."""

    def __init__(self):
        # Simulated database for stock quantities
        self.stock_db = {
            "item_101": 50,
            "item_202": 5,
            "item_303": 0
        }

    def check_stock(self, item_id: str, quantity: int) -> bool:
        """Check if inventory has sufficient stock for the requested quantity."""
        log_info(f"Checking stock for {item_id}, quantity {quantity}")
        available = self.stock_db.get(item_id, 0)
        if available >= quantity:
            return True
        log_error(f"Insufficient stock for {item_id}: available {available}, requested {quantity}")
        return False

    def allocate_stock(self, item_id: str, quantity: int) -> bool:
        """Reserve/allocate stock in the inventory."""
        if self.check_stock(item_id, quantity):
            self.stock_db[item_id] -= quantity
            log_info(f"Successfully allocated {quantity} units of {item_id}")
            return True
        return False

```

---

# File: app/utils/validation.py
## Context: Lines 1-14 (Full File (Tiny File))
```python
from app.models.checkout import CheckoutRequest

def validate_checkout_request(request: CheckoutRequest) -> bool:
    """Validate that the checkout request is complete and correct.
    
    Checks that user_id is non-empty, has items, and amount is positive.
    """
    if not request.user_id:
        return False
    if not request.has_items():
        return False
    if request.amount <= 0.0:
        return False
    return True

```

---

# File: app/models/checkout.py
## Context: Lines 1-14 (Full File (Tiny File))
```python
from dataclasses import dataclass, field
from typing import List, Dict

@dataclass
class CheckoutRequest:
    """Request payload containing user and cart details for checkout."""
    user_id: str
    items: List[Dict[str, int]] = field(default_factory=list)
    amount: float = 0.0
    payment_method: str = "credit_card"

    def has_items(self) -> bool:
        """Helper to check if there are any items in the checkout request."""
        return len(self.items) > 0

```

---

# File: app/models/payment.py
## Context: Lines 1-9 (Full File (Tiny File))
```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class PaymentResult:
    """Result of a payment processing operation."""
    success: bool
    transaction_id: Optional[str] = None
    error_message: Optional[str] = None

```