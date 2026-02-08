# Smart Invoices - Truck Mechanic Edition

A specialized Django-based invoice management system designed specifically for truck mechanics, with user authentication, payment processing, and business management features.

## Project Structure

```
smart-invoices/
?"o?"??"? blank_template/          # Django project settings
?",   ?"o?"??"? settings.py         # Main settings file (configured for local development)
?",   ?"o?"??"? urls.py            # Main URL configuration
?",   ?"o?"??"? wsgi.py            # WSGI application
?",   ?""?"??"? asgi.py            # ASGI application
?"o?"??"? company_core/          # Shared backend apps
?",   ?"o?"??"? accounts/         # Main Django app
?",   ?",   ?"o?"??"? models.py    # Database models
?",   ?",   ?"o?"??"? views.py     # Main views
?",   ?",   ?"o?"??"? forms.py     # Django forms
?",   ?",   ?"o?"??"? urls.py      # URL routing
?",   ?",   ?"o?"??"? admin.py     # Django admin configuration
?",   ?",   ?"o?"??"? templates/   # App templates
?",   ?",   ?"o?"??"? management/  # Custom management commands
?",   ?",   ?""?"??"? migrations/  # Database migrations
?",   ?"o?"??"? api/              # API app for REST endpoints
?",   ?",   ?"o?"??"? views.py     # API views
?",   ?",   ?"o?"??"? serializers.py     # DRF serializers
?",   ?",   ?""?"??"? urls.py      # API URL routing
?"o?"??"? templates/             # Public-facing templates
?"o?"??"? static/                # Static files (CSS, JS, images)
?"o?"??"? media/                 # User-uploaded files
?"o?"??"? logs/                  # Application logs
?"o?"??"? exports/               # Data export files
?"o?"??"? requirements.txt       # Production dependencies
?"o?"??"? requirements_local.txt # Local development dependencies
?"o?"??"? manage.py             # Django management script
?""?"??"? .env                  # Environment variables (not in version control)
```


## Features

- **Truck Mechanic Focus**: Specialized for truck repair and maintenance businesses
- **User Authentication**: Registration, login, password reset
- **Invoice Management**: Create, edit, and manage work orders and invoices
- **Vehicle Management**: Track VIN numbers, mileage, unit numbers, and make/models
- **Payment Processing**: Stripe integration for payments
- **Business Management**: Company profiles and settings
- **Email Notifications**: Automated email sending
- **API Support**: REST API for external integrations
- **Export Functionality**: Data export capabilities

## Local Development Setup

### Prerequisites

- Python 3.10 or higher
- pip (Python package manager)

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd smart-invoices
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   ```

3. **Activate virtual environment**
   ```bash
   # Windows
   venv\Scripts\activate
   
   # macOS/Linux
   source venv/bin/activate
   ```

4. **Install dependencies**
   ```bash
   pip install -r requirements_local.txt
   ```

5. **Set up environment variables**
   Create a `.env` file in the project root with:
   ```
   SECRET_KEY=your-secret-key-here
   EMAIL_HOST_PASSWORD=your-email-password
   OPENAI_API_KEY=your-openai-api-key
   STRIPE_SECRET_KEY=your-stripe-secret-key
   STRIPE_PUBLISHABLE_KEY=your-stripe-publishable-key
   STRIPE_WEBHOOK_SECRET=your-stripe-webhook-secret
   ```

6. **Run database migrations**
   ```bash
   python manage.py migrate
   ```

7. **Create superuser (optional)**
   ```bash
   python manage.py createsuperuser
   ```

8. **Start development server**
   ```bash
   python manage.py runserver
   ```

The application will be available at `http://127.0.0.1:8000`

## Configuration

### Database
- **Local Development**: SQLite (configured in `settings.py`)
- **Production (current Koyeb setup)**: SQLite using the committed `db.sqlite3`
- **Future option**: Postgres by setting `DATABASE_URL`

### Email Settings
- **Host**: smtp.gmail.com
- **Port**: 587
- **TLS**: Enabled
- **Authentication**: Required

### QuickBooks Integration Setup
Transtex now supports both **QuickBooks Online** (direct API sync) and **QuickBooks Desktop** (IIF file exchange). Pick the workflow that matches your business from **Settings → QuickBooks Integration**.

