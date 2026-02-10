# QavTix Backend (Django + DRF)

A production-ready backend service built with **Django** and **Django Rest Framework (DRF)**. This project powers the QavTix platform, providing authentication, user management, and core business APIs with a clean, scalable architecture.

---

## 📌 Features

* Django 5.x
* Django Rest Framework (API-first design)
* Custom User Model
* Environment-based configuration using `django-environ`
* PostgreSQL support (production-ready)
* Token/JWT-ready authentication flow
* Clean project structure
* Secure secret management via `.env`

---


---

## ⚙️ Requirements

* Python 3.10+
* PostgreSQL (recommended for production)
* pip / virtualenv

---

## 🚀 Setup Instructions

### 1️⃣ Clone the repository

```bash
git clone repo link
cd into the project
```

---

### 2️⃣ Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

---

### 3️⃣ Install dependencies

```bash
pip install -r requirements.txt
```

---

### 4️⃣ Environment variables

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Example `.env`:

```
DEBUG=True
SECRET_KEY=your-secret-key
DATABASE_URL=postgres://user:password@localhost:5432/qavtix
```

> ⚠️ Never commit `.env` files. They are excluded via `.gitignore`.

---

### 5️⃣ Database setup

Run migrations:

```bash
python manage.py migrate
```

(Optional) Create a superuser:

```bash
python manage.py createsuperuser
```

---

### 6️⃣ Run the development server

```bash
python manage.py runserver
```

Server will be available at:

```
http://127.0.0.1:8000/
```

---

## 🔐 Environment Configuration

This project uses **django-environ** to automatically read configuration from `.env` files.

In `settings.py`:

```python
DATABASES = {
    'default': env.db(),
}
```

As long as `DATABASE_URL` exists in `.env`, Django will configure the database automatically.

---

## 🧩 Authentication

* Custom User Model is defined in `authentication/models.py`
* Supports standard registration & login
* Social authentication 

> Authentication is API-driven and designed for frontend/mobile consumption.

---

## 🧪 Testing

Run tests using:

```bash
python manage.py test
```

---

## 📦 Git & Version Control

Tracked:

* Source code
* Migrations
* Requirements

Ignored:

* `.env`
* `venv/`
* Logs
* Compiled Python files
* Media & static build artifacts

---

## 🛡️ Security Notes

* Secrets are loaded via environment variables
* Debug mode must be disabled in production
* Database credentials should never be hardcoded

---

## 📄 License

This project is proprietary and owned by **/QavTix**.
Unauthorized copying or redistribution is prohibited.

---

## 🤝 Contributing

1. Create a feature branch from `main`
2. Commit clean, atomic changes
3. Open a pull request with a clear description

---

## 📞 Support

For internal development or issues, contact the QavTix backend team.

---

**Built with ❤️ using Django & DRF**
