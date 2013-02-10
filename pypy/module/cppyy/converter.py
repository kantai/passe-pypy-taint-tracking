import sys

from pypy.interpreter.error import OperationError

from rpython.rtyper.lltypesystem import rffi, lltype
from rpython.rlib.rarithmetic import r_singlefloat
from rpython.rlib import jit_libffi, rfloat

from pypy.module._rawffi.interp_rawffi import unpack_simple_shape
from pypy.module._rawffi.array import W_Array

from pypy.module.cppyy import helper, capi, ffitypes

# Converter objects are used to translate between RPython and C++. They are
# defined by the type name for which they provide conversion. Uses are for
# function arguments, as well as for read and write access to data members.
# All type conversions are fully checked.
#
# Converter instances are greated by get_converter(<type name>), see below.
# The name given should be qualified in case there is a specialised, exact
# match for the qualified type.


def get_rawobject(space, w_obj):
    from pypy.module.cppyy.interp_cppyy import W_CPPInstance
    cppinstance = space.interp_w(W_CPPInstance, w_obj, can_be_None=True)
    if cppinstance:
        rawobject = cppinstance.get_rawobject()
        assert lltype.typeOf(rawobject) == capi.C_OBJECT
        return rawobject
    return capi.C_NULL_OBJECT

def set_rawobject(space, w_obj, address):
    from pypy.module.cppyy.interp_cppyy import W_CPPInstance
    cppinstance = space.interp_w(W_CPPInstance, w_obj, can_be_None=True)
    if cppinstance:
        assert lltype.typeOf(cppinstance._rawobject) == capi.C_OBJECT
        cppinstance._rawobject = rffi.cast(capi.C_OBJECT, address)

def get_rawobject_nonnull(space, w_obj):
    from pypy.module.cppyy.interp_cppyy import W_CPPInstance
    cppinstance = space.interp_w(W_CPPInstance, w_obj, can_be_None=True)
    if cppinstance:
        cppinstance._nullcheck()
        rawobject = cppinstance.get_rawobject()
        assert lltype.typeOf(rawobject) == capi.C_OBJECT
        return rawobject
    return capi.C_NULL_OBJECT

def get_rawbuffer(space, w_obj):
    try:
        buf = space.buffer_w(w_obj)
        return rffi.cast(rffi.VOIDP, buf.get_raw_address())
    except Exception:
        pass
    # special case: allow integer 0 as NULL
    try:
        buf = space.int_w(w_obj)
        if buf == 0:
            return rffi.cast(rffi.VOIDP, 0)
    except Exception:
        pass
    # special case: allow None as NULL
    if space.is_true(space.is_(w_obj, space.w_None)):
        return rffi.cast(rffi.VOIDP, 0)
    raise TypeError("not an addressable buffer")


class TypeConverter(object):
    _immutable_fields_ = ['libffitype', 'uses_local', 'name']

    libffitype = lltype.nullptr(jit_libffi.FFI_TYPE_P.TO)
    uses_local = False
    name = ""

    def __init__(self, space, extra):
        pass

    def _get_raw_address(self, space, w_obj, offset):
        rawobject = get_rawobject_nonnull(space, w_obj)
        assert lltype.typeOf(rawobject) == capi.C_OBJECT
        if rawobject:
            fieldptr = capi.direct_ptradd(rawobject, offset)
        else:
            fieldptr = rffi.cast(capi.C_OBJECT, offset)
        return fieldptr

    def _is_abstract(self, space):
        raise OperationError(space.w_TypeError, space.wrap("no converter available for '%s'" % self.name))

    def convert_argument(self, space, w_obj, address, call_local):
        self._is_abstract(space)

    def convert_argument_libffi(self, space, w_obj, address, call_local):
        from pypy.module.cppyy.interp_cppyy import FastCallNotPossible
        raise FastCallNotPossible

    def default_argument_libffi(self, space, address):
        from pypy.module.cppyy.interp_cppyy import FastCallNotPossible
        raise FastCallNotPossible

    def from_memory(self, space, w_obj, w_pycppclass, offset):
        self._is_abstract(space)

    def to_memory(self, space, w_obj, w_value, offset):
        self._is_abstract(space)

    def finalize_call(self, space, w_obj, call_local):
        pass

    def free_argument(self, space, arg, call_local):
        pass


