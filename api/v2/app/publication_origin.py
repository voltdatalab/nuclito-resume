"""Trusted process configuration; never derived from webhook/HTTP input.

Production retains its existing www alias. Staging is an exclusive opt-in, not
an addition to the production allowlist. Invalid configuration fails closed.
"""
import os

PRODUCTION = 'https://nucleo.jor.br'
STAGING = 'https://staging.nucleo.jor.br'


def source_origin():
    origin = os.environ.get('PUBLICATION_SOURCE_ORIGIN', PRODUCTION)
    if origin not in (PRODUCTION, STAGING):
        raise ValueError('Invalid publication source configuration')
    return origin


def source_origins():
    origin = source_origin()
    return frozenset((PRODUCTION, 'https://www.nucleo.jor.br')) if origin == PRODUCTION else frozenset((origin,))
