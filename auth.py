from fastapi import Depends, HTTPException, status

# Simulated user model
class User:
    def __init__(self, customer_id: int):
        self.customer_id = customer_id

# Dummy authentication dependency
def get_current_user():
    # Normally you'd decode a JWT or session token
    return User(customer_id=1)
