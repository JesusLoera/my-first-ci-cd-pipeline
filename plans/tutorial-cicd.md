# Tutorial: CI/CD con Django + GitHub Actions + DigitalOcean

Este tutorial te guía paso a paso para montar un pipeline de CI/CD completo desde cero.
Al terminar tendrás: tests automáticos en cada PR, deploy automático a staging al mergear
a `develop`, y deploy a producción al mergear a `main`.

---

## Stack

| Capa | Tecnología |
|------|-----------|
| Aplicación | Django 5.1 + Django REST Framework |
| Base de datos | PostgreSQL 18 (separada de la app) |
| Contenedores local | Docker + docker-compose |
| Contenedores producción | Docker + docker-compose (misma imagen que local) |
| Registry de imágenes | DigitalOcean Container Registry (DOCR) |
| Control de versiones | Git + GitHub |
| CI | GitHub Actions — tests + build + push imagen |
| CD | GitHub Actions → SSH → docker pull → restart |
| Servidor WSGI | Gunicorn (dentro del contenedor) |
| Archivos estáticos | WhiteNoise (dentro del contenedor, sin Nginx separado) |
| Infraestructura | 2 Droplets Ubuntu + Managed PostgreSQL |

## Prerequisitos

- Python 3.12+ instalado localmente
- Docker Desktop instalado
- Git configurado
- Cuenta en GitHub
- Cuenta en DigitalOcean con método de pago

## Estrategia de ramas

```
main        → deploy automático a producción
develop     → deploy automático a staging
feature/*   → PRs hacia develop, CI corre los tests
```

La regla de oro: **nunca se hace push directo a `main` ni a `develop`**. Todo pasa por Pull Request con CI verde.

---

## Fase 1 — Estructura local con Docker

**Objetivo:** proyecto Django corriendo localmente con Docker y PostgreSQL separada.

### 1.1 Crear el proyecto

```bash
mkdir my_first_ci_cd_pipeline
cd my_first_ci_cd_pipeline
git init
git checkout -b develop   # develop es la rama principal de trabajo
```

Estructura de directorios a crear:

```
my_first_ci_cd_pipeline/
├── apps/
│   └── todos/
│       ├── migrations/
│       ├── tests/
│       ├── __init__.py
│       ├── apps.py
│       ├── models.py
│       ├── serializers.py
│       ├── urls.py
│       └── views.py
├── config/
│   ├── settings/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── local.py
│   │   └── production.py
│   ├── __init__.py
│   ├── asgi.py
│   ├── urls.py
│   └── wsgi.py
├── requirements/
│   ├── base.txt
│   ├── local.txt
│   └── production.txt
├── .env
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
└── manage.py
```

### 1.2 Requirements

`requirements/base.txt` — dependencias de producción:
```
Django==5.1.6
djangorestframework==3.15.2
psycopg2-binary==2.9.10
python-decouple==3.8
gunicorn==23.0.0
```

`requirements/local.txt` — extiende base con herramientas de dev:
```
-r base.txt

# Herramientas de desarrollo (no se instalan en producción)
ruff==0.9.9
```

`requirements/production.txt`:
```
-r base.txt
```

> **Por qué separar requirements:** `ruff` es un linter que solo necesitas en desarrollo.
> Instalarlo en producción agrega peso innecesario a la imagen de producción.

### 1.3 Settings por ambiente

El patrón es: `base.py` tiene todo lo común, cada ambiente hereda y agrega lo suyo.

`config/settings/base.py`:
```python
from pathlib import Path
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("SECRET_KEY")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    # Local apps
    "apps.todos",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("POSTGRES_DB"),
        "USER": config("POSTGRES_USER"),
        "PASSWORD": config("POSTGRES_PASSWORD"),
        "HOST": config("POSTGRES_HOST"),
        "PORT": config("POSTGRES_PORT", default="5432"),
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 10,
}
```

`config/settings/local.py`:
```python
from .base import *  # noqa

DEBUG = True
ALLOWED_HOSTS = ["*"]
```

`config/settings/production.py`:
```python
from .base import *  # noqa
from decouple import config, Csv

# base.py: DEBUG no está definido (cada ambiente lo define)
# production.py: DEBUG = False → nunca exponer stack traces al usuario final
DEBUG = False

# base.py: ALLOWED_HOSTS no está definido (depende del dominio real)
# production.py: viene de variable de entorno para que el servidor solo responda
#                a los dominios legítimos y rechace requests con Host header falso
ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv())

# --- Seguridad HTTPS ---
# Ninguna de estas opciones existe en base.py ni local.py porque en local
# no corremos HTTPS. Se activan solo en producción donde sí hay un certificado.

# Redirige automáticamente cualquier request HTTP → HTTPS a nivel Django.
# En producción esto lo suele hacer nginx, pero tenerlo en Django es una capa extra.
SECURE_SSL_REDIRECT = True

# Le dice al browser que la cookie de sesión solo se envíe en conexiones HTTPS.
SESSION_COOKIE_SECURE = True

# Igual que SESSION_COOKIE_SECURE pero para la cookie del token CSRF.
CSRF_COOKIE_SECURE = True

# HSTS: indica al browser que durante 1 año SIEMPRE use HTTPS para este dominio.
SECURE_HSTS_SECONDS = 31536000

# Extiende la política HSTS a todos los subdominios.
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
```

