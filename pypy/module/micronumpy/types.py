import functools
import math

from pypy.interpreter.error import OperationError
from pypy.module.micronumpy import interp_boxes
from pypy.module.micronumpy.arrayimpl.voidbox import VoidBoxStorage
from pypy.objspace.std.floatobject import float2string
from pypy.objspace.std.complexobject import str_format
from rpython.rlib import rfloat, clibffi, rcomplex
from rpython.rlib.rawstorage import (alloc_raw_storage, raw_storage_setitem,
                                  raw_storage_getitem)
from rpython.rlib.objectmodel import specialize
from rpython.rlib.rarithmetic import widen, byteswap, r_ulonglong
from rpython.rtyper.lltypesystem import lltype, rffi
from rpython.rlib.rstruct.runpack import runpack
from rpython.rlib.rstruct.nativefmttable import native_is_bigendian
from rpython.rlib.rstruct.ieee import (float_pack, float_unpack, 
                                    unpack_float, unpack_float128)
from rpython.tool.sourcetools import func_with_new_name
from rpython.rlib import jit
from rpython.rlib.rstring import StringBuilder

degToRad = math.pi / 180.0
log2 = math.log(2)
log2e = 1. / log2

def isfinite(d):
    return not rfloat.isinf(d) and not rfloat.isnan(d)

def simple_unary_op(func):
    specialize.argtype(1)(func)
    @functools.wraps(func)
    def dispatcher(self, v):
        return self.box(
            func(
                self,
                self.for_computation(self.unbox(v))
            )
        )
    return dispatcher

def complex_unary_op(func):
    specialize.argtype(1)(func)
    @functools.wraps(func)
    def dispatcher(self, v):
        return self.box_complex(
            *func(
                self,
                self.for_computation(self.unbox(v))
            )
        )
    return dispatcher

def complex_to_real_unary_op(func):
    specialize.argtype(1)(func)
    @functools.wraps(func)
    def dispatcher(self, v):
        from pypy.module.micronumpy.interp_boxes import W_GenericBox
        assert isinstance(v, W_GenericBox)
        return self.box_component(
            func(
                self,
                self.for_computation(self.unbox(v))
            )
        )
    return dispatcher


def raw_unary_op(func):
    specialize.argtype(1)(func)
    @functools.wraps(func)
    def dispatcher(self, v):
        return func(
            self,
            self.for_computation(self.unbox(v))
        )
    return dispatcher

def simple_binary_op(func):
    specialize.argtype(1, 2)(func)
    @functools.wraps(func)
    def dispatcher(self, v1, v2):
        return self.box(
            func(
                self,
                self.for_computation(self.unbox(v1)),
                self.for_computation(self.unbox(v2)),
            )
        )
    return dispatcher

def complex_binary_op(func):
    specialize.argtype(1, 2)(func)
    @functools.wraps(func)
    def dispatcher(self, v1, v2):
        return self.box_complex(
            *func(
                self,
                self.for_computation(self.unbox(v1)),
                self.for_computation(self.unbox(v2)),
            )
        )
    return dispatcher

def raw_binary_op(func):
    specialize.argtype(1, 2)(func)
    @functools.wraps(func)
    def dispatcher(self, v1, v2):
        return func(self,
            self.for_computation(self.unbox(v1)),
            self.for_computation(self.unbox(v2))
        )
    return dispatcher

class BaseType(object):
    _attrs_ = ()

    def _unimplemented_ufunc(self, *args):
        raise NotImplementedError

    def malloc(self, size):
        return alloc_raw_storage(size, track_allocation=False, zero=True)

    def __repr__(self):
        return self.__class__.__name__

class Primitive(object):
    _mixin_ = True

    def get_element_size(self):
        return rffi.sizeof(self.T)

    @specialize.argtype(1)
    def box(self, value):
        return self.BoxType(rffi.cast(self.T, value))

    def unbox(self, box):
        assert isinstance(box, self.BoxType)
        return box.value

    def coerce(self, space, dtype, w_item):
        if isinstance(w_item, self.BoxType):
            return w_item
        return self.coerce_subtype(space, space.gettypefor(self.BoxType), w_item)

    def coerce_subtype(self, space, w_subtype, w_item):
        # XXX: ugly
        w_obj = space.allocate_instance(self.BoxType, w_subtype)
        assert isinstance(w_obj, self.BoxType)
        w_obj.__init__(self._coerce(space, w_item).value)
        return w_obj

    def to_builtin_type(self, space, box):
        return space.wrap(self.for_computation(self.unbox(box)))

    def _coerce(self, space, w_item):
        raise NotImplementedError

    def default_fromstring(self, space):
        raise NotImplementedError

    def _read(self, storage, i, offset):
        return raw_storage_getitem(self.T, storage, i + offset)

    def read(self, arr, i, offset, dtype=None):
        return self.box(self._read(arr.storage, i, offset))

    def read_bool(self, arr, i, offset):
        return bool(self.for_computation(self._read(arr.storage, i, offset)))

    def _write(self, storage, i, offset, value):
        raw_storage_setitem(storage, i + offset, value)

    def store(self, arr, i, offset, box):
        self._write(arr.storage, i, offset, self.unbox(box))

    def fill(self, storage, width, box, start, stop, offset):
        value = self.unbox(box)
        for i in xrange(start, stop, width):
            self._write(storage, i, offset, value)

    def runpack_str(self, s):
        v = runpack(self.format_code, s)
        return self.box(v)

    @simple_binary_op
    def add(self, v1, v2):
        return v1 + v2

    @simple_binary_op
    def sub(self, v1, v2):
        return v1 - v2

    @simple_binary_op
    def mul(self, v1, v2):
        return v1 * v2

    @simple_unary_op
    def pos(self, v):
        return +v

    @simple_unary_op
    def neg(self, v):
        return -v

    @simple_unary_op
    def conj(self, v):
        return v

    @simple_unary_op
    def real(self, v):
        return v

    @simple_unary_op
    def imag(self, v):
        return 0

    @simple_unary_op
    def abs(self, v):
        return abs(v)

    @raw_unary_op
    def isnan(self, v):
        return False

    @raw_unary_op
    def isinf(self, v):
        return False

    @raw_unary_op
    def isneginf(self, v):
        return False

    @raw_unary_op
    def isposinf(self, v):
        return False

    @raw_binary_op
    def eq(self, v1, v2):
        return v1 == v2

    @raw_binary_op
    def ne(self, v1, v2):
        return v1 != v2

    @raw_binary_op
    def lt(self, v1, v2):
        return v1 < v2

    @raw_binary_op
    def le(self, v1, v2):
        return v1 <= v2

    @raw_binary_op
    def gt(self, v1, v2):
        return v1 > v2

    @raw_binary_op
    def ge(self, v1, v2):
        return v1 >= v2

    @raw_binary_op
    def logical_and(self, v1, v2):
        return bool(v1) and bool(v2)

    @raw_binary_op
    def logical_or(self, v1, v2):
        return bool(v1) or bool(v2)

    @raw_unary_op
    def logical_not(self, v):
        return not bool(v)

    @raw_binary_op
    def logical_xor(self, v1, v2):
        return bool(v1) ^ bool(v2)

    def bool(self, v):
        return bool(self.for_computation(self.unbox(v)))

    @simple_binary_op
    def max(self, v1, v2):
        return max(v1, v2)

    @simple_binary_op
    def min(self, v1, v2):
        return min(v1, v2)

