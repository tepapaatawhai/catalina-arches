"""
Django settings for catalina project.
"""

# Load environment variables from .env file if python-dotenv is available
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # python-dotenv not installed, environment variables should be set externally
    pass

import os
import inspect
import semantic_version
from datetime import datetime, timedelta
from django.utils.translation import gettext_lazy as _

try:
    from arches.settings import *
except ImportError:
    pass

from django.conf.locale import LANG_INFO

LANG_INFO["mi"] = {
    "bidi": False,
    "code": "mi",
    "name": "Maori",
    "name_local": "te reo Māori",
}

APP_NAME = "catalina"
APP_VERSION = semantic_version.Version(major=0, minor=0, patch=0)
APP_ROOT = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))

WEBPACK_LOADER = {
    "DEFAULT": {
        "STATS_FILE": os.path.join(APP_ROOT, "..", "webpack/webpack-stats.json"),
    },
}

DATATYPE_LOCATIONS.append("catalina.datatypes")
DATATYPE_LOCATIONS.append("arches_her.datatypes")
FUNCTION_LOCATIONS.append("catalina.functions")
FUNCTION_LOCATIONS.append("arches_her.functions")
ETL_MODULE_LOCATIONS.append("catalina.etl_modules")
SEARCH_COMPONENT_LOCATIONS.append("catalina.search_components")
SEARCH_COMPONENT_LOCATIONS.append("arches_her.search.components")
PERMISSION_LOCATIONS.append("catalina.permissions")

# Blanket-role group names — override these to rename the roles without
# touching the permission framework code or migration logic.
BLANKET_FULL_ACCESS_GROUPS = ["Administrator"]  # view + change + delete on all
BLANKET_READ_ACCESS_GROUPS = ["Editor"]  # view on all

# Resource-instance permissions default to DENY via the stopgap blanket-role
# framework (see catalina.permissions.blanket_roles). Set
# CATALINA_BLANKET_ROLES=False to fall back to the Arches default-ALLOW
# framework.
#
# SECURITY: under default-deny every active non-superuser NOT in a blanket group
# loses default resource-instance access.
if os.environ.get("CATALINA_BLANKET_ROLES", "True").lower() in ("true", "1", "yes"):
    PERMISSION_FRAMEWORK = "blanket_roles.BlanketRoleDenyFramework"

LOCALE_PATHS.insert(0, os.path.join(APP_ROOT, "locale"))

MAPBOX_API_KEY = os.environ.get("MAPBOX_API_KEY", "")

FILE_TYPE_CHECKING = "lenient"
FILE_TYPES = [
    "bmp",
    "gif",
    "jpg",
    "jpeg",
    "json",
    "pdf",
    "png",
    "psd",
    "rtf",
    "tif",
    "tiff",
    "xlsx",
    "csv",
    "zip",
]
FILENAME_GENERATOR = "arches.app.utils.storage_filename_generator.generate_filename"
UPLOADED_FILES_DIR = "uploadedfiles"

AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_S3_ENDPOINT_URL = os.environ.get("AWS_S3_ENDPOINT_URL")
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME")
AWS_S3_REGION_NAME = os.environ.get("AWS_S3_REGION_NAME", "us-east-1")
AWS_LOCATION = os.environ.get("AWS_LOCATION", "")
AWS_S3_CUSTOM_DOMAIN = os.environ.get("AWS_S3_CUSTOM_DOMAIN")
AWS_S3_ADDRESSING_STYLE = "path"
AWS_QUERYSTRING_AUTH = False
AWS_S3_FILE_OVERWRITE = False

if AWS_STORAGE_BUCKET_NAME:
    INSTALLED_APPS = (*INSTALLED_APPS, "storages")
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {},
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "django-insecure-uakb+p1m4%)vx2)6!r&q0*ff@j90ih^35(j0xb#0j-)o_f)y)b"

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = bool(os.environ.get("DJANGO_DEBUG", False))

ROOT_URLCONF = "catalina.urls"
ROOT_HOSTCONF = "catalina.hosts"

DEFAULT_HOST = "catalina"

# Modify this line as needed for your project to connect to elasticsearch with a password that you generate
ELASTICSEARCH_CONNECTION_OPTIONS = {
    "request_timeout": 30,
    "verify_certs": False,
    "basic_auth": ("elastic", "E1asticSearchforArche5"),
}