#### QuickBooks Online (OAuth)
1. **Create an Intuit Developer account** at [developer.intuit.com](https://developer.intuit.com/) and create a new app that uses "QuickBooks Online and Payments".
2. **Add OAuth redirect URIs** for your environments. For local testing you can use the default playground URL (`https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl`) or supply your own application callback (e.g. `https://<your-domain>/quickbooks/callback`).
3. **Copy your Client ID, Client Secret, and Realm ID** from the QuickBooks app settings. The Realm ID appears on the production/sandbox keys page.
4. **Generate a refresh token** by launching the OAuth 2.0 playground from the Intuit developer portal. Exchange the authorization code for tokens and copy the refresh token value.
5. **Enter these values in Transtex** and keep the integration type set to *QuickBooks Online*. Saving the form will store the credentials securely and allow you to refresh access tokens or trigger syncs directly from the dashboard.

Until the refresh token is provided the QuickBooks button on the dashboard remains visible but marked as "Not configured", letting you quickly finish the setup once your credentials are ready.

#### QuickBooks Desktop (IIF)
1. **Choose "QuickBooks Desktop"** in the integration form and supply the exact company name from your QuickBooks Desktop file. No OAuth credentials are required.
2. Use the **Export** or **Full sync package** buttons on the dashboard or settings page to download an `.IIF` file containing invoices ready for QuickBooks Desktop's *File → Utilities → Import* workflow.
3. When you need to bring QuickBooks updates back into Transtex, export the relevant invoices from QuickBooks Desktop to an `.IIF` file and upload it through the **Import** action. The importer matches customers, products, and invoices automatically and creates any missing records.
4. Status badges in the settings page track the last import/export filenames so you always know which file was processed most recently.

#### Environment variable configuration

For hosted environments such as Koyeb you can supply the QuickBooks production credentials via environment variables. When these are present the QuickBooks settings page will pre-fill any missing values. Set the following variables:

| Variable | Description |
| --- | --- |
| `QUICKBOOKS_CLIENT_ID` | OAuth client ID from the Intuit developer portal. |
| `QUICKBOOKS_CLIENT_SECRET` | OAuth client secret for your QuickBooks app. |
| `QUICKBOOKS_REALM_ID` | Company (realm) ID associated with the QuickBooks Online account. |
| `QUICKBOOKS_REFRESH_TOKEN` | Long-lived refresh token generated for the production environment. |
| `QUICKBOOKS_REDIRECT_URI` *(optional)* | Override redirect URI if you are not using the OAuth playground default. |
| `QUICKBOOKS_ENVIRONMENT` *(optional)* | Either `production` or `sandbox`. Defaults to `sandbox`. |
| `QUICKBOOKS_AUTO_SYNC_ENABLED` *(optional)* | Set to `true` to enable automatic syncing by scheduled jobs. |

### Static Files
- **Development**: Served from `static/` directory
- **Production**: Collected to `staticfiles/` directory

## Development Guidelines

### Code Organization
- Keep views modular and focused on single responsibilities
- Use Django forms for data validation
- Follow Django naming conventions
- Document complex business logic

### Testing
- Run tests: `python manage.py test`
- Test email functionality: `python manage.py test_email`

### Database
- Create migrations: `python manage.py makemigrations`
- Apply migrations: `python manage.py migrate`
- Reset database: Delete `db.sqlite3` and run migrations

### Static Files
- Collect static files: `python manage.py collectstatic`
- Clear static cache: Delete `staticfiles/` directory

## File Structure Cleanup

The project has been cleaned up to remove:
- ✅ Python cache files (`__pycache__/`)
- ✅ Temporary test files
- ✅ Duplicate virtual environments
- ✅ Generated static files (will be regenerated as needed)
- ✅ Large unnecessary files
- ✅ Empty log files
- ✅ Non-truck mechanic occupation templates and code
- ✅ Other occupation types (car mechanic, contractor, etc.)

## Environment Variables

Required environment variables in `.env`:
- `SECRET_KEY`: Django secret key
- `EMAIL_HOST_PASSWORD`: Email service password
- `OPENAI_API_KEY`: OpenAI API key (if using AI features)
- `STRIPE_SECRET_KEY`: Stripe secret key
- `STRIPE_PUBLISHABLE_KEY`: Stripe publishable key
- `STRIPE_WEBHOOK_SECRET`: Stripe webhook secret

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure virtual environment is activated
2. **Database Errors**: Run `python manage.py migrate`
3. **Static Files Not Loading**: Run `python manage.py collectstatic`
4. **Email Not Sending**: Check `.env` file and email credentials
5. **Permission Errors**: Ensure proper file permissions

### Logs
- Application logs: `logs/process_recurring_expenses.log`
- Django logs: Console output during development

## Koyeb Deployment

Files and config:
- `Procfile`: `web: gunicorn blank_template.wsgi --log-file -`
- `runtime.txt`: Python version (e.g., `python-3.12.4`)
- `koyeb.yml`: includes build steps (install, collectstatic, migrate) and run command
- `requirements.txt`: includes `gunicorn`, `whitenoise`, `dj-database-url`

Environment variables to set on Koyeb:
- `DJANGO_SETTINGS_MODULE=blank_template.settings`
- `DEBUG=False`
- `ALLOWED_HOSTS=.koyeb.app,yourdomain.com`
- `CSRF_TRUSTED_ORIGINS=https://your-app.koyeb.app,https://yourdomain.com`
- `FORCE_SQLITE=True` (forces `db.sqlite3` usage even if `DATABASE_URL` exists)
- Leave `DATABASE_URL` unset while using SQLite
- Optional: `EMAIL_HOST_PASSWORD`, `STRIPE_*`, `OPENAI_API_KEY`

Koyeb automatically runs the `koyeb.yml` steps on deploy. The service command also runs `python manage.py migrate` on startup to ensure schema is up to date.
For this SQLite setup, keep `db.sqlite3` committed and pushed to GitHub before deploying.

## Contributing

1. Follow the existing code style
2. Add tests for new features
3. Update documentation as needed
4. Test thoroughly before submitting changes

## License

[Add your license information here]
