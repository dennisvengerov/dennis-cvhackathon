from dataclasses import dataclass

@dataclass
class User:
    """Represent a user account in the system."""
    user_id: str
    email: str
    is_active: bool = True

def is_valid_email(email: str) -> bool:
    """Check if an email contains a basic '@' character."""
    return "@" in email
