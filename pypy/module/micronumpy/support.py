from rpython.rlib import jit


@jit.unroll_safe
def product(s):
    i = 1
    for x in s:
        i *= x
    return i

@jit.unroll_safe
def calc_strides(shape, dtype, order):
    strides = []
    backstrides = []
    s = 1
    shape_rev = shape[:]
    if order == 'C':
        shape_rev.reverse()
    for sh in shape_rev:
        strides.append(s * dtype.get_size())
        backstrides.append(s * (sh - 1) * dtype.get_size())
        s *= sh
    if order == 'C':
        strides.reverse()
        backstrides.reverse()
    return strides, backstrides