class ArrayCache(object):
    def __init__(self, space):
        self.space = space
    def __getattr__(self, name):
        if name.startswith('array_'):
            typecode = name[len('array_'):]
            arr = self.space.interp_w(W_Array, unpack_simple_shape(self.space, self.space.wrap(typecode)))
            setattr(self, name, arr)
            return arr
        raise AttributeError(name)

    def _freeze_(self):
        return True

class ArrayTypeConverterMixin(object):
    _mixin_ = True
    _immutable_fields_ = ['libffitype', 'size']

    libffitype = jit_libffi.types.pointer

    def __init__(self, space, array_size):
        if array_size <= 0:
            self.size = sys.maxint
        else:
            self.size = array_size

    def from_memory(self, space, w_obj, w_pycppclass, offset):
        if hasattr(space, "fake"):
            raise NotImplementedError
        # read access, so no copy needed
        address_value = self._get_raw_address(space, w_obj, offset)
        address = rffi.cast(rffi.ULONG, address_value)
        cache = space.fromcache(ArrayCache)
        arr = getattr(cache, 'array_' + self.typecode)
        return arr.fromaddress(space, address, self.size)

    def to_memory(self, space, w_obj, w_value, offset):
        # copy the full array (uses byte copy for now)
        address = rffi.cast(rffi.CCHARP, self._get_raw_address(space, w_obj, offset))
        buf = space.buffer_w(w_value)
        # TODO: report if too many items given?
        for i in range(min(self.size*self.typesize, buf.getlength())):
            address[i] = buf.getitem(i)


class PtrTypeConverterMixin(object):
    _mixin_ = True
    _immutable_fields_ = ['libffitype', 'size']

    libffitype = jit_libffi.types.pointer

    def __init__(self, space, array_size):
        self.size = sys.maxint

    def convert_argument(self, space, w_obj, address, call_local):
        w_tc = space.findattr(w_obj, space.wrap('typecode'))
        if w_tc is not None and space.str_w(w_tc) != self.typecode:
            msg = "expected %s pointer type, but received %s" % (self.typecode, space.str_w(w_tc))
            raise OperationError(space.w_TypeError, space.wrap(msg))
        x = rffi.cast(rffi.VOIDPP, address)
        try:
            x[0] = rffi.cast(rffi.VOIDP, get_rawbuffer(space, w_obj))
        except TypeError:
            raise OperationError(space.w_TypeError,
                                 space.wrap("raw buffer interface not supported"))
        ba = rffi.cast(rffi.CCHARP, address)
        ba[capi.c_function_arg_typeoffset()] = 'o'

    def from_memory(self, space, w_obj, w_pycppclass, offset):
        # read access, so no copy needed
        address_value = self._get_raw_address(space, w_obj, offset)
        address = rffi.cast(rffi.ULONGP, address_value)
        cache = space.fromcache(ArrayCache)
        arr = getattr(cache, 'array_' + self.typecode)
        return arr.fromaddress(space, address[0], self.size)

    def to_memory(self, space, w_obj, w_value, offset):
        # copy only the pointer value
        rawobject = get_rawobject_nonnull(space, w_obj)
        byteptr = rffi.cast(rffi.CCHARPP, capi.direct_ptradd(rawobject, offset))
        buf = space.buffer_w(w_value)
        try:
            byteptr[0] = buf.get_raw_address()
        except ValueError:
            raise OperationError(space.w_TypeError,
                                 space.wrap("raw buffer interface not supported"))


