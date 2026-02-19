# Plan de aprendizaje: CI/CD con Django + GitHub Actions + DigitalOcean

## Stack

| Capa | Tecnología |
|------|-----------|
| Aplicación | Django 5.1 + Django REST Framework |
| Base de datos | PostgreSQL (separada de la app) |
| Contenedores local | Docker + docker-compose |
| Control de versiones | Git + GitHub |
| CI | GitHub Actions |
| CD | GitHub Actions → SSH → Droplets DigitalOcean |
| Servidor web | Nginx (reverse proxy) + Gunicorn (WSGI) |
| Infraestructura | 2 Droplets (staging + producción) + Managed PostgreSQL |

## Estrategia de ramas

```
main        → deploy automático a producción
develop     → deploy automático a staging
feature/*   → PRs hacia develop, CI corre los tests
```

---

## Fase 1 — Estructura local y Docker ✅

**Objetivo:** proyecto Django corriendo localmente con Docker y PostgreSQL separada.

### Lo que se construyó

- App Django con settings separados por ambiente:
  - `config/settings/base.py` — configuración común
  - `config/settings/local.py` — DEBUG=True, ALLOWED_HOSTS=*
  - `config/settings/production.py` — DEBUG=False, HTTPS forzado, headers de seguridad
- API REST de Todos (CRUD completo con DRF)
- `Dockerfile` para construir la imagen de la app
- `docker-compose.yml` con dos servicios separados: `web` y `db`
- 15 pruebas unitarias (modelos + API)
- Variables de entorno con `python-decouple` — nunca credenciales en el código
- `.env.example` como documentación de variables requeridas (va a git)
- `.env` con valores locales reales (no va a git — en `.gitignore`)

### Lecciones aprendidas

- `makemigrations` genera el archivo de migración (va a git). `migrate` lo ejecuta contra la DB (operación runtime).
- El `Dockerfile` necesita toda la carpeta `requirements/` porque `local.txt` hace `-r base.txt`.
- El healthcheck de PostgreSQL necesita `-d <nombre_db>` para apuntar a la base correcta, no al usuario.
- El `label` del app en Django es el apellido del `name` en `AppConfig` — `apps.todos` → label `todos` → tabla `todos_todo`.

### Comandos clave

```bash
# Levantar el stack completo
docker compose up --build

# Generar migración de un app (primera vez o cuando cambia el modelo)
docker compose exec web python manage.py makemigrations todos

# Aplicar migraciones
docker compose exec web python manage.py migrate

# Correr los tests
docker compose exec web python manage.py test apps.todos

# Abrir shell de Django
docker compose exec web python manage.py shell

# Ver logs en tiempo real
docker compose logs -f web
```

---

## Fase 2 — CI con GitHub Actions

**Objetivo:** cada push o PR ejecuta los tests automáticamente en GitHub.

### Lo que se va a construir

- Workflow `.github/workflows/ci.yml` que se dispara en:
  - Push a `main` o `develop`
  - Pull requests hacia `main` o `develop`
- Pasos del workflow:
  1. Checkout del código
  2. Levantar servicio PostgreSQL en el runner de GitHub
  3. Instalar dependencias Python
  4. Correr `migrate`
  5. Correr los 15 tests
  6. (Opcional) Linting con `ruff`
- Protección de ramas en GitHub:
  - `main` solo acepta merge si el CI pasa
  - Requiere Pull Request — nadie hace push directo a main

### Conceptos clave

- Los runners de GitHub Actions tienen Docker disponible, pero es más rápido usar servicios nativos (`services:`) que levantar docker-compose completo.
- Los secrets de GitHub (Settings → Secrets) reemplazan al `.env` en el CI.
- El `DJANGO_SETTINGS_MODULE` en el CI apunta a `config.settings.local` con una DB de test.

---

## Fase 3 — Infraestructura en DigitalOcean

**Objetivo:** dos ambientes reales en la nube con la base de datos separada de los servidores.

### Lo que se va a construir

- **Managed PostgreSQL** en DigitalOcean:
  - Una base de datos para staging
  - Una base de datos para producción
  - Separada físicamente de los servidores de app — si el servidor cae, los datos están seguros
- **2 Droplets Ubuntu** (1 staging, 1 producción):
  - Docker instalado
  - Nginx como reverse proxy
  - Gunicorn como servidor WSGI
  - Certificado SSL con Let's Encrypt

### Por qué separar la base de datos del servidor

