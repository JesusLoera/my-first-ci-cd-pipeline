# my-first-ci-cd-pipeline

API REST de Todos construida con Django como vehículo para aprender e implementar un pipeline de CI/CD completo con GitHub Actions y DigitalOcean.

## Objetivo

Un pipeline automatizado de extremo a extremo:

- **CI**: cada PR corre linting (ruff), verifica migraciones pendientes y ejecuta los tests automáticamente.
- **CD a Staging**: cada merge a `develop` construye una imagen Docker, la sube al Container Registry de DigitalOcean y despliega en el Droplet de staging.
- **CD a Producción**: cada merge a `main` repite el mismo proceso apuntando al Droplet de producción.

## Stack

| Capa | Tecnología |
|---|---|
| Backend | Django 5 + Django REST Framework |
| Base de datos | PostgreSQL 18 |
| Servidor de aplicación | Gunicorn |
| Archivos estáticos | WhiteNoise |
| Contenedores | Docker + Docker Compose |
| Registry de imágenes | DigitalOcean Container Registry (DOCR) |
| Servidores | DigitalOcean Droplets (Ubuntu) |
| CI/CD | GitHub Actions |

## Estructura del proyecto

```
.
├── .github/
│   └── workflows/
│       ├── ci.yml              # Linting + tests en cada PR
│       ├── cd-staging.yml      # Deploy automático a staging (develop)
│       └── cd-production.yml   # Deploy automático a producción (main)
├── apps/
│   └── todos/                  # App Django: modelo, serializer, vistas, tests
├── config/
│   └── settings/
│       ├── base.py             # Settings comunes a todos los ambientes
│       ├── local.py            # Desarrollo local (DEBUG=True, sin HTTPS)
│       └── production.py       # Staging y producción (DEBUG=False, WhiteNoise, seguridad HTTPS)
├── requirements/
│   ├── base.txt                # Dependencias de producción
│   ├── local.txt               # base.txt + herramientas de desarrollo (ruff)
│   └── production.txt          # Alias de base.txt (explícito por claridad)
├── docker-compose.yml          # Entorno local de desarrollo
├── docker-compose.prod.yml     # Entorno de producción/staging (sin volumen de código)
├── Dockerfile                  # Imagen de la aplicación
└── plans/
    └── tutorial-cicd.md        # Tutorial paso a paso del proyecto
```

## Flujo de trabajo (ramas)

```
feature/* → develop → main
               ↓          ↓
           Staging    Producción
```

- `develop`: recibe los merges de features. Cada push dispara el CD a staging.
- `main`: recibe merges desde `develop` vía PR. Cada push dispara el CD a producción.
- Las ramas `feature/*` se mergean a `develop` vía PR. El CI corre y debe pasar antes de mergear.

## API

El endpoint base es `/api/todos/` con operaciones CRUD estándar (ModelViewSet).

| Método | URL | Acción |
|---|---|---|
| GET | `/api/todos/` | Listar todos |
| POST | `/api/todos/` | Crear uno |
| GET | `/api/todos/{id}/` | Obtener uno |
| PUT/PATCH | `/api/todos/{id}/` | Actualizar |
| DELETE | `/api/todos/{id}/` | Eliminar |

Los resultados vienen paginados (10 por página).

## Correr el proyecto localmente

**Requisitos:** Docker y Docker Compose.

```bash
# 1. Clonar el repo
git clone <url-del-repo>
cd my-first-ci-cd-pipeline

# 2. Crear el archivo de variables de entorno
cp .env.example .env

# 3. Levantar los contenedores
docker compose up --build

# 4. En otra terminal, aplicar migraciones
docker compose exec web python manage.py migrate

# 5. Acceder a la API
curl http://localhost:8000/api/todos/
```

## CI/CD — Cómo funciona

### CI (`ci.yml`)

Se dispara en cada push o PR hacia `develop` o `main`. Corre sobre `ubuntu-latest` con un servicio PostgreSQL en el runner.

Pasos:
1. Checkout del código
2. Instalar Python 3.12 y dependencias
3. Linting con `ruff`
4. Verificar que no hay migraciones pendientes (`makemigrations --check`)
5. Aplicar migraciones
6. Correr tests

### CD — Staging y Producción

Ambos workflows siguen la misma estructura:

1. **Login al DOCR** usando `DOCR_TOKEN`
2. **Build y push de imagen** con `docker/build-push-action@v6`
   - Se especifica `platforms: linux/amd64` para producir una sola entrada en el registry (sin manifests multi-plataforma)
   - Dos tags: uno mutable (`staging-latest` / `latest`) + uno inmutable por SHA (`staging-<sha>` / `<sha>`) para rollback
3. **Copiar `docker-compose.prod.yml`** al servidor vía SCP
4. **Deploy vía SSH**: login al registry, `docker pull`, `docker compose up -d`, limpieza de imágenes viejas

## GitHub Secrets requeridos

| Secret | Descripción |
|---|---|
| `DOCR_TOKEN` | Personal Access Token de DigitalOcean (scopes: create, read, update) |
| `DOCR_REGISTRY` | Nombre del registry (ej: `tu-usuario/todos-container-registry`) |
| `SSH_PRIVATE_KEY` | Clave privada SSH para acceder a los Droplets (sin passphrase) |
| `STAGING_HOST` | IP pública del Droplet de staging |
| `PRODUCTION_HOST` | IP pública del Droplet de producción |

## Rollback

Cada deploy sube una imagen con tag inmutable `<github-sha>`. Para hacer rollback en el servidor:

```bash
# En el Droplet correspondiente
cd /opt/todos
TAG=<sha-anterior> docker compose -f docker-compose.prod.yml up -d
```
