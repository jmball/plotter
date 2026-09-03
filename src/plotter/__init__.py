from importlib.metadata import PackageNotFoundError, version

# get version if package has been installed
try:
    __version__ = version(__name__)
except PackageNotFoundError:
    __version__ = "0.0.0"