class NumericTypeConverterMixin(object):
    _mixin_ = True

    def convert_argument_libffi(self, space, w_obj, address, call_local):
        x = rffi.cast(self.c_ptrtype, address)
        x[0] = self._unwrap_object(space, w_obj)

    def default_argument_libffi(self, space, address):
        x = rffi.cast(self.c_ptrtype, address)
        x[0] = self.default

    def from_memory(self, space, w_obj, w_pycppclass, offset):
        address = self._get_raw_address(space, w_obj, offset)
        rffiptr = rffi.cast(self.c_ptrtype, address)
        return space.wrap(rffiptr[0])

    def to_memory(self, space, w_obj, w_value, offset):
        address = self._get_raw_address(space, w_obj, offset)
        rffiptr = rffi.cast(self.c_ptrtype, address)
        rffiptr[0] = self._unwrap_object(space, w_value)

class ConstRefNumericTypeConverterMixin(NumericTypeConverterMixin):
    _mixin_ = True
    _immutable_fields_ = ['uses_local']

    uses_local = True

    def convert_argument_libffi(self, space, w_obj, address, call_local):
        assert rffi.sizeof(self.c_type) <= 2*rffi.sizeof(rffi.VOIDP)  # see interp_cppyy.py
        obj = self._unwrap_object(space, w_obj)
        typed_buf = rffi.cast(self.c_ptrtype, call_local)
        typed_buf[0] = obj
        x = rffi.cast(rffi.VOIDPP, address)
        x[0] = call_local

class IntTypeConverterMixin(NumericTypeConverterMixin):
    _mixin_ = True

    def convert_argument(self, space, w_obj, address, call_local):
        x = rffi.cast(self.c_ptrtype, address)
        x[0] = self._unwrap_object(space, w_obj)

class FloatTypeConverterMixin(NumericTypeConverterMixin):
    _mixin_ = True

    def convert_argument(self, space, w_obj, address, call_local):
        x = rffi.cast(self.c_ptrtype, address)
        x[0] = self._unwrap_object(space, w_obj)
        ba = rffi.cast(rffi.CCHARP, address)
        ba[capi.c_function_arg_typeoffset()] = self.typecode


class VoidConverter(TypeConverter):
    _immutable_fields_ = ['libffitype', 'name']

    libffitype = jit_libffi.types.void

    def __init__(self, space, name):
        self.name = name

    def convert_argument(self, space, w_obj, address, call_local):
        raise OperationError(space.w_TypeError,
                             space.wrap('no converter available for type "%s"' % self.name))


class BoolConverter(ffitypes.typeid(bool), TypeConverter):
    def convert_argument(self, space, w_obj, address, call_local):
        x = rffi.cast(rffi.LONGP, address)
        x[0] = self._unwrap_object(space, w_obj)

    def convert_argument_libffi(self, space, w_obj, address, call_local):
        x = rffi.cast(rffi.LONGP, address)
        x[0] = self._unwrap_object(space, w_obj)

    def from_memory(self, space, w_obj, w_pycppclass, offset):
        address = rffi.cast(rffi.CCHARP, self._get_raw_address(space, w_obj, offset))
        if address[0] == '\x01':
            return space.w_True
        return space.w_False

    def to_memory(self, space, w_obj, w_value, offset):
        address = rffi.cast(rffi.CCHARP, self._get_raw_address(space, w_obj, offset))
        arg = self._unwrap_object(space, w_value)
        if arg:
            address[0] = '\x01'
        else:
            address[0] = '\x00'

class CharConverter(ffitypes.typeid(rffi.CHAR), TypeConverter):
    def convert_argument(self, space, w_obj, address, call_local):
        x = rffi.cast(rffi.CCHARP, address)
        x[0] = self._unwrap_object(space, w_obj)

    def convert_argument_libffi(self, space, w_obj, address, call_local):
        x = rffi.cast(self.c_ptrtype, address)
        x[0] = self._unwrap_object(space, w_obj)

    def from_memory(self, space, w_obj, w_pycppclass, offset):
        address = rffi.cast(rffi.CCHARP, self._get_raw_address(space, w_obj, offset))
        return space.wrap(address[0])

    def to_memory(self, space, w_obj, w_value, offset):
        address = rffi.cast(rffi.CCHARP, self._get_raw_address(space, w_obj, offset))
        address[0] = self._unwrap_object(space, w_value)

