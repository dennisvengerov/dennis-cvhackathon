from dataclasses import dataclass
from typing import Optional

@dataclass
class PaymentResult:
    """Result of a payment processing operation."""
    success: bool
    transaction_id: Optional[str] = None
    error_message: Optional[str] = None