class NonNativePrimitive(Primitive):
    _mixin_ = True

    def _read(self, storage, i, offset):
        res = raw_storage_getitem(self.T, storage, i + offset)
        return byteswap(res)

    def _write(self, storage, i, offset, value):
        value = byteswap(value)
        raw_storage_setitem(storage, i + offset, value)

class Bool(BaseType, Primitive):
    _attrs_ = ()

    T = lltype.Bool
    BoxType = interp_boxes.W_BoolBox
    format_code = "?"

    True = BoxType(True)
    False = BoxType(False)

    @specialize.argtype(1)
    def box(self, value):
        box = Primitive.box(self, value)
        if box.value:
            return self.True
        else:
            return self.False

    def coerce_subtype(self, space, w_subtype, w_item):
        # Doesn't return subclasses so it can return the constants.
        return self._coerce(space, w_item)

    def _coerce(self, space, w_item):
        return self.box(space.is_true(w_item))

    def to_builtin_type(self, space, w_item):
        return space.wrap(self.unbox(w_item))

    def str_format(self, box):
        return "True" if self.unbox(box) else "False"

    def for_computation(self, v):
        return int(v)

    def default_fromstring(self, space):
        return self.box(True)

    @simple_binary_op
    def bitwise_and(self, v1, v2):
        return v1 & v2

    @simple_binary_op
    def bitwise_or(self, v1, v2):
        return v1 | v2

    @simple_binary_op
    def bitwise_xor(self, v1, v2):
        return v1 ^ v2

    @simple_unary_op
    def invert(self, v):
        return ~v

NonNativeBool = Bool

class Integer(Primitive):
    _mixin_ = True

    def _base_coerce(self, space, w_item):
        return self.box(space.int_w(space.call_function(space.w_int, w_item)))
    def _coerce(self, space, w_item):
        return self._base_coerce(space, w_item)

    def str_format(self, box):
        return str(self.for_computation(self.unbox(box)))

    def for_computation(self, v):
        return widen(v)

    def default_fromstring(self, space):
        return self.box(0)

    @simple_binary_op
    def div(self, v1, v2):
        if v2 == 0:
            return 0
        return v1 / v2

    @simple_binary_op
    def floordiv(self, v1, v2):
        if v2 == 0:
            return 0
        return v1 // v2

    @simple_binary_op
    def mod(self, v1, v2):
        return v1 % v2

    @simple_binary_op
    def pow(self, v1, v2):
        if v2 < 0:
            return 0
        res = 1
        while v2 > 0:
            if v2 & 1:
                res *= v1
            v2 >>= 1
            if v2 == 0:
                break
            v1 *= v1
        return res

    @simple_binary_op
    def lshift(self, v1, v2):
        return v1 << v2

    @simple_binary_op
    def rshift(self, v1, v2):
        return v1 >> v2

    @simple_unary_op
    def sign(self, v):
        if v > 0:
            return 1
        elif v < 0:
            return -1
        else:
            assert v == 0
            return 0

    @raw_unary_op
    def isfinite(self, v):
        return True

    @raw_unary_op
    def isnan(self, v):
        return False

    @raw_unary_op
    def isinf(self, v):
        return False

    @raw_unary_op
    def isposinf(self, v):
        return False

    @raw_unary_op
    def isneginf(self, v):
        return False

    @simple_binary_op
    def bitwise_and(self, v1, v2):
        return v1 & v2

    @simple_binary_op
    def bitwise_or(self, v1, v2):
        return v1 | v2

    @simple_binary_op
    def bitwise_xor(self, v1, v2):
        return v1 ^ v2

    @simple_unary_op
    def invert(self, v):
        return ~v

class NonNativeInteger(NonNativePrimitive, Integer):
    _mixin_ = True

class Int8(BaseType, Integer):
    _attrs_ = ()

    T = rffi.SIGNEDCHAR
    BoxType = interp_boxes.W_Int8Box
    format_code = "b"
NonNativeInt8 = Int8

class UInt8(BaseType, Integer):
    _attrs_ = ()

    T = rffi.UCHAR
    BoxType = interp_boxes.W_UInt8Box
    format_code = "B"
NonNativeUInt8 = UInt8

class Int16(BaseType, Integer):
    _attrs_ = ()

    T = rffi.SHORT
    BoxType = interp_boxes.W_Int16Box
    format_code = "h"

