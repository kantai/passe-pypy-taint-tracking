from __future__ import with_statement
from pypy.interpreter.error import OperationError, operationerrfmt
from rpython.rtyper.lltypesystem import lltype, llmemory, rffi
from rpython.rlib.rarithmetic import r_uint, r_ulonglong, is_signed_integer_type
from rpython.rlib.unroll import unrolling_iterable
from rpython.rlib.objectmodel import keepalive_until_here, specialize
from rpython.rlib import jit
from rpython.translator.tool.cbuild import ExternalCompilationInfo

# ____________________________________________________________

_prim_signed_types = unrolling_iterable([
    (rffi.SIGNEDCHAR, rffi.SIGNEDCHARP),
    (rffi.SHORT, rffi.SHORTP),
    (rffi.INT, rffi.INTP),
    (rffi.LONG, rffi.LONGP),
    (rffi.LONGLONG, rffi.LONGLONGP)])

_prim_unsigned_types = unrolling_iterable([
    (rffi.UCHAR, rffi.UCHARP),
    (rffi.USHORT, rffi.USHORTP),
    (rffi.UINT, rffi.UINTP),
    (rffi.ULONG, rffi.ULONGP),
    (rffi.ULONGLONG, rffi.ULONGLONGP)])

_prim_float_types = unrolling_iterable([
    (rffi.FLOAT, rffi.FLOATP),
    (rffi.DOUBLE, rffi.DOUBLEP)])

def read_raw_signed_data(target, size):
    for TP, TPP in _prim_signed_types:
        if size == rffi.sizeof(TP):
            return rffi.cast(lltype.SignedLongLong, rffi.cast(TPP, target)[0])
    raise NotImplementedError("bad integer size")

def read_raw_long_data(target, size):
    for TP, TPP in _prim_signed_types:
        if size == rffi.sizeof(TP):
            assert rffi.sizeof(TP) <= rffi.sizeof(lltype.Signed)
            return rffi.cast(lltype.Signed, rffi.cast(TPP, target)[0])
    raise NotImplementedError("bad integer size")

def read_raw_unsigned_data(target, size):
    for TP, TPP in _prim_unsigned_types:
        if size == rffi.sizeof(TP):
            return rffi.cast(lltype.UnsignedLongLong, rffi.cast(TPP,target)[0])
    raise NotImplementedError("bad integer size")

def read_raw_ulong_data(target, size):
    for TP, TPP in _prim_unsigned_types:
        if size == rffi.sizeof(TP):
            assert rffi.sizeof(TP) <= rffi.sizeof(lltype.Unsigned)
            return rffi.cast(lltype.Unsigned, rffi.cast(TPP,target)[0])
    raise NotImplementedError("bad integer size")

def read_raw_float_data(target, size):
    for TP, TPP in _prim_float_types:
        if size == rffi.sizeof(TP):
            return rffi.cast(lltype.Float, rffi.cast(TPP, target)[0])
    raise NotImplementedError("bad float size")

def read_raw_longdouble_data(target):
    return rffi.cast(rffi.LONGDOUBLEP, target)[0]

@specialize.argtype(1)
def write_raw_integer_data(target, source, size):
    if is_signed_integer_type(lltype.typeOf(source)):
        for TP, TPP in _prim_signed_types:
            if size == rffi.sizeof(TP):
                rffi.cast(TPP, target)[0] = rffi.cast(TP, source)
                return
    else:
        for TP, TPP in _prim_unsigned_types:
            if size == rffi.sizeof(TP):
                rffi.cast(TPP, target)[0] = rffi.cast(TP, source)
                return
    raise NotImplementedError("bad integer size")

def write_raw_float_data(target, source, size):
    for TP, TPP in _prim_float_types:
        if size == rffi.sizeof(TP):
            rffi.cast(TPP, target)[0] = rffi.cast(TP, source)
            return
    raise NotImplementedError("bad float size")

def write_raw_longdouble_data(target, source):
    rffi.cast(rffi.LONGDOUBLEP, target)[0] = source

