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