class NonNativeInt16(BaseType, NonNativeInteger):
    _attrs_ = ()

    T = rffi.SHORT
    BoxType = interp_boxes.W_Int16Box
    format_code = "h"

class UInt16(BaseType, Integer):
    _attrs_ = ()

    T = rffi.USHORT
    BoxType = interp_boxes.W_UInt16Box
    format_code = "H"

class NonNativeUInt16(BaseType, NonNativeInteger):
    _attrs_ = ()

    T = rffi.USHORT
    BoxType = interp_boxes.W_UInt16Box
    format_code = "H"

class Int32(BaseType, Integer):
    _attrs_ = ()

    T = rffi.INT
    BoxType = interp_boxes.W_Int32Box
    format_code = "i"

class NonNativeInt32(BaseType, NonNativeInteger):
    _attrs_ = ()

    T = rffi.INT
    BoxType = interp_boxes.W_Int32Box
    format_code = "i"

class UInt32(BaseType, Integer):
    _attrs_ = ()

    T = rffi.UINT
    BoxType = interp_boxes.W_UInt32Box
    format_code = "I"

class NonNativeUInt32(BaseType, NonNativeInteger):
    _attrs_ = ()

    T = rffi.UINT
    BoxType = interp_boxes.W_UInt32Box
    format_code = "I"

class Long(BaseType, Integer):
    _attrs_ = ()

    T = rffi.LONG
    BoxType = interp_boxes.W_LongBox
    format_code = "l"

class NonNativeLong(BaseType, NonNativeInteger):
    _attrs_ = ()

    T = rffi.LONG
    BoxType = interp_boxes.W_LongBox
    format_code = "l"

class ULong(BaseType, Integer):
    _attrs_ = ()

    T = rffi.ULONG
    BoxType = interp_boxes.W_ULongBox
    format_code = "L"

class NonNativeULong(BaseType, NonNativeInteger):
    _attrs_ = ()

    T = rffi.ULONG
    BoxType = interp_boxes.W_ULongBox
    format_code = "L"

def _int64_coerce(self, space, w_item):
    try:
        return self._base_coerce(space, w_item)
    except OperationError, e:
        if not e.match(space, space.w_OverflowError):
            raise
    bigint = space.bigint_w(w_item)
    try:
        value = bigint.tolonglong()
    except OverflowError:
        raise OperationError(space.w_OverflowError, space.w_None)
    return self.box(value)

class Int64(BaseType, Integer):
    _attrs_ = ()

    T = rffi.LONGLONG
    BoxType = interp_boxes.W_Int64Box
    format_code = "q"

    _coerce = func_with_new_name(_int64_coerce, '_coerce')

class NonNativeInt64(BaseType, NonNativeInteger):
    _attrs_ = ()

    T = rffi.LONGLONG
    BoxType = interp_boxes.W_Int64Box
    format_code = "q"

    _coerce = func_with_new_name(_int64_coerce, '_coerce')

def _uint64_coerce(self, space, w_item):
    try:
        return self._base_coerce(space, w_item)
    except OperationError, e:
        if not e.match(space, space.w_OverflowError):
            raise
    bigint = space.bigint_w(w_item)
    try:
        value = bigint.toulonglong()
    except OverflowError:
        raise OperationError(space.w_OverflowError, space.w_None)
    return self.box(value)

class UInt64(BaseType, Integer):
    _attrs_ = ()

    T = rffi.ULONGLONG
    BoxType = interp_boxes.W_UInt64Box
    format_code = "Q"

    _coerce = func_with_new_name(_uint64_coerce, '_coerce')

class NonNativeUInt64(BaseType, NonNativeInteger):
    _attrs_ = ()

    T = rffi.ULONGLONG
    BoxType = interp_boxes.W_UInt64Box
    format_code = "Q"

    _coerce = func_with_new_name(_uint64_coerce, '_coerce')