# If you need to connect to Elasticsearch via an API key instead of username/password, use the syntax below:
# ELASTICSEARCH_CONNECTION_OPTIONS = {"request_timeout": 30, "verify_certs": False, "api_key": "<ENCODED_API_KEY>"}
# ELASTICSEARCH_CONNECTION_OPTIONS = {"request_timeout": 30, "verify_certs": False, "api_key": ("<ID>", "<API_KEY>")}

# Your Elasticsearch instance needs to be configured with xpack.security.enabled=true to use API keys - update elasticsearch.yml or .env file and restart.

# Set the ELASTIC_PASSWORD environment variable in either the docker-compose.yml or .env file to the password you set for the elastic user,
# otherwise a random password will be generated.

# API keys can be generated via the Elasticsearch API: https://www.elastic.co/guide/en/elasticsearch/reference/current/security-api-create-api-key.html
# Or Kibana: https://www.elastic.co/guide/en/kibana/current/api-keys.html

# a prefix to append to all elasticsearch indexes, note: must be lower case
ELASTICSEARCH_PREFIX = "catalina"

ELASTICSEARCH_CUSTOM_INDEXES = []
# [{
#     'module': 'catalina.search_indexes.sample_index.SampleIndex',
#     'name': 'my_new_custom_index', <-- follow ES index naming rules
#     'should_update_asynchronously': False  <-- denotes if asynchronously updating the index would affect custom functionality within the project.
# }]

KIBANA_URL = "http://localhost:5601/"
KIBANA_CONFIG_BASEPATH = "kibana"  # must match Kibana config.yml setting (server.basePath) but without the leading slash,
# also make sure to set server.rewriteBasePath: true

LOAD_DEFAULT_ONTOLOGY = False
LOAD_PACKAGE_ONTOLOGIES = True

# This is the namespace to use for export of data (for RDF/XML for example)
# It must point to the url where you host your site
# Make sure to use a trailing slash
ARCHES_NAMESPACE_FOR_DATA_EXPORT = "http://localhost:8000/"

DATABASES = {
    "default": {
        "ATOMIC_REQUESTS": False,
        "AUTOCOMMIT": True,
        "CONN_MAX_AGE": 0,
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "HOST": "localhost",
        "NAME": "catalina",
        "OPTIONS": {
            "options": "-c cursor_tuple_fraction=1",
        },
        "PASSWORD": "postgis",
        "PORT": "5432",
        "POSTGIS_TEMPLATE": "template_postgis",
        "TEST": {"CHARSET": None, "COLLATION": None, "MIRROR": None, "NAME": None},
        "TIME_ZONE": None,
        "USER": "postgres",
    }
}

SEARCH_THUMBNAILS = False

INSTALLED_APPS = (
    "catalina",
    "webpack_loader",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "django_hosts",
    "arches_controlled_lists",
    "arches_querysets",
    "arches_vue_components",
    "arches",
    "arches.app.models",
    "arches.management",
    "guardian",
    "django_recaptcha",
    "revproxy",
    "corsheaders",
    "oauth2_provider",
    "django_celery_results",
    "django_migrate_sql",
    "pgtrigger",
    "azure_auth",  # Django Azure Auth for Microsoft Entra ID
    # "silk",
)

INSTALLED_APPS += (
    "arches.app",
    "django.contrib.admin",
    "django.contrib.postgres",
    "arches_her",
    "arches_json_importer",
)

REFERENCES_INDEX_NAME = "references"
ELASTICSEARCH_CUSTOM_INDEXES = [
    {
        "module": "arches_controlled_lists.search_indexes.reference_index.ReferenceIndex",
        "name": REFERENCES_INDEX_NAME,
        "should_update_asynchronously": True,
    }
]
TERM_SEARCH_TYPES = [
    {
        "type": "term",
        "label": _("Term Matches"),
        "key": "terms",
        "module": "arches.app.search.search_term.TermSearch",
    },
    {
        "type": "concept",
        "label": _("Concepts"),
        "key": "concepts",
        "module": "arches.app.search.concept_search.ConceptSearch",
    },
    {
        "type": "reference",
        "label": _("References"),
        "key": REFERENCES_INDEX_NAME,
        "module": "arches_controlled_lists.search_indexes.reference_index.ReferenceIndex",
    },
]