class FloatConverter(ffitypes.typeid(rffi.FLOAT), FloatTypeConverterMixin, TypeConverter):
    _immutable_fields_ = ['default']

    def __init__(self, space, default):
        if default:
            fval = float(rfloat.rstring_to_float(default))
        else:
            fval = float(0.)
        self.default = r_singlefloat(fval)

    def from_memory(self, space, w_obj, w_pycppclass, offset):
        address = self._get_raw_address(space, w_obj, offset)
        rffiptr = rffi.cast(self.c_ptrtype, address)
        return space.wrap(float(rffiptr[0]))

class ConstFloatRefConverter(FloatConverter):
    _immutable_fields_ = ['libffitype', 'typecode']

    libffitype = jit_libffi.types.pointer
    typecode = 'F'

    def convert_argument_libffi(self, space, w_obj, address, call_local):
        from pypy.module.cppyy.interp_cppyy import FastCallNotPossible
        raise FastCallNotPossible

class DoubleConverter(ffitypes.typeid(rffi.DOUBLE), FloatTypeConverterMixin, TypeConverter):
    _immutable_fields_ = ['default']

    def __init__(self, space, default):
        if default:
            self.default = rffi.cast(self.c_type, rfloat.rstring_to_float(default))
        else:
            self.default = rffi.cast(self.c_type, 0.)

class ConstDoubleRefConverter(ConstRefNumericTypeConverterMixin, DoubleConverter):
    _immutable_fields_ = ['libffitype', 'typecode']

    libffitype = jit_libffi.types.pointer
    typecode = 'D'


class CStringConverter(TypeConverter):
    def convert_argument(self, space, w_obj, address, call_local):
        x = rffi.cast(rffi.LONGP, address)
        arg = space.str_w(w_obj)
        x[0] = rffi.cast(rffi.LONG, rffi.str2charp(arg))
        ba = rffi.cast(rffi.CCHARP, address)
        ba[capi.c_function_arg_typeoffset()] = 'o'

    def from_memory(self, space, w_obj, w_pycppclass, offset):
        address = self._get_raw_address(space, w_obj, offset)
        charpptr = rffi.cast(rffi.CCHARPP, address)
        return space.wrap(rffi.charp2str(charpptr[0]))

    def free_argument(self, space, arg, call_local):
        lltype.free(rffi.cast(rffi.CCHARPP, arg)[0], flavor='raw')


class VoidPtrConverter(TypeConverter):
    _immutable_fields_ = ['libffitype']

    libffitype = jit_libffi.types.pointer

    def _unwrap_object(self, space, w_obj):
        try:
            obj = get_rawbuffer(space, w_obj)
        except TypeError:
            obj = rffi.cast(rffi.VOIDP, get_rawobject(space, w_obj))
        return obj

    def convert_argument(self, space, w_obj, address, call_local):
        x = rffi.cast(rffi.VOIDPP, address)
        x[0] = self._unwrap_object(space, w_obj)
        ba = rffi.cast(rffi.CCHARP, address)
        ba[capi.c_function_arg_typeoffset()] = 'o'

    def convert_argument_libffi(self, space, w_obj, address, call_local):
        x = rffi.cast(rffi.VOIDPP, address)
        x[0] = self._unwrap_object(space, w_obj)

class VoidPtrPtrConverter(TypeConverter):
    _immutable_fields_ = ['uses_local']

    uses_local = True

    def convert_argument(self, space, w_obj, address, call_local):
        x = rffi.cast(rffi.VOIDPP, address)
        ba = rffi.cast(rffi.CCHARP, address)
        r = rffi.cast(rffi.VOIDPP, call_local)
        try:
            r[0] = get_rawbuffer(space, w_obj)
        except TypeError:
            r[0] = rffi.cast(rffi.VOIDP, get_rawobject(space, w_obj))
        x[0] = rffi.cast(rffi.VOIDP, call_local)
        ba[capi.c_function_arg_typeoffset()] = 'a'

    def finalize_call(self, space, w_obj, call_local):
        r = rffi.cast(rffi.VOIDPP, call_local)
        try:
            set_rawobject(space, w_obj, r[0])
        except OperationError:
            pass             # no set on buffer/array/None

