from pypy.interpreter import gateway
from pypy.interpreter.error import OperationError
from pypy.objspace.std import newformat
from pypy.objspace.std.model import registerimplementation, W_Object
from pypy.objspace.std.register_all import register_all
from pypy.objspace.std.floatobject import W_FloatObject, _hash_float
from pypy.objspace.std.longobject import W_LongObject
from rpython.rlib.rbigint import rbigint
from rpython.rlib.rfloat import (
    formatd, DTSF_STR_PRECISION, isinf, isnan, copysign)
from rpython.rlib import jit, rcomplex
from rpython.rlib.rarithmetic import intmask

import math


class W_AbstractComplexObject(W_Object):
    __slots__ = ()

    def is_w(self, space, w_other):
        from rpython.rlib.longlong2float import float2longlong
        if not isinstance(w_other, W_AbstractComplexObject):
            return False
        if self.user_overridden_class or w_other.user_overridden_class:
            return self is w_other
        real1 = space.float_w(space.getattr(self,    space.wrap("real")))
        real2 = space.float_w(space.getattr(w_other, space.wrap("real")))
        imag1 = space.float_w(space.getattr(self,    space.wrap("imag")))
        imag2 = space.float_w(space.getattr(w_other, space.wrap("imag")))
        real1 = float2longlong(real1)
        real2 = float2longlong(real2)
        imag1 = float2longlong(imag1)
        imag2 = float2longlong(imag2)
        return real1 == real2 and imag1 == imag2

    def immutable_unique_id(self, space):
        if self.user_overridden_class:
            return None
        from rpython.rlib.longlong2float import float2longlong
        from pypy.objspace.std.model import IDTAG_COMPLEX as tag
        real = space.float_w(space.getattr(self, space.wrap("real")))
        imag = space.float_w(space.getattr(self, space.wrap("imag")))
        real_b = rbigint.fromrarith_int(float2longlong(real))
        imag_b = rbigint.fromrarith_int(float2longlong(imag))
        val = real_b.lshift(64).or_(imag_b).lshift(3).or_(rbigint.fromint(tag))
        return space.newlong_from_rbigint(val)


class W_ComplexObject(W_AbstractComplexObject):
    """This is a reimplementation of the CPython "PyComplexObject"
    """
    from pypy.objspace.std.complextype import complex_typedef as typedef
    _immutable_fields_ = ['realval', 'imagval']

    def __init__(w_self, realval=0.0, imgval=0.0):
        w_self.realval = float(realval)
        w_self.imagval = float(imgval)
#        w_self.taints = set()

    def unwrap(w_self, space):   # for tests only
        return complex(w_self.realval, w_self.imagval)

    def __repr__(w_self):
        """ representation for debugging purposes """
        return "<W_ComplexObject(%f,%f)>" % (w_self.realval, w_self.imagval)

    def as_tuple(self):
        return (self.realval, self.imagval)

    def sub(self, other):
        return W_ComplexObject(self.realval - other.realval,
                               self.imagval - other.imagval)

    def mul(self, other):
        r = self.realval * other.realval - self.imagval * other.imagval
        i = self.realval * other.imagval + self.imagval * other.realval
        return W_ComplexObject(r, i)

    def div(self, other):
        rr, ir = rcomplex.c_div(self.as_tuple(), other.as_tuple())
        return W_ComplexObject(rr, ir)

    def divmod(self, space, other):
        space.warn(
            "complex divmod(), // and % are deprecated",
            space.w_DeprecationWarning
        )
        w_div = self.div(other)
        div = math.floor(w_div.realval)
        w_mod = self.sub(
            W_ComplexObject(other.realval * div, other.imagval * div))
        return (W_ComplexObject(div, 0), w_mod)

    def pow(self, other):
        rr, ir = rcomplex.c_pow(self.as_tuple(), other.as_tuple())
        return W_ComplexObject(rr, ir)

    def pow_small_int(self, n):
        if n >= 0:
            if jit.isconstant(n) and n == 2:
                return self.mul(self)
            return self.pow_positive_int(n)
        else:
            return w_one.div(self.pow_positive_int(-n))

    def pow_positive_int(self, n):
        mask = 1
        w_result = w_one
        while mask > 0 and n >= mask:
            if n & mask:
                w_result = w_result.mul(self)
            mask <<= 1
            self = self.mul(self)

        return w_result