ES_MAPPING_MODIFIER_CLASSES = [
    "arches_controlled_lists.search.references_es_mapping_modifier.ReferencesEsMappingModifier"
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "arches.app.utils.middleware.ModifyAuthorizationHeader",
    "oauth2_provider.middleware.OAuth2TokenMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "arches.app.utils.middleware.SetAnonymousUser",
    # "azure_auth.middleware.AzureMiddleware",  # Commented out - authentication is opt-in via decorators/permissions
    # "silk.middleware.SilkyMiddleware",
]

MIDDLEWARE.insert(  # this must resolve to first MIDDLEWARE entry
    0, "django_hosts.middleware.HostsRequestMiddleware"
)

MIDDLEWARE.append(  # this must resolve last MIDDLEWARE entry
    "django_hosts.middleware.HostsResponseMiddleware"
)

# Security headers
SECURE_SSL_REDIRECT = not DEBUG and not bool(
    os.environ.get("SECURE_SSL_OVERRIDE", False)
)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True

SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Cookie settings
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
SESSION_COOKIE_SECURE = True

STATICFILES_DIRS = build_staticfiles_dirs(app_root=APP_ROOT)

TEMPLATES = build_templates_config(
    debug=DEBUG,
    app_root=APP_ROOT,
)

ALLOWED_HOSTS = []

SYSTEM_SETTINGS_LOCAL_PATH = os.path.join(
    APP_ROOT, "system_settings", "System_Settings.json"
)
WSGI_APPLICATION = "catalina.wsgi.application"

# URL that handles the media served from MEDIA_ROOT, used for managing stored files.
# It must end in a slash if set to a non-empty value.
MEDIA_URL = "/files/"

# Absolute filesystem path to the directory that will hold user-uploaded files.
MEDIA_ROOT = os.path.join(APP_ROOT)

# URL prefix for static files.
# Example: "http://media.lawrence.com/static/"
STATIC_URL = "/static/"

# Absolute path to the directory static files should be collected to.
# Don't put anything in this directory yourself; store your static files
# in apps' "static/" subdirectories and in STATICFILES_DIRS.
# Example: "/home/media/media.lawrence.com/static/"
STATIC_ROOT = os.path.join(APP_ROOT, "staticfiles")

# when hosting Arches under a sub path set this value to the sub path eg : "/{sub_path}/"
FORCE_SCRIPT_NAME = None

RESOURCE_IMPORT_LOG = os.path.join(APP_ROOT, "logs", "resource_import.log")
DEFAULT_RESOURCE_IMPORT_USER = {"username": "admin", "userid": 1}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "console": {
            "format": "%(asctime)s %(name)-12s %(levelname)-8s %(message)s",
        },
    },
    "handlers": {
        "file": {
            "level": "WARNING",  # DEBUG, INFO, WARNING, ERROR
            "class": "logging.FileHandler",
            "filename": os.path.join(APP_ROOT, "arches.log"),
            "formatter": "console",
        },
        "console": {
            "level": "WARNING",
            "class": "logging.StreamHandler",
            "formatter": "console",
        },
    },
    "loggers": {
        "arches": {
            "handlers": ["file", "console"],
            "level": "WARNING",
            "propagate": True,
        },
        "catalina": {
            "handlers": ["file", "console"],
            "level": "WARNING",
            "propagate": True,
        },
        "django.request": {
            "handlers": ["file", "console"],
            "level": "WARNING",
            "propagate": True,
        },
    },
}

# Rate limit for authentication views
# See options (including None or python callables):
# https://django-ratelimit.readthedocs.io/en/stable/rates.html#rates-chapter
RATE_LIMIT = "5/m"

# Sets default max upload size to 15MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 15728640

# Unique session cookie ensures that logins are treated separately for each app
SESSION_COOKIE_NAME = "catalina"
SESSION_COOKIE_SAMESITE = "Lax"  # Allow cookies to be sent with OAuth redirects
SESSION_COOKIE_HTTPONLY = True  # Prevent JavaScript access to session cookie
SESSION_COOKIE_SECURE = False  # Set to True in production with HTTPS