class VoidPtrRefConverter(VoidPtrPtrConverter):
    _immutable_fields_ = ['uses_local']
    uses_local = True

class InstancePtrConverter(TypeConverter):
    _immutable_fields_ = ['libffitype', 'cppclass']

    libffitype  = jit_libffi.types.pointer

    def __init__(self, space, cppclass):
        from pypy.module.cppyy.interp_cppyy import W_CPPClass
        assert isinstance(cppclass, W_CPPClass)
        self.cppclass = cppclass

    def _unwrap_object(self, space, w_obj):
        from pypy.module.cppyy.interp_cppyy import W_CPPInstance
        obj = space.interpclass_w(w_obj)
        if isinstance(obj, W_CPPInstance):
            if capi.c_is_subtype(obj.cppclass, self.cppclass):
                rawobject = obj.get_rawobject()
                offset = capi.c_base_offset(obj.cppclass, self.cppclass, rawobject, 1)
                obj_address = capi.direct_ptradd(rawobject, offset)
                return rffi.cast(capi.C_OBJECT, obj_address)
        raise OperationError(space.w_TypeError,
                             space.wrap("cannot pass %s as %s" %
                             (space.type(w_obj).getname(space, "?"), self.cppclass.name)))

    def convert_argument(self, space, w_obj, address, call_local):
        x = rffi.cast(rffi.VOIDPP, address)
        x[0] = rffi.cast(rffi.VOIDP, self._unwrap_object(space, w_obj))
        address = rffi.cast(capi.C_OBJECT, address)
        ba = rffi.cast(rffi.CCHARP, address)
        ba[capi.c_function_arg_typeoffset()] = 'o'

    def convert_argument_libffi(self, space, w_obj, address, call_local):
        x = rffi.cast(rffi.VOIDPP, address)
        x[0] = rffi.cast(rffi.VOIDP, self._unwrap_object(space, w_obj))

    def from_memory(self, space, w_obj, w_pycppclass, offset):
        address = rffi.cast(capi.C_OBJECT, self._get_raw_address(space, w_obj, offset))
        from pypy.module.cppyy import interp_cppyy
        return interp_cppyy.wrap_cppobject_nocast(
            space, w_pycppclass, self.cppclass, address, isref=True, python_owns=False)

    def to_memory(self, space, w_obj, w_value, offset):
        address = rffi.cast(rffi.VOIDPP, self._get_raw_address(space, w_obj, offset))
        address[0] = rffi.cast(rffi.VOIDP, self._unwrap_object(space, w_value))

class InstanceConverter(InstancePtrConverter):

    def convert_argument_libffi(self, space, w_obj, address, call_local):
        from pypy.module.cppyy.interp_cppyy import FastCallNotPossible
        raise FastCallNotPossible       # TODO: by-value is a jit_libffi special case

    def from_memory(self, space, w_obj, w_pycppclass, offset):
        address = rffi.cast(capi.C_OBJECT, self._get_raw_address(space, w_obj, offset))
        from pypy.module.cppyy import interp_cppyy
        return interp_cppyy.wrap_cppobject_nocast(
            space, w_pycppclass, self.cppclass, address, isref=False, python_owns=False)

    def to_memory(self, space, w_obj, w_value, offset):
        self._is_abstract(space)