class Float(Primitive):
    _mixin_ = True

    def _coerce(self, space, w_item):
        return self.box(space.float_w(space.call_function(space.w_float, w_item)))

    def str_format(self, box):
        return float2string(self.for_computation(self.unbox(box)), "g",
                            rfloat.DTSF_STR_PRECISION)

    def for_computation(self, v):
        return float(v)

    def default_fromstring(self, space):
        return self.box(-1.0)

    @simple_binary_op
    def div(self, v1, v2):
        try:
            return v1 / v2
        except ZeroDivisionError:
            if v1 == v2 == 0.0:
                return rfloat.NAN
            return rfloat.copysign(rfloat.INFINITY, v1 * v2)

    @simple_binary_op
    def floordiv(self, v1, v2):
        try:
            return math.floor(v1 / v2)
        except ZeroDivisionError:
            if v1 == v2 == 0.0:
                return rfloat.NAN
            return rfloat.copysign(rfloat.INFINITY, v1 * v2)

    @simple_binary_op
    def mod(self, v1, v2):
        return math.fmod(v1, v2)

    @simple_binary_op
    def pow(self, v1, v2):
        try:
            return math.pow(v1, v2)
        except ValueError:
            return rfloat.NAN
        except OverflowError:
            if math.modf(v2)[0] == 0 and math.modf(v2 / 2)[0] != 0:
                # Odd integer powers result in the same sign as the base
                return rfloat.copysign(rfloat.INFINITY, v1)
            return rfloat.INFINITY

    @simple_binary_op
    def copysign(self, v1, v2):
        return math.copysign(v1, v2)

    @simple_unary_op
    def sign(self, v):
        if v == 0.0:
            return 0.0
        return rfloat.copysign(1.0, v)

    @raw_unary_op
    def signbit(self, v):
        return rfloat.copysign(1.0, v) < 0.0

    @simple_unary_op
    def fabs(self, v):
        return math.fabs(v)

    @simple_binary_op
    def fmax(self, v1, v2):
        if rfloat.isnan(v2):
            return v1
        elif rfloat.isnan(v1):
            return v2
        return max(v1, v2)

    @simple_binary_op
    def fmin(self, v1, v2):
        if rfloat.isnan(v2):
            return v1
        elif rfloat.isnan(v1):
            return v2
        return min(v1, v2)

    @simple_binary_op
    def fmod(self, v1, v2):
        try:
            return math.fmod(v1, v2)
        except ValueError:
            return rfloat.NAN

    @simple_unary_op
    def reciprocal(self, v):
        if v == 0.0:
            return rfloat.copysign(rfloat.INFINITY, v)
        return 1.0 / v

    @simple_unary_op
    def floor(self, v):
        return math.floor(v)

    @simple_unary_op
    def ceil(self, v):
        return math.ceil(v)

    @simple_unary_op
    def trunc(self, v):
        if v < 0:
            return math.ceil(v)
        else:
            return math.floor(v)

    @simple_unary_op
    def exp(self, v):
        try:
            return math.exp(v)
        except OverflowError:
            return rfloat.INFINITY

    @simple_unary_op
    def exp2(self, v):
        try:
            return math.pow(2, v)
        except OverflowError:
            return rfloat.INFINITY

    @simple_unary_op
    def expm1(self, v):
        try:
            return rfloat.expm1(v)
        except OverflowError:
            return rfloat.INFINITY

    @simple_unary_op
    def sin(self, v):
        return math.sin(v)

    @simple_unary_op
    def cos(self, v):
        return math.cos(v)

    @simple_unary_op
    def tan(self, v):
        return math.tan(v)

    @simple_unary_op
    def arcsin(self, v):
        if not -1.0 <= v <= 1.0:
            return rfloat.NAN
        return math.asin(v)

    @simple_unary_op
    def arccos(self, v):
        if not -1.0 <= v <= 1.0:
            return rfloat.NAN
        return math.acos(v)

    @simple_unary_op
    def arctan(self, v):
        return math.atan(v)

    @simple_binary_op
    def arctan2(self, v1, v2):
        return math.atan2(v1, v2)

    @simple_unary_op
    def sinh(self, v):
        return math.sinh(v)

    @simple_unary_op
    def cosh(self, v):
        return math.cosh(v)

    @simple_unary_op
    def tanh(self, v):
        return math.tanh(v)

    @simple_unary_op
    def arcsinh(self, v):
        return math.asinh(v)

    @simple_unary_op
    def arccosh(self, v):
        if v < 1.0:
            return rfloat.NAN
        return math.acosh(v)

    @simple_unary_op
    def arctanh(self, v):
        if v == 1.0 or v == -1.0:
            return math.copysign(rfloat.INFINITY, v)
        if not -1.0 < v < 1.0:
            return rfloat.NAN
        return math.atanh(v)

    @simple_unary_op
    def sqrt(self, v):
        try:
            return math.sqrt(v)
        except ValueError:
            return rfloat.NAN

    @simple_unary_op
    def square(self, v):
        return v*v

    @raw_unary_op
    def isnan(self, v):
        return rfloat.isnan(v)

    @raw_unary_op
    def isinf(self, v):
        return rfloat.isinf(v)

    @raw_unary_op
    def isneginf(self, v):
        return rfloat.isinf(v) and v < 0

    @raw_unary_op
    def isposinf(self, v):
        return rfloat.isinf(v) and v > 0

    @raw_unary_op
    def isfinite(self, v):
        return not (rfloat.isinf(v) or rfloat.isnan(v))

    @simple_unary_op
    def radians(self, v):
        return v * degToRad
    deg2rad = radians

    @simple_unary_op
    def degrees(self, v):
        return v / degToRad

    @simple_unary_op
    def log(self, v):
        try:
            return math.log(v)
        except ValueError:
            if v == 0.0:
                # CPython raises ValueError here, so we have to check
                # the value to find the correct numpy return value
                return -rfloat.INFINITY
            return rfloat.NAN

    @simple_unary_op
    def log2(self, v):
        try:
            return math.log(v) / log2
        except ValueError:
            if v == 0.0:
                # CPython raises ValueError here, so we have to check
                # the value to find the correct numpy return value
                return -rfloat.INFINITY
            return rfloat.NAN

    @simple_unary_op
    def log10(self, v):
        try:
            return math.log10(v)
        except ValueError:
            if v == 0.0:
                # CPython raises ValueError here, so we have to check
                # the value to find the correct numpy return value
                return -rfloat.INFINITY
            return rfloat.NAN

    @simple_unary_op
    def log1p(self, v):
        try:
            return rfloat.log1p(v)
        except OverflowError:
            return -rfloat.INFINITY
        except ValueError:
            return rfloat.NAN

    @simple_binary_op
    def logaddexp(self, v1, v2):
        tmp = v1 - v2
        if tmp > 0:
            return v1 + rfloat.log1p(math.exp(-tmp))
        elif tmp <= 0:
            return v2 + rfloat.log1p(math.exp(tmp))
        else:
            return v1 + v2

    def npy_log2_1p(self, v):
        return log2e * rfloat.log1p(v)

    @simple_binary_op
    def logaddexp2(self, v1, v2):
        tmp = v1 - v2
        if tmp > 0:
            return v1 + self.npy_log2_1p(math.pow(2, -tmp))
        if tmp <= 0:
            return v2 + self.npy_log2_1p(math.pow(2, tmp))
        else:
            return v1 + v2

class NonNativeFloat(NonNativePrimitive, Float):
    _mixin_ = True

    def _read(self, storage, i, offset):
        res = raw_storage_getitem(self.T, storage, i + offset)
        #return byteswap(res) XXX
        return res

    def _write(self, storage, i, offset, value):
        #value = byteswap(value) XXX
        raw_storage_setitem(storage, i + offset, value)


