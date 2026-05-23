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