# For more info on configuring your cache: https://docs.djangoproject.com/en/2.2/topics/cache/
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://redis:6379"),
    },
    "user_permission": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "user_permission_cache",
    },
}

# Hide nodes and cards in a report that have no data
HIDE_EMPTY_NODES_IN_REPORT = False

BYPASS_UNIQUE_CONSTRAINT_TILE_VALIDATION = False
BYPASS_REQUIRED_VALUE_TILE_VALIDATION = False

DATE_IMPORT_EXPORT_FORMAT = (
    "%Y-%m-%d"  # Custom date format for dates imported from and exported to csv
)

# This is used to indicate whether the data in the CSV and SHP exports should be
# ordered as seen in the resource cards or not.
EXPORT_DATA_FIELDS_IN_CARD_ORDER = False

# Identify the usernames and duration (seconds) for which you want to cache the time wheel
CACHE_BY_USER = {"default": 3600 * 24, "anonymous": 3600 * 24}  # 24hrs  # 24hrs

TILE_CACHE_TIMEOUT = 600  # seconds
CLUSTER_DISTANCE_MAX = 5000  # meters
GRAPH_MODEL_CACHE_TIMEOUT = None

APP_TITLE = "Arches | Heritage Data Management"
COPYRIGHT_TEXT = "All Rights Reserved."
COPYRIGHT_YEAR = "2019"

ENABLE_CAPTCHA = False
# RECAPTCHA_PUBLIC_KEY = ''
# RECAPTCHA_PRIVATE_KEY = ''
# RECAPTCHA_USE_SSL = False
NOCAPTCHA = True
# RECAPTCHA_PROXY = 'http://127.0.0.1:8000'

# EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'  #<-- Only need to uncomment this for testing without an actual email server
# arches 8.2 moved email config to MAILERS; Django raises ImproperlyConfigured
# if the legacy EMAIL_HOST_USER/EMAIL_HOST_PASSWORD/etc settings are set
# alongside it, so overrides go through MAILERS now instead.
MAILERS = {
    "default": {
        "OPTIONS": {
            "use_tls": True,
            # "host": "smtp.gmail.com",
            "username": "xxxx@xxx.com",
            # "password": "xxxxxxx",
        },
    },
}

DEFAULT_FROM_EMAIL = MAILERS["default"]["OPTIONS"]["username"]

CELERY_BROKER_URL = ""  # RabbitMQ --> "amqp://guest:guest@localhost",  Redis --> "redis://localhost:6379/0"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_RESULT_BACKEND = (
    "django-db"  # Use 'django-cache' if you want to use your cache as your backend
)
CELERY_TASK_SERIALIZER = "json"

CELERY_WORKER_CONCURRENCY = int(os.environ.get("CELERY_WORKER_CONCURRENCY", "3"))


CELERY_SEARCH_EXPORT_EXPIRES = 24 * 3600  # seconds
CELERY_SEARCH_EXPORT_CHECK = 3600  # seconds

CELERY_BEAT_SCHEDULE = {
    "delete-expired-search-export": {
        "task": "arches.app.tasks.delete_file",
        "schedule": CELERY_SEARCH_EXPORT_CHECK,
    },
    "notification": {
        "task": "arches.app.tasks.message",
        "schedule": CELERY_SEARCH_EXPORT_CHECK,
        "args": ("Celery Beat is Running",),
    },
}

# Set to True if you want to send celery tasks to the broker without being able to detect celery.
# This might be necessary if the worker pool is regulary fully active, with no idle workers, or if
# you need to run the celery task using solo pool (e.g. on Windows). You may need to provide another
# way of monitoring celery so you can detect the background task not being available.
CELERY_CHECK_ONLY_INSPECT_BROKER = False

CANTALOUPE_DIR = os.path.join(ROOT_DIR, UPLOADED_FILES_DIR)
CANTALOUPE_HTTP_ENDPOINT = "http://localhost:8182/"

ACCESSIBILITY_MODE = False