class Float16(BaseType, Float):
    _attrs_ = ()
    _STORAGE_T = rffi.USHORT
    T = rffi.DOUBLE

    BoxType = interp_boxes.W_Float16Box

    def get_element_size(self):
        return rffi.sizeof(self._STORAGE_T)

    def runpack_str(self, s):
        assert len(s) == 2
        fval = unpack_float(s, native_is_bigendian)
        return self.box(fval)

    def for_computation(self, v):
        return float(v)

    def default_fromstring(self, space):
        return self.box(-1.0)

    def _read(self, storage, i, offset):
        hbits = raw_storage_getitem(self._STORAGE_T, storage, i + offset)
        return float_unpack(r_ulonglong(hbits), 2)

    def _write(self, storage, i, offset, value):
        hbits = float_pack(value,2)
        raw_storage_setitem(storage, i + offset,
                rffi.cast(self._STORAGE_T, hbits))

class NonNativeFloat16(Float16):
    _attrs_ = ()
    BoxType = interp_boxes.W_Float16Box

    def _read(self, storage, i, offset):
        res = Float16._read(self, storage, i, offset)
        #return byteswap(res) XXX
        return res

    def _write(self, storage, i, offset, value):
        #value = byteswap(value) XXX
        Float16._write(self, storage, i, offset, value)

class Float32(BaseType, Float):
    _attrs_ = ()

    T = rffi.FLOAT
    BoxType = interp_boxes.W_Float32Box
    format_code = "f"

class NonNativeFloat32(BaseType, NonNativeFloat):
    _attrs_ = ()

    T = rffi.FLOAT
    BoxType = interp_boxes.W_Float32Box
    format_code = "f"

class Float64(BaseType, Float):
    _attrs_ = ()

    T = rffi.DOUBLE
    BoxType = interp_boxes.W_Float64Box
    format_code = "d"

class NonNativeFloat64(BaseType, NonNativeFloat):
    _attrs_ = ()

    T = rffi.DOUBLE
    BoxType = interp_boxes.W_Float64Box
    format_code = "d"

