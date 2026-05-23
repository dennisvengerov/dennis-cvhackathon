def format_currency(amount: float) -> str:
    """Format a float amount as USD currency string."""
    return f"${amount:,.2f}"

def calculate_tax(amount: float, rate: float = 0.08) -> float:
    """Calculate tax for a given amount and rate."""
    return round(amount * rate, 2)