### 1.4 La app de Todos

`apps/todos/apps.py`:
```python
from django.apps import AppConfig

class TodosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.todos"
    # name = "apps.todos" → label automático = "todos" → tabla = "todos_todo"
```

`apps/todos/models.py`:
```python
from django.db import models

class Todo(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title
```

`apps/todos/serializers.py`:
```python
from rest_framework import serializers
from .models import Todo

class TodoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Todo
        fields = ["id", "title", "description", "completed", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]
```

`apps/todos/views.py`:
```python
from rest_framework import viewsets
from .models import Todo
from .serializers import TodoSerializer

class TodoViewSet(viewsets.ModelViewSet):
    queryset = Todo.objects.all()
    serializer_class = TodoSerializer
```

`apps/todos/urls.py`:
```python
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TodoViewSet

router = DefaultRouter()
router.register(r"todos", TodoViewSet)

urlpatterns = [path("", include(router.urls))]
```

`config/urls.py`:
```python
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.todos.urls")),
]
```

### 1.5 Variables de entorno

`.env.example` (va a git — es documentación):
```
DJANGO_SETTINGS_MODULE=config.settings.local
SECRET_KEY=your-secret-key-here-change-in-production
POSTGRES_DB=todos_db
POSTGRES_USER=todos_user
POSTGRES_PASSWORD=todos_password
POSTGRES_HOST=db
POSTGRES_PORT=5432
```

`.env` (NO va a git — valores reales locales):
```
DJANGO_SETTINGS_MODULE=config.settings.local
SECRET_KEY=django-insecure-cambia-esto-en-produccion
POSTGRES_DB=todos_db
POSTGRES_USER=todos_user
POSTGRES_PASSWORD=todos_password
POSTGRES_HOST=db
POSTGRES_PORT=5432
```

`.gitignore` debe incluir al menos:
```
.env
__pycache__/
*.pyc
staticfiles/
.DS_Store
```

### 1.6 Docker

`Dockerfile`:
```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# IMPORTANTE: copiar TODA la carpeta requirements/, no solo local.txt
# local.txt hace "-r base.txt" → si base.txt no está, el build falla
COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/local.txt

COPY . .

EXPOSE 8000
```

`docker-compose.yml`:
```yaml
services:
  # Base de datos PostgreSQL — servicio separado de la aplicación
  db:
    image: postgres:18-alpine
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "5432:5432"
    healthcheck:
      # IMPORTANTE: incluir -d ${POSTGRES_DB}
      # Sin -d, pg_isready usa el nombre de usuario como nombre de DB y falla
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 5

  # Aplicación Django
  web:
    build: .
    command: python manage.py runserver 0.0.0.0:8000
    volumes:
      - .:/app
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy

volumes:
  postgres_data:
```

### 1.7 Generar migraciones y levantar

```bash
# Construir y levantar el stack
docker compose up --build

# En otra terminal: generar la migración inicial
# IMPORTANTE: hacer esto ANTES de correr los tests
docker compose exec web python manage.py makemigrations todos

# Aplicar migraciones
docker compose exec web python manage.py migrate

# Correr los tests
docker compose exec web python manage.py test apps.todos
```

> **Diferencia clave:** `makemigrations` genera el *archivo* de migración (va a git).
> `migrate` *ejecuta* ese archivo contra la base de datos (operación runtime).
> El archivo generado debe commitearse para que todos los ambientes puedan aplicarlo.

### 1.8 Tests

`apps/todos/tests/test_models.py`:
```python
from django.test import TestCase
from apps.todos.models import Todo

class TodoModelTest(TestCase):
    def test_create_todo_with_defaults(self):
        todo = Todo.objects.create(title="Aprender CI/CD")
        self.assertEqual(todo.title, "Aprender CI/CD")
        self.assertFalse(todo.completed)
        self.assertEqual(todo.description, "")

    def test_str_returns_title(self):
        todo = Todo.objects.create(title="Mi tarea")
        self.assertEqual(str(todo), "Mi tarea")

    def test_completed_can_be_toggled(self):
        todo = Todo.objects.create(title="Tarea pendiente")
        todo.completed = True
        todo.save()
        todo.refresh_from_db()
        self.assertTrue(todo.completed)

    def test_ordering_by_created_at_desc(self):
        Todo.objects.create(title="Primero")
        Todo.objects.create(title="Segundo")
        todos = Todo.objects.all()
        self.assertEqual(todos[0].title, "Segundo")
        self.assertEqual(todos[1].title, "Primero")
```

