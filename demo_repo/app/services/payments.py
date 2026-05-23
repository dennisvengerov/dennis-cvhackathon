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
