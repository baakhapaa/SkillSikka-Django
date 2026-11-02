"""Validation shared by course foreign-key query filters."""
import re

from rest_framework.exceptions import ValidationError


def positive_id_param(params, field):
    """Absent means no filter; supplied IDs must fit a signed bigint PK."""
    if field not in params:
        return None
    value = params.get(field)
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+', value):
        raise ValidationError({field: 'Enter a positive integer ID.'})
    # Bound the string before int() so even extremely long input is harmless.
    digits = value.lstrip('0')
    maximum = '9223372036854775807'
    if not digits or len(digits) > len(maximum) or (len(digits) == len(maximum) and digits > maximum):
        raise ValidationError({field: 'Enter a positive integer ID within the supported range.'})
    return int(digits)
