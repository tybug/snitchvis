from distutils.core import setup
from setuptools import find_packages
import re

# https://stackoverflow.com/a/7071358
VERSION = "Unknown"
VERSION_RE = r"^__version__ = ['\"]([^'\"]*)['\"]"

with open("snitchvis/version.py") as f:
    match = re.search(VERSION_RE, f.read())
    if match:
        VERSION = match.group(1)
    else:
        raise RuntimeError("Unable to find version string in "
            "snitchvis/version.py")

setup(
    name="snitchvis",
    version=VERSION,
    packages=find_packages(),
    install_requires=[
        "numpy",
        "PyQt6"
    ],
    package_data={
        "snitchvis": ["resources/*"]
    }
)
