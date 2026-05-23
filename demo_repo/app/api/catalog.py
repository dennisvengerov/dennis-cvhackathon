from app.utils.logging import log_info

def list_products() -> list:
    """List all products available in the store catalog."""
    log_info("Fetching product catalog")
    return [
        {"item_id": "item_101", "name": "Standard Widget", "price": 10.99},
        {"item_id": "item_202", "name": "Premium Gadget", "price": 99.99},
        {"item_id": "item_303", "name": "Out-of-Stock Item", "price": 5.00}
    ]