class ComplexFloating(object):
    _mixin_ = True
    _attrs_ = ()

    def _coerce(self, space, w_item):
        w_item = space.call_function(space.w_complex, w_item)
        real, imag = space.unpackcomplex(w_item)
        return self.box_complex(real, imag)

    def coerce(self, space, dtype, w_item):
        if isinstance(w_item, self.BoxType):
            return w_item
        return self.coerce_subtype(space, space.gettypefor(self.BoxType), w_item)

    def coerce_subtype(self, space, w_subtype, w_item):
        w_tmpobj = self._coerce(space, w_item)
        w_obj = space.allocate_instance(self.BoxType, w_subtype)
        assert isinstance(w_obj, self.BoxType)
        w_obj.__init__(w_tmpobj.real, w_tmpobj.imag)
        return w_obj

    def str_format(self, box):
        real, imag = self.for_computation(self.unbox(box))
        imag_str = str_format(imag) + 'j'
        
        # (0+2j) => 2j
        if real == 0:
            return imag_str        

        real_str = str_format(real)
        op = '+' if imag >= 0 else ''
        return ''.join(['(', real_str, op, imag_str, ')'])

    def for_computation(self, v):   
        return float(v[0]), float(v[1])

    def get_element_size(self):
        return 2 * rffi.sizeof(self._COMPONENTS_T)

    @specialize.argtype(1)
    def box(self, value):
        return self.BoxType(
            rffi.cast(self._COMPONENTS_T, value),
            rffi.cast(self._COMPONENTS_T, 0.0))

    @specialize.argtype(1)
    def box_component(self, value):
        return self.ComponentBoxType(
            rffi.cast(self._COMPONENTS_T, value))

    @specialize.argtype(1, 2)
    def box_complex(self, real, imag):
        return self.BoxType(
            rffi.cast(self._COMPONENTS_T, real),
            rffi.cast(self._COMPONENTS_T, imag))

    def unbox(self, box):
        assert isinstance(box, self.BoxType)
        # do this in two stages since real, imag are read only
        real, imag = box.real, box.imag
        return real, imag

    def store(self, arr, i, offset, box):
        real, imag = self.unbox(box)
        raw_storage_setitem(arr.storage, i+offset, real)
        raw_storage_setitem(arr.storage,
                i+offset+rffi.sizeof(self._COMPONENTS_T), imag)

    def _read(self, storage, i, offset):
        real = raw_storage_getitem(self._COMPONENTS_T, storage, i + offset)
        imag = raw_storage_getitem(self._COMPONENTS_T, storage,
                              i + offset + rffi.sizeof(self._COMPONENTS_T))
        return real, imag

    def read(self, arr, i, offset, dtype=None):
        real, imag = self._read(arr.storage, i, offset)
        return self.box_complex(real, imag)

    @complex_binary_op
    def add(self, v1, v2):
        return rcomplex.c_add(v1, v2)

    @complex_binary_op
    def sub(self, v1, v2):
        return rcomplex.c_sub(v1, v2)

    @complex_binary_op
    def mul(self, v1, v2):
        return rcomplex.c_mul(v1, v2)
    
    @complex_binary_op
    def div(self, v1, v2):
        try:
            return rcomplex.c_div(v1, v2)
        except ZeroDivisionError:
            if rcomplex.c_abs(*v1) == 0:
                return rfloat.NAN, rfloat.NAN
            return rfloat.INFINITY, rfloat.INFINITY

    @complex_unary_op
    def pos(self, v):
        return v

    @complex_unary_op
    def neg(self, v):
        return -v[0], -v[1]

    @complex_unary_op
    def conj(self, v):
        return v[0], -v[1]

    @complex_to_real_unary_op
    def real(self, v):
        return v[0]

    @complex_to_real_unary_op
    def imag(self, v):
        return v[1]

    @complex_to_real_unary_op
    def abs(self, v):
        return rcomplex.c_abs(v[0], v[1])

    @raw_unary_op
    def isnan(self, v):
        '''a complex number is nan if one of the parts is nan'''
        return rfloat.isnan(v[0]) or rfloat.isnan(v[1])

    @raw_unary_op
    def isinf(self, v):
        '''a complex number is inf if one of the parts is inf'''
        return rfloat.isinf(v[0]) or rfloat.isinf(v[1])

    def _eq(self, v1, v2):
        return v1[0] == v2[0] and v1[1] == v2[1]

    @raw_binary_op
    def eq(self, v1, v2):
        #compare the parts, so nan == nan is False
        return self._eq(v1, v2)

    @raw_binary_op
    def ne(self, v1, v2):
        return not self._eq(v1, v2)

    def _lt(self, v1, v2):
        (r1, i1), (r2, i2) = v1, v2
        if r1 < r2:
            return True
        elif not r1 <= r2:
            return False
        return i1 < i2

    @raw_binary_op
    def lt(self, v1, v2):
        return self._lt(v1, v2)

    @raw_binary_op
    def le(self, v1, v2):
        return self._lt(v1, v2) or self._eq(v1, v2) 

    @raw_binary_op
    def gt(self, v1, v2):
        return self._lt(v2, v1)

    @raw_binary_op
    def ge(self, v1, v2):
        return self._lt(v2, v1) or self._eq(v2, v1) 

    def _bool(self, v):
        return bool(v[0]) or bool(v[1])

    @raw_binary_op
    def logical_and(self, v1, v2):
        return self._bool(v1) and self._bool(v2)

    @raw_binary_op
    def logical_or(self, v1, v2):
        return self._bool(v1) or self._bool(v2)

    @raw_unary_op
    def logical_not(self, v):
        return not self._bool(v)

    @raw_binary_op
    def logical_xor(self, v1, v2):
        return self._bool(v1) ^ self._bool(v2)

    def min(self, v1, v2):
        return self.fmin(v1, v2)

    def max(self, v1, v2):
        return self.fmax(v1, v2)

    @complex_binary_op
    def floordiv(self, v1, v2):
        try:
            ab = v1[0]*v2[0] + v1[1]*v2[1]
            bb = v2[0]*v2[0] + v2[1]*v2[1]
            return math.floor(ab/bb), 0.
        except ZeroDivisionError:
            return rfloat.NAN, 0.

    #complex mod does not exist in numpy
    #@simple_binary_op
    #def mod(self, v1, v2):
    #    return math.fmod(v1, v2)

    @complex_binary_op
    def pow(self, v1, v2):
        if v1[1] == 0 and v2[1] == 0 and v1[0] > 0:
            return math.pow(v1[0], v2[0]), 0
        #if not isfinite(v1[0]) or not isfinite(v1[1]):
        #    return rfloat.NAN, rfloat.NAN
        try:
            return rcomplex.c_pow(v1, v2)
        except ZeroDivisionError:
            return rfloat.NAN, rfloat.NAN
        except OverflowError:
            return rfloat.INFINITY, -math.copysign(rfloat.INFINITY, v1[1])
        except ValueError:
            return rfloat.NAN, rfloat.NAN


    #complex copysign does not exist in numpy
    #@complex_binary_op
    #def copysign(self, v1, v2):
    #    return (rfloat.copysign(v1[0], v2[0]),
    #           rfloat.copysign(v1[1], v2[1]))

    @complex_unary_op
    def sign(self, v):
        '''
        sign of complex number could be either the point closest to the unit circle
        or {-1,0,1}, for compatability with numpy we choose the latter
        '''
        if v[0] == 0.0:
            if v[1] == 0:
                return 0,0
            if v[1] > 0:
                return 1,0
            return -1,0
        if v[0] > 0:
            return 1,0
        return -1,0

    def fmax(self, v1, v2):
        if self.isnan(v2):
            return v1
        elif self.isnan(v1):
            return v2
        if self.ge(v1, v2):
            return v1
        return v2

    def fmin(self, v1, v2):
        if self.isnan(v2):
            return v1
        elif self.isnan(v1):
            return v2
        if self.le(v1, v2):
            return v1
        return v2

    #@simple_binary_op
    #def fmod(self, v1, v2):
    #    try:
    #        return math.fmod(v1, v2)
    #    except ValueError:
    #        return rfloat.NAN

    @complex_unary_op
    def reciprocal(self, v):
        if rfloat.isinf(v[1]) and rfloat.isinf(v[0]):
            return rfloat.NAN, rfloat.NAN
        if rfloat.isinf(v[0]):
            return (rfloat.copysign(0., v[0]),
                    rfloat.copysign(0., -v[1]))
        a2 = v[0]*v[0] + v[1]*v[1]
        try:
            return rcomplex.c_div((v[0], -v[1]), (a2, 0.))
        except ZeroDivisionError:
            return rfloat.NAN, rfloat.NAN
 
    # No floor, ceil, trunc in numpy for complex
    #@simple_unary_op
    #def floor(self, v):
    #    return math.floor(v)

    #@simple_unary_op
    #def ceil(self, v):
    #    return math.ceil(v)

    #@simple_unary_op
    #def trunc(self, v):
    #    if v < 0:
    #        return math.ceil(v)
    #    else:
    #        return math.floor(v)

    @complex_unary_op
    def exp(self, v):
        if rfloat.isinf(v[1]):
            if rfloat.isinf(v[0]):
                if v[0] < 0:
                    return 0., 0.
                return rfloat.INFINITY, rfloat.NAN
            elif (isfinite(v[0]) or \
                                 (rfloat.isinf(v[0]) and v[0] > 0)):
                return rfloat.NAN, rfloat.NAN
        try:
            return rcomplex.c_exp(*v)
        except OverflowError:
            if v[1] == 0:
                return rfloat.INFINITY, 0.0
            return rfloat.INFINITY, rfloat.NAN

    @complex_unary_op
    def exp2(self, v):
        try:
            return rcomplex.c_pow((2,0), v)
        except OverflowError:
            return rfloat.INFINITY, rfloat.NAN
        except ValueError:
            return rfloat.NAN, rfloat.NAN

    @complex_unary_op
    def expm1(self, v):
        # duplicate exp() so in the future it will be easier
        # to implement seterr
        if rfloat.isinf(v[1]):
            if rfloat.isinf(v[0]):
                if v[0] < 0:
                    return -1., 0.
                return rfloat.NAN, rfloat.NAN
            elif (isfinite(v[0]) or \
                                 (rfloat.isinf(v[0]) and v[0] > 0)):
                return rfloat.NAN, rfloat.NAN
        try:
            res = rcomplex.c_exp(*v)
            res = (res[0]-1, res[1])
            return res
        except OverflowError:
            if v[1] == 0:
                return rfloat.INFINITY, 0.0
            return rfloat.INFINITY, rfloat.NAN

    @complex_unary_op
    def sin(self, v):
        if rfloat.isinf(v[0]):
            if v[1] == 0.:
                return rfloat.NAN, 0.
            if isfinite(v[1]):
                return rfloat.NAN, rfloat.NAN
            elif not rfloat.isnan(v[1]):
                return rfloat.NAN, rfloat.INFINITY
        return rcomplex.c_sin(*v)

    @complex_unary_op
    def cos(self, v):
        if rfloat.isinf(v[0]):
            if v[1] == 0.:
                return rfloat.NAN, 0.0
            if isfinite(v[1]):
                return rfloat.NAN, rfloat.NAN
            elif not rfloat.isnan(v[1]):
                return rfloat.INFINITY, rfloat.NAN
        return rcomplex.c_cos(*v)

    @complex_unary_op
    def tan(self, v):
        if rfloat.isinf(v[0]) and isfinite(v[1]):
            return rfloat.NAN, rfloat.NAN
        return rcomplex.c_tan(*v)

    @complex_unary_op
    def arcsin(self, v):
        return rcomplex.c_asin(*v)

    @complex_unary_op
    def arccos(self, v):
        return rcomplex.c_acos(*v)

    @complex_unary_op
    def arctan(self, v):
        if v[0] == 0 and (v[1] == 1 or v[1] == -1):
            #This is the place to print a "runtime warning"
            return rfloat.NAN, math.copysign(rfloat.INFINITY, v[1])
        return rcomplex.c_atan(*v)

    #@complex_binary_op
    #def arctan2(self, v1, v2):
    #    return rcomplex.c_atan2(v1, v2)

    @complex_unary_op
    def sinh(self, v):
        if rfloat.isinf(v[1]):
            if isfinite(v[0]):
                if v[0] == 0.0:
                    return 0.0, rfloat.NAN
                return rfloat.NAN, rfloat.NAN
            elif not rfloat.isnan(v[0]):
                return rfloat.INFINITY, rfloat.NAN
        return rcomplex.c_sinh(*v)

    @complex_unary_op
    def cosh(self, v):
        if rfloat.isinf(v[1]):
            if isfinite(v[0]):
                if v[0] == 0.0:
                    return rfloat.NAN, 0.0
                return rfloat.NAN, rfloat.NAN
            elif not rfloat.isnan(v[0]):
                return rfloat.INFINITY, rfloat.NAN
        return rcomplex.c_cosh(*v)

    @complex_unary_op
    def tanh(self, v):
        if rfloat.isinf(v[1]) and isfinite(v[0]):
            return rfloat.NAN, rfloat.NAN
        return rcomplex.c_tanh(*v)

    @complex_unary_op
    def arcsinh(self, v):
        return rcomplex.c_asinh(*v)

    @complex_unary_op
    def arccosh(self, v):
        return rcomplex.c_acosh(*v)

    @complex_unary_op
    def arctanh(self, v):
        if v[1] == 0 and (v[0] == 1.0 or v[0] == -1.0):
            return (math.copysign(rfloat.INFINITY, v[0]),
                   math.copysign(0., v[1]))
        return rcomplex.c_atanh(*v)

    @complex_unary_op
    def sqrt(self, v):
        return rcomplex.c_sqrt(*v)

    @complex_unary_op
    def square(self, v):
        return rcomplex.c_mul(v,v)

    @raw_unary_op
    def isfinite(self, v):
        return isfinite(v[0]) and isfinite(v[1])

    #@simple_unary_op
    #def radians(self, v):
    #    return v * degToRad
    #deg2rad = radians

    #@simple_unary_op
    #def degrees(self, v):
    #    return v / degToRad

    @complex_unary_op
    def log(self, v):
        if v[0] == 0 and v[1] == 0:
            return -rfloat.INFINITY, 0
        return rcomplex.c_log(*v)

    @complex_unary_op
    def log2(self, v):
        if v[0] == 0 and v[1] == 0:
            return -rfloat.INFINITY, 0
        r = rcomplex.c_log(*v)
        return r[0] / log2, r[1] / log2

    @complex_unary_op
    def log10(self, v):
        if v[0] == 0 and v[1] == 0:
            return -rfloat.INFINITY, 0
        return rcomplex.c_log10(*v)

    @complex_unary_op
    def log1p(self, v):
        try:
            return rcomplex.c_log(v[0] + 1, v[1])
        except OverflowError:
            return -rfloat.INFINITY, 0
        except ValueError:
            return rfloat.NAN, rfloat.NAN