`apps/todos/tests/test_api.py`:
```python
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from apps.todos.models import Todo

class TodoAPITest(APITestCase):
    def setUp(self):
        self.todo = Todo.objects.create(
            title="Todo inicial",
            description="Descripción de prueba",
        )

    def test_list_todos_returns_200(self):
        url = reverse("todo-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_todos_contains_created_todo(self):
        url = reverse("todo-list")
        response = self.client.get(url)
        titles = [item["title"] for item in response.data["results"]]
        self.assertIn("Todo inicial", titles)

    def test_create_todo_returns_201(self):
        url = reverse("todo-list")
        data = {"title": "Nuevo todo", "description": "Nueva descripción"}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_todo_persists_in_db(self):
        url = reverse("todo-list")
        data = {"title": "Persistido", "description": ""}
        self.client.post(url, data, format="json")
        self.assertEqual(Todo.objects.count(), 2)

    def test_create_todo_without_title_returns_400(self):
        url = reverse("todo-list")
        response = self.client.post(url, {"description": "Sin título"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_retrieve_todo_returns_200(self):
        url = reverse("todo-detail", args=[self.todo.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Todo inicial")

    def test_retrieve_nonexistent_todo_returns_404(self):
        url = reverse("todo-detail", args=[9999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_todo_marks_as_completed(self):
        url = reverse("todo-detail", args=[self.todo.id])
        data = {"title": "Todo inicial", "description": "Descripción de prueba", "completed": True}
        response = self.client.put(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.todo.refresh_from_db()
        self.assertTrue(self.todo.completed)

    def test_partial_update_only_title(self):
        url = reverse("todo-detail", args=[self.todo.id])
        response = self.client.patch(url, {"title": "Título actualizado"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.todo.refresh_from_db()
        self.assertEqual(self.todo.title, "Título actualizado")

    def test_delete_todo_returns_204(self):
        url = reverse("todo-detail", args=[self.todo.id])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_delete_todo_removes_from_db(self):
        url = reverse("todo-detail", args=[self.todo.id])
        self.client.delete(url)
        self.assertEqual(Todo.objects.count(), 0)
```

### 1.9 Git inicial

```bash
# Primer commit en develop
git add .
git commit -m "feat: estructura inicial del proyecto con Django y Docker"

# Crear rama main y sincronizar
git checkout -b main
git checkout develop
```

### Errores comunes en Fase 1

| Error | Causa | Solución |
|-------|-------|----------|
| `could not open requirements file: base.txt` | Dockerfile solo copia `local.txt` pero no `base.txt` | Cambiar `COPY requirements/local.txt` a `COPY requirements/ requirements/` |
| `FATAL: database "todos_user" does not exist` | Healthcheck sin `-d` usa el nombre de usuario como DB | Agregar `-d ${POSTGRES_DB}` al comando `pg_isready` |
| `relation "todos_todo" does not exist` | Se corrieron los tests sin haber hecho `makemigrations` | Ejecutar `makemigrations todos` y luego `migrate` antes de los tests |

---

## Fase 2 — CI con GitHub Actions

**Objetivo:** cada push o PR ejecuta tests automáticamente en GitHub.

### 2.1 Crear el repositorio en GitHub

```bash
# Desde GitHub.com: crear repo (recomendado: público para branch protection gratis)
git remote add origin https://github.com/tu-usuario/tu-repo.git
git push origin develop
git push origin main
```

> **Tip:** Para que GitHub Actions pueda crear o modificar archivos `.github/workflows/`,
> necesitas que tu token tenga el scope `workflow`. Si recibes error al hacer push, ejecuta:
> ```bash
> gh auth refresh -s workflow
> ```

### 2.2 El workflow de CI

Crea el archivo `.github/workflows/ci.yml`:

