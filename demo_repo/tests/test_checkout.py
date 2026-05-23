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
