from .base import *  # noqa
from decouple import config, Csv

DEBUG = False

# En producción ALLOWED_HOSTS viene de variable de entorno, ej: "miapp.com,www.miapp.com"
ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv())

# Seguridad HTTPS
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