```yaml
# ============================================================
# Workflow de CI — Integración Continua
# ============================================================
# Se ejecuta en cada push o Pull Request hacia main o develop.
# Si algún paso falla, el workflow falla y bloquea el merge
# (cuando la protección de ramas está configurada en GitHub).
# ============================================================

name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  test:
    name: Linting y pruebas
    runs-on: ubuntu-latest

    # GitHub Actions puede levantar servicios Docker junto al runner.
    # Usamos esto en lugar de docker-compose: es más rápido porque
    # no necesitamos construir nuestra propia imagen para correr los tests.
    services:
      postgres:
        image: postgres:18-alpine
        env:
          POSTGRES_DB: todos_db
          POSTGRES_USER: todos_user
          POSTGRES_PASSWORD: todos_password
        ports:
          - 5432:5432
        # El runner espera a que postgres esté listo antes de continuar
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    # Variables de entorno disponibles en todos los pasos del job.
    # Estas reemplazan al archivo .env que usamos en local.
    # Nota: SECRET_KEY aquí es solo para CI — no es un secret real.
    env:
      DJANGO_SETTINGS_MODULE: config.settings.local
      SECRET_KEY: ci-secret-key-only-for-testing-not-real
      POSTGRES_DB: todos_db
      POSTGRES_USER: todos_user
      POSTGRES_PASSWORD: todos_password
      # En el runner, el servicio postgres es accesible en localhost,
      # no en "db" como en docker-compose.
      POSTGRES_HOST: localhost
      POSTGRES_PORT: 5432

    steps:
      # 1. Descargar el código del repositorio al runner
      - name: Checkout del código
        uses: actions/checkout@v4

      # 2. Instalar Python con cache de pip para acelerar ejecuciones futuras.
      #    El cache se invalida automáticamente si cambia local.txt.
      - name: Configurar Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"
          cache-dependency-path: requirements/local.txt

      # 3. psycopg2 necesita libpq-dev para compilarse en Linux
      - name: Instalar dependencias del sistema
        run: sudo apt-get install -y libpq-dev

      # 4. Instalar dependencias Python (Django, DRF, ruff, etc.)
      - name: Instalar dependencias Python
        run: pip install -r requirements/local.txt

      # 5. Linting: ruff revisa errores de sintaxis y estilo.
      #    Si hay un error real, el CI falla aquí antes de perder
      #    tiempo corriendo los tests.
      - name: Linting con ruff
        run: ruff check .

      # 6. Verificar que todos los modelos tienen su migración generada.
      #    Si alguien modifica un modelo pero olvida hacer makemigrations,
      #    este paso falla y avisa antes de llegar a producción.
      - name: Verificar migraciones pendientes
        run: python manage.py makemigrations --check --dry-run

      # 7. Aplicar las migraciones a la base de datos de CI
      - name: Aplicar migraciones
        run: python manage.py migrate

      # 8. Correr los tests con salida detallada
      - name: Correr pruebas
        run: python manage.py test apps.todos --verbosity=2
```

### 2.3 Diferencias importantes: CI vs local

| Aspecto | Local (docker-compose) | CI (GitHub Actions) |
|---------|----------------------|-------------------|
| Host de postgres | `db` (nombre del servicio) | `localhost` |
| Variables de entorno | Archivo `.env` | Sección `env:` del workflow |
| Versión postgres | `postgres:18-alpine` | `postgres:18-alpine` (debe coincidir) |

### 2.4 Protección de ramas en GitHub

Para que el CI sea **obligatorio** antes de hacer merge:

1. Ir a **Settings → Branches → Add classic branch protection rule**
2. Branch name pattern: `main`
3. Activar: **Require a pull request before merging**
4. Activar: **Require status checks to pass before merging**
   - Buscar y seleccionar el check: `Linting y pruebas`
   - Activar: "Require branches to be up to date before merging"
5. Click **Create**
6. Repetir para `develop`

> **Nota:** La protección de ramas en repos privados requiere plan de pago (GitHub Team).
> Si tu repo es privado y estás en el plan gratuito, hazlo público — es un proyecto de aprendizaje
> sin datos sensibles. Las credenciales reales irán en GitHub Secrets (Fase 4).

### 2.5 Flujo de trabajo con PRs

**Nunca hacer push directo a `main` o `develop`.**

El flujo correcto:

```
1. Crear rama de feature
   git checkout -b feature/mi-funcionalidad

2. Desarrollar y commitear
   git add .
   git commit -m "feat: agregar mi funcionalidad"

3. Push de la rama
   git push origin feature/mi-funcionalidad

4. Crear PR en GitHub: feature/mi-funcionalidad → develop
5. CI corre automáticamente (~40 segundos)
6. Con CI verde: aprobar y mergear (Squash and merge recomendado)
7. Al mergear a develop → CI corre en develop también
8. Cuando develop está listo: PR de develop → main
9. Al mergear a main → CD deploya a producción (Fase 4)
```

**Tipos de merge en GitHub:**

| Estrategia | Cuándo usarla |
|---|---|
| Merge commit | Cuando quieres preservar todo el historial de commits del PR |
| **Squash and merge** | Cuando los commits intermedios son "WIP" o "fix typo" — un PR = un commit limpio |
| Rebase and merge | Equipos que quieren historial lineal estricto |

### Errores comunes en Fase 2

| Error | Causa | Solución |
|-------|-------|----------|
| `refusing to allow an OAuth App to create or update workflow` | Token sin scope `workflow` | `gh auth refresh -s workflow` |
| El check no aparece en el buscador de branch protection | `main` nunca tuvo un CI run | Hacer push a main primero, esperar que corra CI, luego configurar la protección |
| `postgres:18-alpine` no existe | Versión muy nueva o typo | Verificar en hub.docker.com que existe el tag exacto |

