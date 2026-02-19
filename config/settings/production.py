from .base import *  # noqa
from decouple import config, Csv

# base.py: DEBUG no está definido (cada ambiente lo define)
# production.py: DEBUG = False → nunca exponer stack traces al usuario final
DEBUG = False

# base.py: ALLOWED_HOSTS no está definido (depende del dominio real)
# production.py: viene de variable de entorno para que el servidor solo responda
#                a los dominios legítimos y rechace requests con Host header falso
ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv())

# --- WhiteNoise: archivos estáticos sin Nginx separado ---
# WhiteNoise debe ir justo después de SecurityMiddleware para interceptar
# los requests de archivos estáticos antes que cualquier otro middleware.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Comprime y cachea los archivos estáticos automáticamente
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# --- Seguridad HTTPS ---
# Ninguna de estas opciones existe en base.py ni local.py porque en local
# no corremos HTTPS. Se activan solo en producción donde sí hay un certificado.

# TODO: activar cuando HTTPS esté configurado con Certbot/Let's Encrypt
# Redirige automáticamente cualquier request HTTP → HTTPS a nivel Django.
SECURE_SSL_REDIRECT = False

# Le dice al browser que la cookie de sesión solo se envíe en conexiones HTTPS.
# Sin esto, la cookie podría viajar en texto plano por una conexión HTTP accidental.
SESSION_COOKIE_SECURE = True

# Igual que SESSION_COOKIE_SECURE pero para la cookie del token CSRF.
# Protege contra que el token sea interceptado en conexiones no cifradas.
CSRF_COOKIE_SECURE = True

# HSTS (HTTP Strict Transport Security): le indica al browser que durante
# 31536000 segundos (1 año) SIEMPRE use HTTPS para este dominio,
# incluso si el usuario escribe "http://...". Evita ataques de downgrade.
SECURE_HSTS_SECONDS = 31536000

# Extiende la política HSTS a todos los subdominios del dominio.
# Ej: si el dominio es miapp.com, también fuerza HTTPS en api.miapp.com, etc.
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
