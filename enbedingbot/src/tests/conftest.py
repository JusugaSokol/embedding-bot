import os

from django.conf import settings

os.environ["INGESTION_VECTOR_ALIAS"] = "default"


def pytest_configure():
    if "vectors" in settings.DATABASES:
        mirrors = settings.DATABASES["vectors"].get("TEST", {})
        settings.DATABASES["vectors"] = {
            **settings.DATABASES["default"],
            "TEST": {
                **mirrors,
                "MIRROR": "default",
            },
        }