# ____________________________________________________________

sprintf_longdouble = rffi.llexternal(
    "sprintf", [rffi.CCHARP, rffi.CCHARP, rffi.LONGDOUBLE], lltype.Void,
    _nowrapper=True, sandboxsafe=True)

FORMAT_LONGDOUBLE = rffi.str2charp("%LE")

def longdouble2str(lvalue):
    with lltype.scoped_alloc(rffi.CCHARP.TO, 128) as p:    # big enough
        sprintf_longdouble(p, FORMAT_LONGDOUBLE, lvalue)
        return rffi.charp2str(p)

# ____________________________________________________________

def _is_a_float(space, w_ob):
    from pypy.module._cffi_backend.cdataobj import W_CData
    from pypy.module._cffi_backend.ctypeprim import W_CTypePrimitiveFloat
    ob = space.interpclass_w(w_ob)
    if isinstance(ob, W_CData):
        return isinstance(ob.ctype, W_CTypePrimitiveFloat)
    return space.isinstance_w(w_ob, space.w_float)

def as_long_long(space, w_ob):
    # (possibly) convert and cast a Python object to a long long.
    # This version accepts a Python int too, and does convertions from
    # other types of objects.  It refuses floats.
    if space.is_w(space.type(w_ob), space.w_int):   # shortcut
        return space.int_w(w_ob)
    try:
        bigint = space.bigint_w(w_ob)
    except OperationError, e:
        if not e.match(space, space.w_TypeError):
            raise
        if _is_a_float(space, w_ob):
            raise
        bigint = space.bigint_w(space.int(w_ob))
    try:
        return bigint.tolonglong()
    except OverflowError:
        raise OperationError(space.w_OverflowError, space.wrap(ovf_msg))

def as_long(space, w_ob):
    # Same as as_long_long(), but returning an int instead.
    if space.is_w(space.type(w_ob), space.w_int):   # shortcut
        return space.int_w(w_ob)
    try:
        bigint = space.bigint_w(w_ob)
    except OperationError, e:
        if not e.match(space, space.w_TypeError):
            raise
        if _is_a_float(space, w_ob):
            raise
        bigint = space.bigint_w(space.int(w_ob))
    try:
        return bigint.toint()
    except OverflowError:
        raise OperationError(space.w_OverflowError, space.wrap(ovf_msg))

def as_unsigned_long_long(space, w_ob, strict):
    # (possibly) convert and cast a Python object to an unsigned long long.
    # This accepts a Python int too, and does convertions from other types of
    # objects.  If 'strict', complains with OverflowError; if 'not strict',
    # mask the result and round floats.
    if space.is_w(space.type(w_ob), space.w_int):   # shortcut
        value = space.int_w(w_ob)
        if strict and value < 0:
            raise OperationError(space.w_OverflowError, space.wrap(neg_msg))
        return r_ulonglong(value)
    try:
        bigint = space.bigint_w(w_ob)
    except OperationError, e:
        if not e.match(space, space.w_TypeError):
            raise
        if strict and _is_a_float(space, w_ob):
            raise
        bigint = space.bigint_w(space.int(w_ob))
    if strict:
        try:
            return bigint.toulonglong()
        except ValueError:
            raise OperationError(space.w_OverflowError, space.wrap(neg_msg))
        except OverflowError:
            raise OperationError(space.w_OverflowError, space.wrap(ovf_msg))
    else:
        return bigint.ulonglongmask()

def as_unsigned_long(space, w_ob, strict):
    # same as as_unsigned_long_long(), but returning just an Unsigned
    if space.is_w(space.type(w_ob), space.w_int):   # shortcut
        value = space.int_w(w_ob)
        if strict and value < 0:
            raise OperationError(space.w_OverflowError, space.wrap(neg_msg))
        return r_uint(value)
    try:
        bigint = space.bigint_w(w_ob)
    except OperationError, e:
        if not e.match(space, space.w_TypeError):
            raise
        if strict and _is_a_float(space, w_ob):
            raise
        bigint = space.bigint_w(space.int(w_ob))
    if strict:
        try:
            return bigint.touint()
        except ValueError:
            raise OperationError(space.w_OverflowError, space.wrap(neg_msg))
        except OverflowError:
            raise OperationError(space.w_OverflowError, space.wrap(ovf_msg))
    else:
        return bigint.uintmask()

