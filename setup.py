from setuptools import setup

setup(
    name="avail",
    version="0.1.0",
    py_modules=["avail"],
    install_requires=[
        "google-auth-oauthlib>=0.4.6",
        "google-api-python-client>=2.47.0",
        "pytz>=2022.1",
        "click>=8.1.3",
        "python-dateutil>=2.8.2",
        "tzlocal>=4.2",
        "O365>=2.0.19",
    ],
    entry_points={
        "console_scripts": [
            "avail=avail:main",
        ],
    },
)