class InstancePtrPtrConverter(InstancePtrConverter):
    _immutable_fields_ = ['uses_local']

    uses_local = True

    def convert_argument(self, space, w_obj, address, call_local):
        r = rffi.cast(rffi.VOIDPP, call_local)
        r[0] = rffi.cast(rffi.VOIDP, self._unwrap_object(space, w_obj))
        x = rffi.cast(rffi.VOIDPP, address)
        x[0] = rffi.cast(rffi.VOIDP, call_local)
        address = rffi.cast(capi.C_OBJECT, address)
        ba = rffi.cast(rffi.CCHARP, address)
        ba[capi.c_function_arg_typeoffset()] = 'o'

    def convert_argument_libffi(self, space, w_obj, address, call_local):
        # TODO: finalize_call not yet called for fast call (see interp_cppyy.py)
        from pypy.module.cppyy.interp_cppyy import FastCallNotPossible
        raise FastCallNotPossible

    def from_memory(self, space, w_obj, w_pycppclass, offset):
        self._is_abstract(space)

    def to_memory(self, space, w_obj, w_value, offset):
        self._is_abstract(space)

    def finalize_call(self, space, w_obj, call_local):
        from pypy.module.cppyy.interp_cppyy import W_CPPInstance
        obj = space.interpclass_w(w_obj)
        assert isinstance(obj, W_CPPInstance)
        r = rffi.cast(rffi.VOIDPP, call_local)
        obj._rawobject = rffi.cast(capi.C_OBJECT, r[0])


class StdStringConverter(InstanceConverter):
    _immutable_fields_ = ['cppclass']

    def __init__(self, space, extra):
        from pypy.module.cppyy import interp_cppyy
        cppclass = interp_cppyy.scope_byname(space, "std::string")
        InstanceConverter.__init__(self, space, cppclass)

    def _unwrap_object(self, space, w_obj):
        try:
            charp = rffi.str2charp(space.str_w(w_obj))
            arg = capi.c_charp2stdstring(charp)
            rffi.free_charp(charp)
            return arg
        except OperationError:
            arg = InstanceConverter._unwrap_object(self, space, w_obj)
            return capi.c_stdstring2stdstring(arg)

    def to_memory(self, space, w_obj, w_value, offset):
        try:
            address = rffi.cast(capi.C_OBJECT, self._get_raw_address(space, w_obj, offset))
            charp = rffi.str2charp(space.str_w(w_value))
            capi.c_assign2stdstring(address, charp)
            rffi.free_charp(charp)
            return
        except Exception:
            pass
        return InstanceConverter.to_memory(self, space, w_obj, w_value, offset)

    def free_argument(self, space, arg, call_local):
        capi.c_free_stdstring(rffi.cast(capi.C_OBJECT, rffi.cast(rffi.VOIDPP, arg)[0]))

class StdStringRefConverter(InstancePtrConverter):
    _immutable_fields_ = ['cppclass']

    def __init__(self, space, extra):
        from pypy.module.cppyy import interp_cppyy
        cppclass = interp_cppyy.scope_byname(space, "std::string")
        InstancePtrConverter.__init__(self, space, cppclass)


class PyObjectConverter(TypeConverter):
    _immutable_fields_ = ['libffitype']

    libffitype = jit_libffi.types.pointer

    def convert_argument(self, space, w_obj, address, call_local):
        if hasattr(space, "fake"):
            raise NotImplementedError
        space.getbuiltinmodule("cpyext")
        from pypy.module.cpyext.pyobject import make_ref
        ref = make_ref(space, w_obj)
        x = rffi.cast(rffi.VOIDPP, address)
        x[0] = rffi.cast(rffi.VOIDP, ref)
        ba = rffi.cast(rffi.CCHARP, address)
        ba[capi.c_function_arg_typeoffset()] = 'a'

    def convert_argument_libffi(self, space, w_obj, address, call_local):
        # TODO: free_argument not yet called for fast call (see interp_cppyy.py)
        from pypy.module.cppyy.interp_cppyy import FastCallNotPossible
        raise FastCallNotPossible

        # proposed implementation:
        """if hasattr(space, "fake"):
            raise NotImplementedError
        space.getbuiltinmodule("cpyext")
        from pypy.module.cpyext.pyobject import make_ref
        ref = make_ref(space, w_obj)
        x = rffi.cast(rffi.VOIDPP, address)
        x[0] = rffi.cast(rffi.VOIDP, ref)"""

    def free_argument(self, space, arg, call_local):
        if hasattr(space, "fake"):
            raise NotImplementedError
        from pypy.module.cpyext.pyobject import Py_DecRef, PyObject
        Py_DecRef(space, rffi.cast(PyObject, rffi.cast(rffi.VOIDPP, arg)[0]))