class Complex64(ComplexFloating, BaseType):
    _attrs_ = ()

    T = rffi.CHAR
    _COMPONENTS_T = rffi.FLOAT
    BoxType = interp_boxes.W_Complex64Box
    ComponentBoxType = interp_boxes.W_Float32Box


NonNativeComplex64 = Complex64

class Complex128(ComplexFloating, BaseType):
    _attrs_ = ()

    T = rffi.CHAR
    _COMPONENTS_T = rffi.DOUBLE
    BoxType = interp_boxes.W_Complex128Box
    ComponentBoxType = interp_boxes.W_Float64Box


NonNativeComplex128 = Complex128

if interp_boxes.long_double_size == 12:
    class Float96(BaseType, Float):
        _attrs_ = ()

        T = rffi.LONGDOUBLE
        BoxType = interp_boxes.W_Float96Box
        format_code = "q"

        def runpack_str(self, s):
            assert len(s) == 12
            fval = unpack_float128(s, native_is_bigendian)
            return self.box(fval)

    class NonNativeFloat96(Float96):
        pass

    class Complex192(ComplexFloating, BaseType):
        _attrs_ = ()

        T = rffi.CHAR
        _COMPONENTS_T = rffi.LONGDOUBLE
        BoxType = interp_boxes.W_Complex192Box
        ComponentBoxType = interp_boxes.W_Float96Box

    NonNativeComplex192 = Complex192


