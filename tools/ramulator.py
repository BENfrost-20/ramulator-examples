"""Locate the Ferrandi Ramulator installations consumed by MDPI and Verilator."""
from pathlib import Path


API_VERSION = '2.1'


def library_candidates(prefix):
    return [
        prefix / 'lib/libramulator.so',
        prefix / 'lib64/libramulator.so',
        *sorted((prefix / 'lib').glob('*/libramulator.so')),
    ]


def require_headers(prefix):
    include = prefix / 'include/ramulator'
    if not all((include / header).is_file() for header in (
        'base/config.h', 'frontend/i_frontend.h', 'bambu/legacy_config.h',
    )):
        raise ValueError(f'Ferrandi Ramulator {API_VERSION} headers missing in {include}; check RAMULATOR2_DIR')


def installed_library(prefix, libdir=None):
    candidates = [Path(libdir) / 'libramulator.so'] if libdir else library_candidates(prefix)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ValueError(f'libramulator.so missing in {libdir or prefix}; check RAMULATOR2_DIR and RAMULATOR2_LIBDIR')
