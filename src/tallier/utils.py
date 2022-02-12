# Copyright (C) 2021-2022 Arthur Zamarin
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from random import choices
from functools import reduce
from itertools import starmap
import operator


def clean_gen_shamir(value: int, key_count: int, threshold: int, p: int) -> tuple[int]:
    a_i = [value] + choices(range(p), k=threshold - 1)
    return tuple(sum(a * pow(x + 1, i, p) for i, a in enumerate(a_i)) % p for x in range(key_count))


def gen_shamir(value: int, key_count: int, threshold: int, p: int) -> [[int, int]]:
    a_i = [value] + choices(range(p), k=threshold - 1)
    return tuple((x, sum((a * x ** i for i, a in enumerate(a_i))) % p) for x in range(1, key_count + 1))


def resolve(keys: [int], p: int):
    def l(x_i, y_i):
        c1, c2 = 1, 1
        for x_j, _ in keys:
            if x_j != x_i:
                c1 *= x_j
                c2 *= ((x_j - x_i) % p)
        return (c1 * pow(c2, -1, p) * y_i) % p
    keys = tuple(enumerate(keys, start=1))
    return sum(starmap(l, keys)) % p


def inverse(a, p):
    def eliminate(r1, r2, col, target=0):
        fac = (r2[col]-target) * pow(r1[col], -1, p)
        for i in range(len(r2)):
            r2[i] -= fac * r1[i]
            r2[i] %= p

    def gauss(a):
        for i in range(len(a)):
            if a[i][i] == 0:
                for j in range(i + 1, len(a)):
                    if a[i][j] != 0:
                        a[i], a[j] = a[j], a[i]
                        break
                else:
                    raise ValueError("Matrix is not invertible")
            for j in range(i + 1, len(a)):
                eliminate(a[i], a[j], i)
        for i in range(len(a) - 1, -1, -1):
            for j in range(i - 1, -1, -1):
                eliminate(a[i], a[j], i)
        for i in range(len(a)):
            eliminate(a[i], a[i], i, target=1)
        return a

    tmp = [[] for _ in a]
    for i, row in enumerate(a):
        assert len(row) == len(a)
        tmp[i].extend(row + [0] * i + [1] + [0] * (len(a) - i - 1))
    gauss(tmp)
    return [tmp[i][len(tmp[i]) // 2:] for i in range(len(tmp))]


def modular_sqrt(a, p):
    """ Find a quadratic residue (mod p) of 'a'. p must be an odd prime.

        Solve the congruence of the form:
            x^2 = a (mod p)
        And returns x. Note that p - x is also a root.

        0 is returned is no square root exists for these a and p.
    """
    def legendre_symbol(a):
        """ Compute the Legendre symbol a|p using Euler's criterion. p is a prime, a is
            relatively prime to p (if p divides a, then a|p = 0)

            Returns 1 if a has a square root modulo p, -1 otherwise.
        """
        ls = pow(a, (p - 1) // 2, p)
        return -1 if ls == p - 1 else ls
    # Simple cases
    if a == 0 or p == 2 or legendre_symbol(a) != 1:
        return 0
    elif p % 4 == 3:
        return pow(a, (p + 1) // 4, p)

    # Partition p-1 to s * 2^e for an odd s (i.e.
    # reduce all the powers of 2 from p-1)
    #
    s, e = p - 1, 0
    while s % 2 == 0:
        s //= 2
        e += 1

    # Find some 'n' with a legendre symbol n|p = -1.
    # Shouldn't take long.
    n = 2
    while legendre_symbol(n) != -1:
        n += 1

    # x is a guess of the square root that gets better with each iteration.
    # b is the "fudge factor" - by how much we're off with the guess.
    # The invariant x^2 = ab (mod p) is maintained throughout the loop.
    # g is used for successive powers of n to update both a and b
    # r is the exponent - decreases with each update
    x, r = pow(a, (s + 1) // 2, p), e
    b, g = pow(a, s, p), pow(n, s, p)

    while True:
        t, m = b, 0
        for m in range(r):
            if t == 1: break
            t = pow(t, 2, p)

        if m == 0:
            return x

        gs = pow(g, 2 ** (r - m - 1), p)
        g = (gs * gs) % p
        x = (x * gs) % p
        b = (b * g) % p
        r = m


def lagrange_polynomial(points: list[[int, int]], p: int):
    def coeffs(a: [int]) -> [int]:
        assert len(a) > 0
        if len(a) == 1:
            return [-a[0], 1]
        sub = coeffs(a[1:])
        return [(x - y * a[0]) % p for x, y in zip([0] + sub, sub + [0])]

    def l_j(x_j: int) -> [int]:
        a = [x for x, _ in points if x != x_j]
        q = pow(reduce(operator.mul, (x_j - x for x in a)), -1, p)
        return [(x * q) % p for x in coeffs(a)]

    assert len(points) > 0
    res = [0] * len(points)
    for x_j, y_j in points:
        prod = [(x * y_j) % p for x in l_j(x_j)]
        res = tuple(map(sum, zip(res, prod)))
    return [x % p for x in res]
