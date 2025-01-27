import sys


if (sys.version_info.major >= 3) and (sys.version_info.minor >= 8):
    import importlib.metadata

    __version__ = importlib.metadata.version("equistore-core")

else:
    from pkg_resources import get_distribution

    __version__ = get_distribution("equistore-core").version
