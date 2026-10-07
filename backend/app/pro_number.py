"""12-digit PRO number helpers.

POC rule: positions 1-11 are the base, position 12 is a mod-7 check digit over the base.
Swap this for the real carrier algorithm when AS400 integration lands.
"""

import random


def compute_check_digit(base11: str) -> str:
    if len(base11) != 11 or not base11.isdigit():
        raise ValueError("PRO base must be 11 digits")
    return str(int(base11) % 7)


def is_valid_pro(pro_number: str) -> bool:
    value = (pro_number or "").strip()
    if len(value) != 12 or not value.isdigit():
        return False
    return compute_check_digit(value[:11]) == value[11]


def generate_pro(rng: random.Random | None = None) -> str:
    rng = rng or random
    base = "4021" + "".join(str(rng.randint(0, 9)) for _ in range(7))
    return base + compute_check_digit(base)