RENDERERS = [
    {
        "name": "imagereader",
        "title": "Image Reader",
        "description": "Displays most image file types",
        "id": "5e05aa2e-5db0-4922-8938-b4d2b7919733",
        "iconclass": "fa fa-camera",
        "component": "views/components/cards/file-renderers/imagereader",
        "ext": "",
        "type": "image/*",
        "exclude": "tif,tiff,psd",
    },
    {
        "name": "pdfreader",
        "title": "PDF Reader",
        "description": "Displays pdf files",
        "id": "09dec059-1ee8-4fbd-85dd-c0ab0428aa94",
        "iconclass": "fa fa-file",
        "component": "views/components/cards/file-renderers/pdfreader",
        "ext": "pdf",
        "type": "application/pdf",
        "exclude": "tif,tiff,psd",
    },
]

# By setting RESTRICT_MEDIA_ACCESS to True, media file requests outside of Arches will checked against nodegroup permissions.
RESTRICT_MEDIA_ACCESS = False

# By setting RESTRICT_CELERY_EXPORT_FOR_ANONYMOUS_USER to True, if the user is attempting
# to export search results above the SEARCH_EXPORT_IMMEDIATE_DOWNLOAD_THRESHOLD
# value and is not signed in with a user account then the request will not be allowed.
RESTRICT_CELERY_EXPORT_FOR_ANONYMOUS_USER = False

# Dictionary containing any additional context items for customising email templates
EXTRA_EMAIL_CONTEXT = {
    "salutation": _("Hi"),
    "expiration": (
        datetime.now() + timedelta(seconds=CELERY_SEARCH_EXPORT_EXPIRES)
    ).strftime("%A, %d %B %Y"),
}

# see https://docs.djangoproject.com/en/1.9/topics/i18n/translation/#how-django-discovers-language-preference
# to see how LocaleMiddleware tries to determine the user's language preference
# (make sure to check your accept headers as they will override the LANGUAGE_CODE setting!)
# also see get_language_from_request in django.utils.translation.trans_real.py
# to see how the language code is derived in the actual code

####### TO GENERATE .PO FILES DO THE FOLLOWING ########
# run the following commands
# language codes used in the command should be in the form (which is slightly different
# form the form used in the LANGUAGE_CODE and LANGUAGES settings below):
# --local={countrycode}_{REGIONCODE} <-- countrycode is lowercase, regioncode is uppercase, also notice the underscore instead of hyphen
# commands to run (to generate files for "British English, German, and Spanish"):
# django-admin.py makemessages --ignore=env/* --local=de --local=en --local=en_GB --local=es  --extension=htm,py
# django-admin.py compilemessages


# default language of the application
# language code needs to be all lower case with the form:
# {langcode}-{regioncode} eg: en, en-gb ....
# a list of language codes can be found here http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = "en"

# list of languages to display in the language switcher,
# if left empty or with a single entry then the switch won't be displayed
# language codes need to be all lower case with the form:
# {langcode}-{regioncode} eg: en, en-gb ....
# a list of language codes can be found here http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGES = [
    #   ('de', _('German')),
    ("en", _("English")),
    ("mi", _("Māori")),
    #   ('en-gb', _('British English')),
    #   ('es', _('Spanish')),
]

# override this to permenantly display/hide the language switcher
SHOW_LANGUAGE_SWITCH = len(LANGUAGES) > 1

# Implement this class to associate custom documents to the ES resource index
# See tests.views.search_tests.TestEsMappingModifier class for example
# ES_MAPPING_MODIFIER_CLASSES = ["catalina.search.es_mapping_modifier.EsMappingModifier"]

# ============================================================================
# Azure AD Configuration (django-azure-auth)
# ============================================================================

# Login/Logout redirect URLs
LOGIN_REDIRECT_URL = os.environ.get("LOGIN_REDIRECT_URL", "/")
LOGOUT_REDIRECT_URL = os.environ.get("LOGOUT_REDIRECT_URL", "/")
OAUTH_CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID", "")

