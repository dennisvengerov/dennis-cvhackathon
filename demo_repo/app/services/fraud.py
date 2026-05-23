from app.utils.logging import log_info, log_error

class FraudService:
    """Service to evaluate transaction risk levels."""

    def __init__(self, risk_threshold: float = 0.85):
        self.risk_threshold = risk_threshold

    def is_fraudulent_attempt(self, user_id: str, amount: float) -> bool:
        """Run standard rules to check if this purchase is highly risky."""
        log_info(f"Running fraud assessment for user {user_id} with amount {amount}")
        
        # High single transaction amount check
        if amount > 10000.0:
            log_error(f"Transaction rejected: amount {amount} exceeds safety limit.")
            return True
            
        # Simulating basic user-based block rules
        if user_id.startswith("fraud_"):
            log_error(f"Transaction rejected: User {user_id} matches known bad actor pattern.")
            return True
            
        return False