_converters = {}         # builtin and custom types
_a_converters = {}       # array and ptr versions of above
def get_converter(space, name, default):
    # The matching of the name to a converter should follow:
    #   1) full, exact match
    #       1a) const-removed match
    #   2) match of decorated, unqualified type
    #   3) accept ref as pointer (for the stubs, const& can be
    #       by value, but that does not work for the ffi path)
    #   4) generalized cases (covers basically all user classes)
    #   5) void converter, which fails on use

    name = capi.c_resolve_name(name)

    #   1) full, exact match
    try:
        return _converters[name](space, default)
    except KeyError:
        pass

    #   1a) const-removed match
    try:
        return _converters[helper.remove_const(name)](space, default)
    except KeyError:
        pass

    #   2) match of decorated, unqualified type
    compound = helper.compound(name)
    clean_name = capi.c_resolve_name(helper.clean_type(name))
    try:
        # array_index may be negative to indicate no size or no size found
        array_size = helper.array_size(name)
        return _a_converters[clean_name+compound](space, array_size)
    except KeyError:
        pass

    #   3) TODO: accept ref as pointer

    #   4) generalized cases (covers basically all user classes)
    from pypy.module.cppyy import interp_cppyy
    cppclass = interp_cppyy.scope_byname(space, clean_name)
    if cppclass:
        # type check for the benefit of the annotator
        from pypy.module.cppyy.interp_cppyy import W_CPPClass
        cppclass = space.interp_w(W_CPPClass, cppclass, can_be_None=False)
        if compound == "*" or compound == "&":
            return InstancePtrConverter(space, cppclass)
        elif compound == "**":
            return InstancePtrPtrConverter(space, cppclass)
        elif compound == "":
            return InstanceConverter(space, cppclass)
    elif capi.c_is_enum(clean_name):
        return _converters['unsigned'](space, default)

    #   5) void converter, which fails on use
    #
    # return a void converter here, so that the class can be build even
    # when some types are unknown; this overload will simply fail on use
    return VoidConverter(space, name)


_converters["bool"]                     = BoolConverter
_converters["char"]                     = CharConverter
_converters["float"]                    = FloatConverter
_converters["const float&"]             = ConstFloatRefConverter
_converters["double"]                   = DoubleConverter
_converters["const double&"]            = ConstDoubleRefConverter
_converters["const char*"]              = CStringConverter
_converters["void*"]                    = VoidPtrConverter
_converters["void**"]                   = VoidPtrPtrConverter
_converters["void*&"]                   = VoidPtrRefConverter

# special cases (note: CINT backend requires the simple name 'string')
_converters["std::basic_string<char>"]           = StdStringConverter
_converters["const std::basic_string<char>&"]    = StdStringConverter     # TODO: shouldn't copy
_converters["std::basic_string<char>&"]          = StdStringRefConverter

_converters["PyObject*"]                         = PyObjectConverter

