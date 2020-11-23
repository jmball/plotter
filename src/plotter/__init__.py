from pkg_resources import get_distribution, DistributionNotFound

# get version if package has been installed
if __version__ is None:
    try:
        __version__ = get_distribution(__name__).version
    except DistributionNotFound:
        __version__ = "0.0.0"
        pass
