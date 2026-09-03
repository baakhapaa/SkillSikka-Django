# SkillSikka-Django

SkillSikka backend — Django + Django REST Framework, modular monolith.

## Stack

- Django 5 + Django REST Framework
- SimpleJWT (access/refresh auth)
- drf-spectacular (OpenAPI schema/Swagger UI)
- MySQL in production (PyMySQL driver), SQLite for local dev by default

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

See [docs](../SkillSikka/docs/01-Technical-Documentation.md) in the SkillSikka repo for the full architecture and data model.
