from slowapi import Limiter
from slowapi.util import get_remote_address

# Inicializamos el Limiter globalmente con la key 'get_remote_address' (IP del cliente)
limiter = Limiter(key_func=get_remote_address)
