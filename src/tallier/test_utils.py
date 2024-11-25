from random import randint

import pytest

from utils import clean_gen_shamir, resolve

p = 2 ** 31 - 1

@pytest.mark.parametrize("key_count", (3, 5, 7, 9))
def test_gen_shamir(key_count):
    for _ in range(10_000):
        a = randint(0, p - 1)
        shares = clean_gen_shamir(a, key_count, key_count // 2 + 1, p)
        assert resolve(shares, p) == a