---

## Fase 3 — Infraestructura en DigitalOcean

**Objetivo:** dos servidores reales en la nube con base de datos separada.

### 3.1 Por qué separar la base de datos del servidor

```
❌ Mal:  [Droplet: app + postgres]   → si cae el droplet, pierdes datos
✅ Bien: [Droplet: app] → [Managed DB]  → escalado y backup independientes
```

El Managed PostgreSQL de DigitalOcean incluye: backups automáticos diarios, réplicas,
failover automático, y actualizaciones de seguridad gestionadas.

### 3.2 Crear el Managed PostgreSQL

En DigitalOcean: **Databases → Create Database**

| Campo | Valor |
|-------|-------|
| Engine | PostgreSQL 18 (o la versión más reciente disponible) |
| Plan | Basic — 1 GB RAM / 1 vCPU / 15 GB |
| Datacenter | New York 3 (o el más cercano a ti) |
| Nombre | `todos-db` (solo es una etiqueta visual) |

> **Consistencia de versiones:** usa la misma versión de PostgreSQL en DigitalOcean,
> en `docker-compose.yml` (`image: postgres:18-alpine`) y en `ci.yml`. Si cambias
> la versión en DigitalOcean, actualiza los otros dos archivos también.

Después de crear el cluster, crear las dos bases de datos:
- **db-name:** `todos_staging`
- **db-name:** `todos_production`

### 3.3 Crear los Droplets

**Droplet de staging:**

| Campo | Valor |
|-------|-------|
| OS | Ubuntu 24.04 LTS |
| Plan | Basic Regular → **$6/mes** (1 vCPU, 1 GB RAM, 25 GB SSD) |
| Datacenter | **Mismo que el cluster PostgreSQL** |
| Authentication | SSH Key (ver sección 3.4) |
| Opciones adicionales | Activar "Metrics monitoring" (gratis) |
| Hostname | `todos-staging` |

> **Por qué no el plan de $4:** 512 MB RAM no es suficiente. Ubuntu al arrancar consume
> ~200-250 MB, Django + Gunicorn consume otros ~150-200 MB. Sin headroom, los `pip install`
> durante el deploy pueden matar el proceso por falta de memoria (OOM killer).

Repetir para producción con hostname `todos-production`.

> **Región:** los tres recursos (cluster + 2 droplets) deben estar en la misma región.
> Dentro de la misma región, la comunicación va por la red privada de DigitalOcean
> (sub-milisegundo, sin costo de transferencia). Entre regiones: internet público + latencia alta.

### 3.4 SSH Keys

Verificar si ya tienes una llave SSH:
```bash
ls ~/.ssh/*.pub
```

Si no tienes, generar una:
```bash
ssh-keygen -t ed25519 -C "tu-email@ejemplo.com"
```

Agregar la llave pública al Droplet durante su creación:
- Click "New SSH Key" en el panel de DigitalOcean
- Pegar el contenido de `~/.ssh/id_rsa.pub` (o `id_ed25519.pub`)

Una vez creado el Droplet, conectarte así:
```bash
ssh root@<IP_DEL_DROPLET>
```

### 3.5 Crear el DigitalOcean Container Registry (DOCR)

El registry es el almacén donde se guardan las imágenes Docker. El CI construye
la imagen y la sube aquí; el Droplet la baja desde aquí en cada deploy.

En DigitalOcean: **Container Registry → Create Registry**

| Campo | Valor |
|-------|-------|
| Nombre | `todos-registry` (o el que prefieras) |
| Plan | Starter — **Gratis** hasta 500 MB |
| Datacenter | El mismo que los Droplets (NYC3) |

Después de crear el registry, anota el nombre del endpoint. Tendrá esta forma:
```
registry.digitalocean.com/todos-registry
```

> **500 MB es suficiente para este proyecto.** Una imagen Django básica con sus
> dependencias pesa ~200-350 MB. Si el proyecto crece y supera ese límite, el plan
> Basic cuesta $5/mes con 5 GB.

### 3.6 Configurar fuentes confiables en PostgreSQL

En DigitalOcean: **tu-cluster → Settings → Trusted sources**

Agregar ambos droplets como fuentes confiables. DigitalOcean los detecta automáticamente
si están en el mismo proyecto y región. Esto hace que la conexión vaya por la **red privada**
sin exponerse a internet.

### 3.7 Preparar la imagen Docker para producción

El enfoque Docker en producción usa **la misma imagen que en desarrollo** —
esa consistencia es el gran beneficio de Docker.

Agregar `whitenoise` a `requirements/base.txt` para servir archivos estáticos
sin necesitar Nginx separado:
```
whitenoise==6.9.0
```