AZURE_AUTH = {
    # Change with actual values needed
    "CLIENT_ID": os.environ.get("CLIENT_ID", ""),
    "CLIENT_SECRET": os.environ.get("AZURE_CLIENT_SECRET", ""),
    "CLIENT_TYPE": os.environ.get("AZURE_CLIENT_TYPE", "public_client"),
    "TENANT_ID": os.environ.get("AZURE_TENANT_ID", ""),
    "AUTHORITY": os.environ.get(
        "AZURE_AUTHORITY",
        "https://login.microsoftonline.com/c96bb5bc-ccef-481c-b886-6aa10e107810",
    ),
    "REDIRECT_URI": os.environ.get(
        "AZURE_REDIRECT_URI", "http://localhost:8000/azure_auth/callback"
    ),
    "SCOPES": [
        "User.Read"
    ],  # Only non-reserved scopes (openid, profile, email are added automatically)
    "PROMPT": "select_account",
    "PUBLIC_URLS": [
        "azure_auth:login",
        "azure_auth:callback",
    ],
    # User management
    "USERNAME_ATTRIBUTE": "mail",
    "SAVE_ID_TOKEN_CLAIMS": True,  # Store user claims in session
    "AUTO_CREATE_USERS": True,  # Create Django users from Azure AD accounts
    "AUTO_CREATE_UNKNOWN_USERS": True,  # Create users even if not in directory
}

LOGIN_URL = "/azure_auth/login"
LOGIN_REDIRECT_URL = "/"  # Or any other endpoint

AUTHENTICATION_BACKENDS = [
    # Do we need this? "arches.app.utils.email_auth_backend.EmailAuthenticationBackend",
    "django.contrib.auth.backends.ModelBackend",
    "oauth2_provider.backends.OAuth2Backend",
    "arches.app.permissions.arches_permission_base.PermissionBackend",
    "arches.app.utils.external_oauth_backend.ExternalOauthAuthenticationBackend",
    "azure_auth.backends.AzureBackend",
]

# Portal host, with trailing /hosting suffix.
ARCGIS_PORTAL_URL = os.environ.get("ARCGIS_PORTAL_URL", "")
ARCGIS_PORTAL_USERNAME = os.environ.get("ARCGIS_PORTAL_USERNAME", "")
ARCGIS_PORTAL_PASSWORD = os.environ.get("ARCGIS_PORTAL_PASSWORD", "")

# Optional. Defaults to <ARCGIS_PORTAL_URL>/portal/sharing/rest/generateToken.
# Set this if the portal uses a non-standard web context name.
ARCGIS_PORTAL_TOKEN_GENERATE_URL = os.environ.get(
    "ARCGIS_PORTAL_TOKEN_GENERATE_URL", ""
)

# Slug -> service path from the portal host root (no leading slash).
# Defaults match prod portal naming; override per-env via ARCGIS_PORTAL_SERVICE_<SLUG>
# enable dev portals that expose a corresponding service under different names.
ARCGIS_PORTAL_SERVICES = {
    "nzaa": os.environ.get(
        "ARCGIS_PORTAL_SERVICE_NZAA",
        "NZAA_ArchSiteBuffer_HFLr/FeatureServer",
    ),
    "cons_land": os.environ.get(
        "ARCGIS_PORTAL_SERVICE_CONS_LAND",
        "NAPALIS_ProtectedArea_PublicConservationLand/FeatureServer",
    ),
    "ops_regions": os.environ.get(
        "ARCGIS_PORTAL_SERVICE_OPS_REGIONS",
        "DOC_OperationsRegions_HFLr/FeatureServer",
    ),
    "ops_districts": os.environ.get(
        "ARCGIS_PORTAL_SERVICE_OPS_DISTRICTS",
        "DOC_OperationsDistricts_HFLr/FeatureServer",
    ),
}

# Referer-restricted public key for LINZ Basemaps (aerial photo overlay).
LINZ_BASEMAPS_API_KEY = os.environ.get("LINZ_BASEMAPS_API_KEY", "")

# Slugs of portal-backed overlays this env should register. DOC's portals
# get reshuffled occasionally, so each env declares its own availability.
_DEFAULT_PORTAL_OVERLAYS = "cons_land,ops_regions,ops_districts"
PORTAL_OVERLAYS_AVAILABLE = {
    s.strip()
    for s in os.environ.get(
        "PORTAL_OVERLAYS_AVAILABLE", _DEFAULT_PORTAL_OVERLAYS
    ).split(",")
    if s.strip()
}

try:
    from .package_settings import *
except ImportError:
    try:
        from package_settings import *
    except ImportError as e:
        pass

try:
    from .settings_local import *
except ImportError as e:
    try:
        from settings_local import *
    except ImportError as e:
        pass
