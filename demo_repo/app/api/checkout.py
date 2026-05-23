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