elif interp_boxes.long_double_size == 16:
    class Float128(BaseType, Float):
        _attrs_ = ()

        T = rffi.LONGDOUBLE
        BoxType = interp_boxes.W_Float128Box
        format_code = "q"

        def runpack_str(self, s):
            assert len(s) == 16
            fval = unpack_float128(s, native_is_bigendian)
            return self.box(fval)

    class NonNativeFloat128(Float128):
        pass

    class Complex256(ComplexFloating, BaseType):
        _attrs_ = ()

        T = rffi.CHAR
        _COMPONENTS_T = rffi.LONGDOUBLE
        BoxType = interp_boxes.W_Complex256Box
        ComponentBoxType = interp_boxes.W_Float128Box


    NonNativeComplex256 = Complex256

class BaseStringType(object):
    _mixin_ = True

    def __init__(self, size=0):
        self.size = size

    def get_element_size(self):
        return self.size * rffi.sizeof(self.T)

    def get_size(self):
        return self.size

class StringType(BaseType, BaseStringType):
    T = lltype.Char

    @jit.unroll_safe
    def coerce(self, space, dtype, w_item):
        from pypy.module.micronumpy.interp_dtype import new_string_dtype
        arg = space.str_w(space.str(w_item))
        arr = interp_boxes.VoidBoxStorage(len(arg), new_string_dtype(space, len(arg)))
        for i in range(len(arg)):
            arr.storage[i] = arg[i]
        return interp_boxes.W_StringBox(arr,  0, None)

    @jit.unroll_safe
    def store(self, arr, i, offset, box):
        assert isinstance(box, interp_boxes.W_StringBox)
        for k in range(min(self.size, box.arr.size-offset)):
            arr.storage[k + i] = box.arr.storage[k + offset]

    def read(self, arr, i, offset, dtype=None):
        if dtype is None:
            dtype = arr.dtype
        return interp_boxes.W_StringBox(arr, i + offset, dtype)

    @jit.unroll_safe
    def to_str(self, item):
        builder = StringBuilder()
        assert isinstance(item, interp_boxes.W_StringBox)
        i = item.ofs
        end = i+self.size
        while i < end:
            assert isinstance(item.arr.storage[i], str)
            if item.arr.storage[i] == '\x00':
                break
            builder.append(item.arr.storage[i])
            i += 1
        return builder.build()

    def str_format(self, item):
        builder = StringBuilder()
        builder.append("'")
        builder.append(self.to_str(item))
        builder.append("'")
        return builder.build()

class VoidType(BaseType, BaseStringType):
    T = lltype.Char

NonNativeVoidType = VoidType
NonNativeStringType = StringType

class UnicodeType(BaseType, BaseStringType):
    T = lltype.UniChar

NonNativeUnicodeType = UnicodeType

class RecordType(BaseType):

    T = lltype.Char

    def __init__(self, offsets_and_fields, size):
        self.offsets_and_fields = offsets_and_fields
        self.size = size

    def get_element_size(self):
        return self.size

    def read(self, arr, i, offset, dtype=None):
        if dtype is None:
            dtype = arr.dtype
        return interp_boxes.W_VoidBox(arr, i + offset, dtype)

    @jit.unroll_safe
    def coerce(self, space, dtype, w_item):
        if isinstance(w_item, interp_boxes.W_VoidBox):
            return w_item
        # we treat every sequence as sequence, no special support
        # for arrays
        if not space.issequence_w(w_item):
            raise OperationError(space.w_TypeError, space.wrap(
                "expected sequence"))
        if len(self.offsets_and_fields) != space.int_w(space.len(w_item)):
            raise OperationError(space.w_ValueError, space.wrap(
                "wrong length"))
        items_w = space.fixedview(w_item)
        arr = VoidBoxStorage(self.size, dtype)
        for i in range(len(items_w)):
            subdtype = dtype.fields[dtype.fieldnames[i]][1]
            ofs, itemtype = self.offsets_and_fields[i]
            w_item = items_w[i]
            w_box = itemtype.coerce(space, subdtype, w_item)
            itemtype.store(arr, 0, ofs, w_box)
        return interp_boxes.W_VoidBox(arr, 0, dtype)

    @jit.unroll_safe
    def store(self, arr, i, ofs, box):
        assert isinstance(box, interp_boxes.W_VoidBox)
        for k in range(self.get_element_size()):
            arr.storage[k + i] = box.arr.storage[k + box.ofs]

    @jit.unroll_safe
    def str_format(self, box):
        assert isinstance(box, interp_boxes.W_VoidBox)
        pieces = ["("]
        first = True
        for ofs, tp in self.offsets_and_fields:
            if first:
                first = False
            else:
                pieces.append(", ")
            pieces.append(tp.str_format(tp.read(box.arr, box.ofs, ofs)))
        pieces.append(")")
        return "".join(pieces)

for tp in [Int32, Int64]:
    if tp.T == lltype.Signed:
        IntP = tp
        break
for tp in [UInt32, UInt64]:
    if tp.T == lltype.Unsigned:
        UIntP = tp
        break
del tp

def _setup():
    # compute alignment
    for tp in globals().values():
        if isinstance(tp, type) and hasattr(tp, 'T'):
            tp.alignment = clibffi.cast_type_to_ffitype(tp.T).c_alignment
_setup()
del _setup