# add basic (builtin) converters
def _build_basic_converters():
    "NOT_RPYTHON"
    # signed types (use strtoll in setting of default in __init__)
    type_info = (
        (rffi.SHORT,      ("short", "short int")),
        (rffi.INT,        ("int",)),
    )

    # constref converters exist only b/c the stubs take constref by value, whereas
    # libffi takes them by pointer (hence it needs the fast-path in testing); note
    # that this is list is not complete, as some classes are specialized

    for c_type, names in type_info:
        class BasicConverter(ffitypes.typeid(c_type), IntTypeConverterMixin, TypeConverter):
            _immutable_ = True
            def __init__(self, space, default):
                self.default = rffi.cast(self.c_type, capi.c_strtoll(default))
        class ConstRefConverter(ConstRefNumericTypeConverterMixin, BasicConverter):
            _immutable_ = True
            libffitype = jit_libffi.types.pointer
        for name in names:
            _converters[name] = BasicConverter
            _converters["const "+name+"&"] = ConstRefConverter

    type_info = (
        (rffi.LONG,       ("long", "long int")),
        (rffi.LONGLONG,   ("long long", "long long int")),
    )

    for c_type, names in type_info:
        class BasicConverter(ffitypes.typeid(c_type), IntTypeConverterMixin, TypeConverter):
            _immutable_ = True
            def __init__(self, space, default):
                self.default = rffi.cast(self.c_type, capi.c_strtoll(default))
        class ConstRefConverter(ConstRefNumericTypeConverterMixin, BasicConverter):
            _immutable_ = True
            libffitype = jit_libffi.types.pointer
            typecode = 'r'
            def convert_argument(self, space, w_obj, address, call_local):
                x = rffi.cast(self.c_ptrtype, address)
                x[0] = self._unwrap_object(space, w_obj)
                ba = rffi.cast(rffi.CCHARP, address)
                ba[capi.c_function_arg_typeoffset()] = self.typecode
        for name in names:
            _converters[name] = BasicConverter
            _converters["const "+name+"&"] = ConstRefConverter

    # unsigned integer types (use strtoull in setting of default in __init__)
    type_info = (
        (rffi.USHORT,     ("unsigned short", "unsigned short int")),
        (rffi.UINT,       ("unsigned", "unsigned int")),
        (rffi.ULONG,      ("unsigned long", "unsigned long int")),
        (rffi.ULONGLONG,  ("unsigned long long", "unsigned long long int")),
    )

    for c_type, names in type_info:
        class BasicConverter(ffitypes.typeid(c_type), IntTypeConverterMixin, TypeConverter):
            _immutable_ = True
            def __init__(self, space, default):
                self.default = rffi.cast(self.c_type, capi.c_strtoull(default))
        class ConstRefConverter(ConstRefNumericTypeConverterMixin, BasicConverter):
            _immutable_ = True
            libffitype = jit_libffi.types.pointer
        for name in names:
            _converters[name] = BasicConverter
            _converters["const "+name+"&"] = ConstRefConverter
_build_basic_converters()

# create the array and pointer converters; all real work is in the mixins
def _build_array_converters():
    "NOT_RPYTHON"
    array_info = (
        ('b', rffi.sizeof(rffi.UCHAR),  ("bool",)),    # is debatable, but works ...
        ('h', rffi.sizeof(rffi.SHORT),  ("short int", "short")),
        ('H', rffi.sizeof(rffi.USHORT), ("unsigned short int", "unsigned short")),
        ('i', rffi.sizeof(rffi.INT),    ("int",)),
        ('I', rffi.sizeof(rffi.UINT),   ("unsigned int", "unsigned")),
        ('l', rffi.sizeof(rffi.LONG),   ("long int", "long")),
        ('L', rffi.sizeof(rffi.ULONG),  ("unsigned long int", "unsigned long")),
        ('f', rffi.sizeof(rffi.FLOAT),  ("float",)),
        ('d', rffi.sizeof(rffi.DOUBLE), ("double",)),
    )

    for tcode, tsize, names in array_info:
        class ArrayConverter(ArrayTypeConverterMixin, TypeConverter):
            typecode = tcode
            typesize = tsize
        class PtrConverter(PtrTypeConverterMixin, TypeConverter):
            typecode = tcode
            typesize = tsize
        for name in names:
            _a_converters[name+'[]'] = ArrayConverter
            _a_converters[name+'*']  = PtrConverter
_build_array_converters()

# add another set of aliased names
def _add_aliased_converters():
    "NOT_RPYTHON"
    aliases = (
        ("char",                            "unsigned char"),
        ("const char*",                     "char*"),

        ("std::basic_string<char>",         "string"),
        ("const std::basic_string<char>&",  "const string&"),
        ("std::basic_string<char>&",        "string&"),

        ("PyObject*",                       "_object*"),
    )
 
    for c_type, alias in aliases:
        _converters[alias] = _converters[c_type]
_add_aliased_converters()