registerimplementation(W_ComplexObject)

w_one = W_ComplexObject(1, 0)


def delegate_Bool2Complex(space, w_bool):
    return W_ComplexObject(w_bool.boolval, 0.0)

def delegate_Int2Complex(space, w_int):
    return W_ComplexObject(w_int.intval, 0.0)

def delegate_Long2Complex(space, w_long):
    try:
        dval =  w_long.tofloat()
    except OverflowError, e:
        raise OperationError(space.w_OverflowError, space.wrap(str(e)))
    return W_ComplexObject(dval, 0.0)

def delegate_Float2Complex(space, w_float):
    return W_ComplexObject(w_float.floatval, 0.0)

def hash__Complex(space, w_value):
    hashreal = _hash_float(space, w_value.realval)
    hashimg = _hash_float(space, w_value.imagval)
    combined = intmask(hashreal + 1000003 * hashimg)
    return space.newint(combined)

def add__Complex_Complex(space, w_complex1, w_complex2):
    return W_ComplexObject(w_complex1.realval + w_complex2.realval,
                           w_complex1.imagval + w_complex2.imagval)

def sub__Complex_Complex(space, w_complex1, w_complex2):
    return W_ComplexObject(w_complex1.realval - w_complex2.realval,
                           w_complex1.imagval - w_complex2.imagval)

def mul__Complex_Complex(space, w_complex1, w_complex2):
    return w_complex1.mul(w_complex2)

def div__Complex_Complex(space, w_complex1, w_complex2):
    try:
        return w_complex1.div(w_complex2)
    except ZeroDivisionError, e:
        raise OperationError(space.w_ZeroDivisionError, space.wrap(str(e)))

truediv__Complex_Complex = div__Complex_Complex

def mod__Complex_Complex(space, w_complex1, w_complex2):
    try:
        return w_complex1.divmod(space, w_complex2)[1]
    except ZeroDivisionError, e:
        raise OperationError(space.w_ZeroDivisionError, space.wrap(str(e)))

def divmod__Complex_Complex(space, w_complex1, w_complex2):
    try:
        div, mod = w_complex1.divmod(space, w_complex2)
    except ZeroDivisionError, e:
        raise OperationError(space.w_ZeroDivisionError, space.wrap(str(e)))
    return space.newtuple([div, mod])

def floordiv__Complex_Complex(space, w_complex1, w_complex2):
    # don't care about the slight slowdown you get from using divmod
    try:
        return w_complex1.divmod(space, w_complex2)[0]
    except ZeroDivisionError, e:
        raise OperationError(space.w_ZeroDivisionError, space.wrap(str(e)))

def pow__Complex_Complex_ANY(space, w_complex, w_exponent, thirdArg):
    if not space.is_w(thirdArg, space.w_None):
        raise OperationError(space.w_ValueError, space.wrap('complex modulo'))
    try:
        r = w_exponent.realval
        if w_exponent.imagval == 0.0 and -100.0 <= r <= 100.0 and r == int(r):
            w_p = w_complex.pow_small_int(int(r))
        else:
            w_p = w_complex.pow(w_exponent)
    except ZeroDivisionError:
        raise OperationError(space.w_ZeroDivisionError, space.wrap("0.0 to a negative or complex power"))
    except OverflowError:
        raise OperationError(space.w_OverflowError, space.wrap("complex exponentiation"))
    return w_p

def neg__Complex(space, w_complex):
    return W_ComplexObject(-w_complex.realval, -w_complex.imagval)

def pos__Complex(space, w_complex):
    return W_ComplexObject(w_complex.realval, w_complex.imagval)