neg_msg = "can't convert negative number to unsigned"
ovf_msg = "long too big to convert"

# ____________________________________________________________

class _NotStandardObject(Exception):
    pass

def _standard_object_as_bool(space, w_ob):
    if space.isinstance_w(w_ob, space.w_int):
        return space.int_w(w_ob) != 0
    if space.isinstance_w(w_ob, space.w_long):
        return space.bigint_w(w_ob).tobool()
    if space.isinstance_w(w_ob, space.w_float):
        return space.float_w(w_ob) != 0.0
    raise _NotStandardObject

# hackish, but the most straightforward way to know if a LONGDOUBLE object
# contains the value 0 or not.
eci = ExternalCompilationInfo(post_include_bits=["""
#define pypy__is_nonnull_longdouble(x)  ((x) != 0.0)
"""])
is_nonnull_longdouble = rffi.llexternal(
    "pypy__is_nonnull_longdouble", [rffi.LONGDOUBLE], lltype.Bool,
    compilation_info=eci, _nowrapper=True, elidable_function=True,
    sandboxsafe=True)

def object_as_bool(space, w_ob):
    # convert and cast a Python object to a boolean.  Accept an integer
    # or a float object, up to a CData 'long double'.
    try:
        return _standard_object_as_bool(space, w_ob)
    except _NotStandardObject:
        pass
    #
    from pypy.module._cffi_backend.cdataobj import W_CData
    from pypy.module._cffi_backend.ctypeprim import W_CTypePrimitiveFloat
    from pypy.module._cffi_backend.ctypeprim import W_CTypePrimitiveLongDouble
    ob = space.interpclass_w(w_ob)
    is_cdata = isinstance(ob, W_CData)
    if is_cdata and isinstance(ob.ctype, W_CTypePrimitiveFloat):
        if isinstance(ob.ctype, W_CTypePrimitiveLongDouble):
            result = is_nonnull_longdouble(read_raw_longdouble_data(ob._cdata))
        else:
            result = read_raw_float_data(ob._cdata, ob.ctype.size) != 0.0
        keepalive_until_here(ob)
        return result
    #
    if not is_cdata and space.lookup(w_ob, '__float__') is not None:
        w_io = space.float(w_ob)
    else:
        w_io = space.int(w_ob)
    try:
        return _standard_object_as_bool(space, w_io)
    except _NotStandardObject:
        raise OperationError(space.w_TypeError,
                             space.wrap("integer/float expected"))

# ____________________________________________________________

def _raw_memcopy(source, dest, size):
    if jit.isconstant(size):
        # for the JIT: first handle the case where 'size' is known to be
        # a constant equal to 1, 2, 4, 8
        for TP, TPP in _prim_unsigned_types:
            if size == rffi.sizeof(TP):
                rffi.cast(TPP, dest)[0] = rffi.cast(TPP, source)[0]
                return
    _raw_memcopy_opaque(source, dest, size)

@jit.dont_look_inside
def _raw_memcopy_opaque(source, dest, size):
    # push push push at the llmemory interface (with hacks that are all
    # removed after translation)
    zero = llmemory.itemoffsetof(rffi.CCHARP.TO, 0)
    llmemory.raw_memcopy(
        llmemory.cast_ptr_to_adr(source) + zero,
        llmemory.cast_ptr_to_adr(dest) + zero,
        size * llmemory.sizeof(lltype.Char))

def _raw_memclear(dest, size):
    # for now, only supports the cases of size = 1, 2, 4, 8
    for TP, TPP in _prim_unsigned_types:
        if size == rffi.sizeof(TP):
            rffi.cast(TPP, dest)[0] = rffi.cast(TP, 0)
            return
    raise NotImplementedError("bad clear size")