```
❌ Mal:  [Droplet: app + postgres]   → si cae el droplet, pierdes datos
✅ Bien: [Droplet: app] → [Managed DB]  → escalado y backup independientes
```

El Managed PostgreSQL de DigitalOcean incluye: backups automáticos diarios, réplicas, failover automático, y actualizaciones de seguridad gestionadas.

### Comandos clave

```bash
# Conectar al droplet por SSH
ssh root@<IP_DROPLET>

# Ver logs del contenedor en el servidor
docker logs -f <nombre_contenedor>
```

---

## Fase 4 — CD automatizado

**Objetivo:** merge a `develop` → deploy a staging. Merge a `main` → deploy a producción.

### Lo que se va a construir

- Workflow `.github/workflows/cd-staging.yml`:
  - Se dispara en push a `develop` (después de que CI pasa)
  - Se conecta por SSH al Droplet de staging
  - Hace `git pull`, rebuild de la imagen, `migrate`, restart del contenedor
- Workflow `.github/workflows/cd-production.yml`:
  - Se dispara en push a `main`
  - Mismos pasos pero apuntando al Droplet de producción

### Flujo completo

```
1. Developer hace PR de feature/x → develop
2. GitHub Actions corre CI (tests + linting)
3. Si pasa: merge permitido
4. Al hacer merge → CD de staging se dispara automáticamente
5. QA revisa staging
6. PR de develop → main
7. Al hacer merge → CD de producción se dispara automáticamente
```

### Manejo seguro de secrets en CD

Todos los datos sensibles (IPs, contraseñas, SSH keys) viven en GitHub Secrets, nunca en el código:

| Secret | Uso |
|--------|-----|
| `STAGING_HOST` | IP del droplet de staging |
| `PRODUCTION_HOST` | IP del droplet de producción |
| `SSH_PRIVATE_KEY` | Clave SSH para conectarse al droplet |
| `POSTGRES_PASSWORD` | Contraseña de la base de datos |
| `DJANGO_SECRET_KEY` | Secret key de Django en producción |

### Estrategia de migrations en CD

Las migrations se corren **antes** de que el nuevo contenedor empiece a atender tráfico:

```bash
# En el workflow de deploy
docker compose exec web python manage.py migrate --no-input
docker compose restart web
```

---

## Fase 5 — Buenas prácticas finales

**Objetivo:** dejar el proyecto con estándares de producción reales.

### Temas a cubrir

- **Health check endpoint** en Django (`/health/`) para que el load balancer sepa si la app está viva
- **Rollback básico**: si el deploy falla, cómo volver a la versión anterior con `git revert` + re-deploy
- **Logging**: configurar Django para escribir logs en un lugar accesible
- **Variables de entorno**: auditoría de que ningún secret esté hardcodeado

### Checklist de producción

- [ ] `DEBUG=False` en producción
- [ ] `SECRET_KEY` generada aleatoriamente y en secret, no en el código
- [ ] `ALLOWED_HOSTS` restringido al dominio real
- [ ] HTTPS forzado y certificado SSL activo
- [ ] Backups automáticos de la base de datos activados
- [ ] `.env` en `.gitignore`
- [ ] Rama `main` protegida (requiere PR + CI verde)
- [ ] Migrations corriendo antes del restart del servidor

---

## Referencia rápida de archivos del proyecto

```
my_first_ci_cd_pipeline/
├── .github/
│   └── workflows/
│       ├── ci.yml              # Fase 2: tests en cada PR
│       ├── cd-staging.yml      # Fase 4: deploy a staging
│       └── cd-production.yml   # Fase 4: deploy a producción
├── apps/
│   └── todos/                  # App Django
│       ├── migrations/
│       ├── tests/
│       │   ├── test_models.py
│       │   └── test_api.py
│       ├── models.py
│       ├── serializers.py
│       ├── views.py
│       └── urls.py
├── config/
│   ├── settings/
│   │   ├── base.py             # Configuración común
│   │   ├── local.py            # Desarrollo local
│   │   └── production.py       # Producción / staging
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── plans/
│   └── aprendizaje-cicd.md    # Este archivo
├── requirements/
│   ├── base.txt
│   ├── local.txt
│   └── production.txt
├── .env                        # Local (no va a git)
├── .env.example                # Plantilla documentada (va a git)
├── .gitignore
├── Dockerfile
├── docker-compose.yml
└── manage.py
```