Activar WhiteNoise en `config/settings/production.py`:
```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # justo después de SecurityMiddleware
    # ... resto del middleware
]

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
```

Crear `docker-compose.prod.yml` en la raíz del proyecto:
```yaml
services:
  web:
    image: registry.digitalocean.com/<DOCR_REGISTRY>/todos:${TAG:-latest}
    command: >
      sh -c "python manage.py migrate --no-input &&
             python manage.py collectstatic --no-input &&
             gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2"
    env_file: .env
    ports:
      - "80:8000"
    restart: unless-stopped
```

> **Por qué `sh -c` con múltiples comandos:** el contenedor ejecuta migrate y
> collectstatic antes de levantar Gunicorn. Así el deploy nunca sirve la nueva
> versión con las migraciones pendientes.

> **Por qué no Nginx separado:** esta app es una REST API pura (solo JSON).
> WhiteNoise sirve los archivos estáticos del Django Admin directamente desde
> Gunicorn, sin necesidad de un proxy separado. Para apps con mucho tráfico de
> assets estáticos, se añadiría Nginx o un CDN.

### 3.8 Preparar los Droplets

Ejecutar en **cada** Droplet (conectado por SSH):

```bash
# Actualizar el sistema
apt-get update && apt-get upgrade -y

# Instalar Docker
curl -fsSL https://get.docker.com | sh

# Verificar instalación
docker --version
docker compose version
```

Crear el directorio de la app y el archivo de configuración:
```bash
mkdir -p /opt/todos
```

Crear el archivo `.env` en el servidor con los datos reales:
```bash
cat > /opt/todos/.env << 'EOF'
DJANGO_SETTINGS_MODULE=config.settings.production
SECRET_KEY=<genera-una-key-aleatoria-segura>
POSTGRES_DB=todos_staging
POSTGRES_USER=<usuario-del-cluster-digitalocean>
POSTGRES_PASSWORD=<password-del-cluster-digitalocean>
POSTGRES_HOST=<hostname-vpc-del-cluster>
POSTGRES_PORT=25060
ALLOWED_HOSTS=<ip-del-droplet>
EOF
```

> **Cómo obtener el hostname VPC:** en DigitalOcean, en la página del cluster
> PostgreSQL → Connection details → selecciona "VPC network". El hostname
> empieza con `private-`. Siempre usar este hostname para que el tráfico no
> salga a internet.

Copiar `docker-compose.prod.yml` al servidor (o hacerlo via CD automáticamente):
```bash
# Desde tu máquina local
scp docker-compose.prod.yml root@<IP_DROPLET>:/opt/todos/
```

Autenticar Docker en el DOCR para que el Droplet pueda hacer pull de imágenes:
```bash
# En el Droplet — usar el mismo token de DO que se configura en GitHub Secrets
echo "<DOCR_TOKEN>" | docker login registry.digitalocean.com -u "<DOCR_TOKEN>" --password-stdin
```

> **El DOCR_TOKEN es un Personal Access Token de DigitalOcean** con scope de
> lectura/escritura en el registry. Se genera en API → Generate New Token.

Verificar que todo está en su lugar:
```bash
ls /opt/todos/
# debe mostrar: .env  docker-compose.prod.yml
```

---

## Fase 4 — CD automatizado

**Objetivo:** merge a `develop` → deploy a staging. Merge a `main` → deploy a producción.

### 4.1 Secrets en GitHub

Antes de crear los workflows de CD, agregar los secrets en **Settings → Secrets and variables → Actions**:

| Secret | Valor |
|--------|-------|
| `STAGING_HOST` | IP del droplet de staging (ej: `45.55.156.142`) |
| `PRODUCTION_HOST` | IP del droplet de producción (ej: `174.138.57.232`) |
| `SSH_PRIVATE_KEY` | Contenido completo de `~/.ssh/id_rsa` (la llave privada) |
| `DOCR_TOKEN` | Personal Access Token de DigitalOcean con acceso al registry |
| `DOCR_REGISTRY` | Nombre del registry (ej: `todos-registry`) |
| `STAGING_DB` | `todos_staging` |
| `PRODUCTION_DB` | `todos_production` |
| `POSTGRES_USER` | Usuario del cluster DigitalOcean |
| `POSTGRES_PASSWORD` | Password del cluster DigitalOcean |
| `POSTGRES_HOST` | Hostname VPC del cluster (empieza con `private-`) |
| `STAGING_DJANGO_SECRET_KEY` | Secret key para staging |
| `PRODUCTION_DJANGO_SECRET_KEY` | Secret key para producción |

> **Generar SECRET_KEY seguras (una diferente para staging y otra para producción):**
> ```bash
> python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
> ```

> **Generar el DOCR_TOKEN:** en DigitalOcean → API → Generate New Token.
> Nombre: `github-actions`. Scopes: lectura y escritura en registry.
> En el login de Docker, el token se usa tanto como username como password.

