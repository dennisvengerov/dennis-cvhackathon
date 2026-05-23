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