def abs__Complex(space, w_complex):
    try:
        return space.newfloat(math.hypot(w_complex.realval, w_complex.imagval))
    except OverflowError, e:
        raise OperationError(space.w_OverflowError, space.wrap(str(e)))

def eq__Complex_Complex(space, w_complex1, w_complex2):
    return space.newbool((w_complex1.realval == w_complex2.realval) and
            (w_complex1.imagval == w_complex2.imagval))

def ne__Complex_Complex(space, w_complex1, w_complex2):
    return space.newbool((w_complex1.realval != w_complex2.realval) or
            (w_complex1.imagval != w_complex2.imagval))

def eq__Complex_Long(space, w_complex1, w_long2):
    if w_complex1.imagval:
        return space.w_False
    return space.eq(space.newfloat(w_complex1.realval), w_long2)

def eq__Long_Complex(space, w_long1, w_complex2):
    return eq__Complex_Long(space, w_complex2, w_long1)

def ne__Complex_Long(space, w_complex1, w_long2):
    if w_complex1.imagval:
        return space.w_True
    return space.ne(space.newfloat(w_complex1.realval), w_long2)

def ne__Long_Complex(space, w_long1, w_complex2):
    return ne__Complex_Long(space, w_complex2, w_long1)

def lt__Complex_Complex(space, w_complex1, w_complex2):
    raise OperationError(space.w_TypeError, space.wrap('cannot compare complex numbers using <, <=, >, >='))

gt__Complex_Complex = lt__Complex_Complex
ge__Complex_Complex = lt__Complex_Complex
le__Complex_Complex = lt__Complex_Complex

def nonzero__Complex(space, w_complex):
    return space.newbool((w_complex.realval != 0.0) or
                         (w_complex.imagval != 0.0))

def coerce__Complex_Complex(space, w_complex1, w_complex2):
    return space.newtuple([w_complex1, w_complex2])

def float__Complex(space, w_complex):
    raise OperationError(space.w_TypeError, space.wrap("can't convert complex to float; use abs(z)"))

def int__Complex(space, w_complex):
    raise OperationError(space.w_TypeError, space.wrap("can't convert complex to int; use int(abs(z))"))

def complex_conjugate__Complex(space, w_self):
    #w_real = space.call_function(space.w_float,space.wrap(w_self.realval))
    #w_imag = space.call_function(space.w_float,space.wrap(-w_self.imagval))
    return space.newcomplex(w_self.realval,-w_self.imagval)

def format_float(x, code, precision):
    # like float2string, except that the ".0" is not necessary
    if isinf(x):
        if x > 0.0:
            return "inf"
        else:
            return "-inf"
    elif isnan(x):
        return "nan"
    else:
        return formatd(x, code, precision)

def repr_format(x):
    return format_float(x, 'r', 0)
def str_format(x):
    return format_float(x, 'g', DTSF_STR_PRECISION)

def repr__Complex(space, w_complex):
    if w_complex.realval == 0 and copysign(1., w_complex.realval) == 1.:
        return space.wrap(repr_format(w_complex.imagval) + 'j')
    sign = (copysign(1., w_complex.imagval) == 1. or
            isnan(w_complex.imagval)) and '+' or ''
    return space.wrap('(' + repr_format(w_complex.realval)
                      + sign + repr_format(w_complex.imagval) + 'j)')

def str__Complex(space, w_complex):
    if w_complex.realval == 0 and copysign(1., w_complex.realval) == 1.:
        return space.wrap(str_format(w_complex.imagval) + 'j')
    sign = (copysign(1., w_complex.imagval) == 1. or
            isnan(w_complex.imagval)) and '+' or ''
    return space.wrap('(' + str_format(w_complex.realval)
                      + sign + str_format(w_complex.imagval) + 'j)')

def format__Complex_ANY(space, w_complex, w_format_spec):
    return newformat.run_formatter(space, w_format_spec, "format_complex", w_complex)

from pypy.objspace.std import complextype
register_all(vars(), complextype)
