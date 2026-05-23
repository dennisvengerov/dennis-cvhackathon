from app.models.user import User, is_valid_email
from app.utils.logging import log_info, log_error

def register_user(email: str, username: str) -> dict:
    """Register a new user in the system after validating email format."""
    log_info(f"Attempting registration for {email}")
    if not is_valid_email(email):
        log_error(f"Invalid email: {email}")
        return {"success": False, "error": "InvalidEmail"}
        
    user = User(user_id=username, email=email)
    log_info(f"User {user.user_id} registered successfully.")
    return {"success": True, "user_id": user.user_id}