### 4.2 Workflow de CD — Staging

`.github/workflows/cd-staging.yml`:
```yaml
name: CD — Staging

on:
  push:
    branches: [develop]

jobs:
  build-and-deploy:
    name: Build, push y deploy a staging
    runs-on: ubuntu-latest

    steps:
      - name: Checkout del código
        uses: actions/checkout@v4

      # Autenticar en DOCR para poder hacer push de la imagen
      - name: Login al DigitalOcean Container Registry
        uses: docker/login-action@v3
        with:
          registry: registry.digitalocean.com
          username: ${{ secrets.DOCR_TOKEN }}
          password: ${{ secrets.DOCR_TOKEN }}

      # Construir la imagen y subirla al registry con dos tags:
      # - staging-latest: siempre apunta a la última versión de staging
      # - staging-<sha>: tag inmutable para rollback si es necesario
      - name: Build y push de imagen Docker
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: |
            registry.digitalocean.com/${{ secrets.DOCR_REGISTRY }}/todos:staging-latest
            registry.digitalocean.com/${{ secrets.DOCR_REGISTRY }}/todos:staging-${{ github.sha }}

      # SSH al droplet de staging para bajar la nueva imagen y reiniciar
      - name: Deploy en staging
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.STAGING_HOST }}
          username: root
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          envs: DOCR_TOKEN,DOCR_REGISTRY
          script: |
            # Autenticar Docker en el registry
            echo "$DOCR_TOKEN" | docker login registry.digitalocean.com -u "$DOCR_TOKEN" --password-stdin

            # Bajar la nueva imagen
            docker pull registry.digitalocean.com/$DOCR_REGISTRY/todos:staging-latest

            # Actualizar la variable TAG y reiniciar el contenedor
            cd /opt/todos
            TAG=staging-latest docker compose -f docker-compose.prod.yml up -d

            # Limpiar imágenes viejas para liberar espacio
            docker image prune -f
        env:
          DOCR_TOKEN: ${{ secrets.DOCR_TOKEN }}
          DOCR_REGISTRY: ${{ secrets.DOCR_REGISTRY }}
```

### 4.3 Workflow de CD — Producción

`.github/workflows/cd-production.yml`:
```yaml
name: CD — Producción

on:
  push:
    branches: [main]

jobs:
  build-and-deploy:
    name: Build, push y deploy a producción
    runs-on: ubuntu-latest

    steps:
      - name: Checkout del código
        uses: actions/checkout@v4

      - name: Login al DigitalOcean Container Registry
        uses: docker/login-action@v3
        with:
          registry: registry.digitalocean.com
          username: ${{ secrets.DOCR_TOKEN }}
          password: ${{ secrets.DOCR_TOKEN }}

      - name: Build y push de imagen Docker
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: |
            registry.digitalocean.com/${{ secrets.DOCR_REGISTRY }}/todos:latest
            registry.digitalocean.com/${{ secrets.DOCR_REGISTRY }}/todos:${{ github.sha }}

      - name: Deploy en producción
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.PRODUCTION_HOST }}
          username: root
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            echo "$DOCR_TOKEN" | docker login registry.digitalocean.com -u "$DOCR_TOKEN" --password-stdin
            docker pull registry.digitalocean.com/$DOCR_REGISTRY/todos:latest
            cd /opt/todos
            TAG=latest docker compose -f docker-compose.prod.yml up -d
            docker image prune -f
        env:
          DOCR_TOKEN: ${{ secrets.DOCR_TOKEN }}
          DOCR_REGISTRY: ${{ secrets.DOCR_REGISTRY }}
```

> **Por qué dos tags (`latest` y `<sha>`):** `latest` es conveniente para el
> deploy normal. El tag con el SHA del commit es inmutable — sirve para hacer
> rollback a una versión exacta sin tener que reconstruir la imagen.

### 4.4 Flujo completo end-to-end

```
1. Developer crea rama: git checkout -b feature/nueva-funcionalidad
2. Desarrolla, commitea y hace push
3. Abre PR: feature/nueva-funcionalidad → develop
4. GitHub Actions corre CI automáticamente
5. Con CI verde + aprobación: merge a develop
6. CD de staging se dispara automáticamente
7. App actualizada en staging en ~1 minuto
8. QA verifica en staging
9. Abre PR: develop → main
10. CI corre en el PR
11. Con CI verde + aprobación: merge a main
12. CD de producción se dispara automáticamente
13. App en producción actualizada
```

---

## Fase 5 — Buenas prácticas finales

### Health check endpoint

Agregar en `apps/todos/views.py`:
```python
from rest_framework.decorators import api_view
from rest_framework.response import Response

@api_view(["GET"])
def health_check(request):
    return Response({"status": "ok"})
```

