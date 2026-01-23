from slowapi import Limiter
from slowapi.util import get_remote_address

# Initialize the global Limiter with 'get_remote_address' (client IP) as the key function
limiter = Limiter(key_func=get_remote_address)