En `config/urls.py`:
```python
from apps.todos.views import health_check

urlpatterns = [
    path("health/", health_check),
    ...
]
```

El load balancer (o el CD workflow) puede verificar que la app está viva antes de considerar el deploy exitoso.

### Rollback básico

Si un deploy a producción rompe algo:
```bash
# Opción 1 (recomendada): revertir el último commit en main
git revert HEAD
git push origin main
# → CD de producción se dispara y construye una imagen nueva sin el cambio problemático

# Opción 2: rollback inmediato en el servidor sin esperar CI/CD
# Cada imagen tiene un tag con el SHA del commit — úsalo para volver atrás al instante
ssh root@<IP_PRODUCCION>
cd /opt/todos
TAG=<sha-del-commit-bueno> docker compose -f docker-compose.prod.yml up -d
# La imagen ya está en el Droplet (o se baja del registry en segundos)
```

> **Ventaja de Docker sobre el enfoque sin Docker:** el rollback es instantáneo.
> No hay que reinstalar dependencias ni recompilar nada — la imagen anterior
> ya existe en el registry y se activa en segundos.

### Checklist de producción

- [ ] `DEBUG=False` en producción
- [ ] `SECRET_KEY` generada aleatoriamente y en GitHub Secrets, no en el código
- [ ] `ALLOWED_HOSTS` restringido al dominio/IP real
- [ ] HTTPS activo (Let's Encrypt con Certbot)
- [ ] Backups automáticos del Managed PostgreSQL activados
- [ ] `.env` en `.gitignore` — nunca commitear credenciales
- [ ] Ramas `main` y `develop` protegidas (requieren PR + CI verde)
- [ ] Migraciones corriendo dentro del contenedor antes de levantar Gunicorn
- [ ] `docker-compose.prod.yml` con `restart: unless-stopped` para auto-arranque
- [ ] WhiteNoise configurado para archivos estáticos
- [ ] DOCR_TOKEN guardado en GitHub Secrets (no en el código)
- [ ] Docker login configurado en cada Droplet para hacer pull del registry

---

## Referencia rápida

### Comandos locales frecuentes

```bash
# Levantar el stack completo
docker compose up --build

# Generar migración después de cambiar un modelo
docker compose exec web python manage.py makemigrations todos

# Aplicar migraciones
docker compose exec web python manage.py migrate

# Correr los tests
docker compose exec web python manage.py test apps.todos --verbosity=2

# Ver logs en tiempo real
docker compose logs -f web

# Abrir shell de Django
docker compose exec web python manage.py shell
```

### Comandos en el servidor

```bash
# Conectar al servidor
ssh root@<IP_DROPLET>

# Ver estado del contenedor
cd /opt/todos
docker compose -f docker-compose.prod.yml ps

# Ver logs de la aplicación en tiempo real
docker compose -f docker-compose.prod.yml logs -f web

# Reiniciar el contenedor manualmente
docker compose -f docker-compose.prod.yml restart web

# Abrir shell dentro del contenedor (para depuración)
docker compose -f docker-compose.prod.yml exec web python manage.py shell

# Correr un comando dentro del contenedor
docker compose -f docker-compose.prod.yml exec web python manage.py migrate

# Ver todas las imágenes descargadas en el servidor
docker images

# Rollback a una versión anterior
TAG=<sha-del-commit> docker compose -f docker-compose.prod.yml up -d

# Liberar espacio eliminando imágenes sin uso
docker image prune -f
```

### Estructura de archivos final

```
my_first_ci_cd_pipeline/
├── .github/
│   └── workflows/
│       ├── ci.yml              # Tests en cada push/PR
│       ├── cd-staging.yml      # Deploy automático a staging
│       └── cd-production.yml   # Deploy automático a producción
├── apps/
│   └── todos/
│       ├── migrations/
│       ├── tests/
│       │   ├── __init__.py
│       │   ├── test_models.py
│       │   └── test_api.py
│       ├── __init__.py
│       ├── apps.py
│       ├── models.py
│       ├── serializers.py
│       ├── urls.py
│       └── views.py
├── config/
│   ├── settings/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── local.py
│   │   └── production.py
│   ├── __init__.py
│   ├── asgi.py
│   ├── urls.py
│   └── wsgi.py
├── plans/
│   ├── aprendizaje-cicd.md    # Plan de aprendizaje (resumen)
│   └── tutorial-cicd.md       # Este archivo
├── requirements/
│   ├── base.txt
│   ├── local.txt
│   └── production.txt
├── .env                        # Local (NO va a git)
├── .env.example                # Plantilla documentada (va a git)
├── .gitignore
├── Dockerfile
├── docker-compose.yml          # Desarrollo local
├── docker-compose.prod.yml     # Producción/staging (usa imagen del registry)
└── manage.py
```
