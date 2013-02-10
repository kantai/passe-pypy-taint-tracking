from rpython.rtyper.lltypesystem import rffi, lltype
from rpython.rlib import jit

import reflex_capi as backend
#import cint_capi as backend

identify  = backend.identify
pythonize = backend.pythonize
register_pythonizations = backend.register_pythonizations

ts_reflect = backend.ts_reflect
ts_call    = backend.ts_call
ts_memory  = backend.ts_memory
ts_helper  = backend.ts_helper

_C_OPAQUE_PTR = rffi.LONG
_C_OPAQUE_NULL = lltype.nullptr(rffi.LONGP.TO)# ALT: _C_OPAQUE_PTR.TO

C_SCOPE = _C_OPAQUE_PTR
C_NULL_SCOPE = rffi.cast(C_SCOPE, _C_OPAQUE_NULL)

C_TYPE = C_SCOPE
C_NULL_TYPE = C_NULL_SCOPE

C_OBJECT = _C_OPAQUE_PTR
C_NULL_OBJECT = rffi.cast(C_OBJECT, _C_OPAQUE_NULL)

C_METHOD = _C_OPAQUE_PTR
C_INDEX = rffi.LONG
C_INDEX_ARRAY = rffi.LONGP
WLAVC_INDEX = rffi.LONG

C_METHPTRGETTER = lltype.FuncType([C_OBJECT], rffi.VOIDP)
C_METHPTRGETTER_PTR = lltype.Ptr(C_METHPTRGETTER)

def direct_ptradd(ptr, offset):
    offset = rffi.cast(rffi.SIZE_T, offset)
    jit.promote(offset)
    assert lltype.typeOf(ptr) == C_OBJECT
    address = rffi.cast(rffi.CCHARP, ptr)
    return rffi.cast(C_OBJECT, lltype.direct_ptradd(address, offset))

def exchange_address(ptr, cif_descr, index):
    return rffi.ptradd(ptr, cif_descr.exchange_args[index])

c_load_dictionary = backend.c_load_dictionary

# name to opaque C++ scope representation ------------------------------------
_c_num_scopes = rffi.llexternal(
    "cppyy_num_scopes",
    [C_SCOPE], rffi.INT,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_num_scopes(cppscope):
    return _c_num_scopes(cppscope.handle)
_c_scope_name = rffi.llexternal(
    "cppyy_scope_name",
    [C_SCOPE, rffi.INT], rffi.CCHARP,
    compilation_info = backend.eci)
def c_scope_name(cppscope, iscope):
    return charp2str_free(_c_scope_name(cppscope.handle, iscope))

_c_resolve_name = rffi.llexternal(
    "cppyy_resolve_name",
    [rffi.CCHARP], rffi.CCHARP,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_resolve_name(name):
    return charp2str_free(_c_resolve_name(name))
c_get_scope_opaque = rffi.llexternal(
    "cppyy_get_scope",
    [rffi.CCHARP], C_SCOPE,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
c_get_template = rffi.llexternal(
    "cppyy_get_template",
    [rffi.CCHARP], C_TYPE,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
_c_actual_class = rffi.llexternal(
    "cppyy_actual_class",
    [C_TYPE, C_OBJECT], C_TYPE,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_actual_class(cppclass, cppobj):
    return _c_actual_class(cppclass.handle, cppobj)

# memory management ----------------------------------------------------------
_c_allocate = rffi.llexternal(
    "cppyy_allocate",
    [C_TYPE], C_OBJECT,
    threadsafe=ts_memory,
    compilation_info=backend.eci)
def c_allocate(cppclass):
    return _c_allocate(cppclass.handle)
_c_deallocate = rffi.llexternal(
    "cppyy_deallocate",
    [C_TYPE, C_OBJECT], lltype.Void,
    threadsafe=ts_memory,
    compilation_info=backend.eci)
def c_deallocate(cppclass, cppobject):
    _c_deallocate(cppclass.handle, cppobject)
_c_destruct = rffi.llexternal(
    "cppyy_destruct",
    [C_TYPE, C_OBJECT], lltype.Void,
    threadsafe=ts_call,
    compilation_info=backend.eci)
def c_destruct(cppclass, cppobject):
    _c_destruct(cppclass.handle, cppobject)

# method/function dispatching ------------------------------------------------
c_call_v = rffi.llexternal(
    "cppyy_call_v",
    [C_METHOD, C_OBJECT, rffi.INT, rffi.VOIDP], lltype.Void,
    threadsafe=ts_call,
    compilation_info=backend.eci)
c_call_b = rffi.llexternal(
    "cppyy_call_b",
    [C_METHOD, C_OBJECT, rffi.INT, rffi.VOIDP], rffi.UCHAR,
    threadsafe=ts_call,
    compilation_info=backend.eci)
c_call_c = rffi.llexternal(
    "cppyy_call_c",
    [C_METHOD, C_OBJECT, rffi.INT, rffi.VOIDP], rffi.CHAR,
    threadsafe=ts_call,
    compilation_info=backend.eci)
c_call_h = rffi.llexternal(
    "cppyy_call_h",
    [C_METHOD, C_OBJECT, rffi.INT, rffi.VOIDP], rffi.SHORT,
    threadsafe=ts_call,
    compilation_info=backend.eci)
c_call_i = rffi.llexternal(
    "cppyy_call_i",
    [C_METHOD, C_OBJECT, rffi.INT, rffi.VOIDP], rffi.INT,
    threadsafe=ts_call,
    compilation_info=backend.eci)
c_call_l = rffi.llexternal(
    "cppyy_call_l",
    [C_METHOD, C_OBJECT, rffi.INT, rffi.VOIDP], rffi.LONG,
    threadsafe=ts_call,
    compilation_info=backend.eci)
c_call_ll = rffi.llexternal(
    "cppyy_call_ll",
    [C_METHOD, C_OBJECT, rffi.INT, rffi.VOIDP], rffi.LONGLONG,
    threadsafe=ts_call,
    compilation_info=backend.eci)
c_call_f = rffi.llexternal(
    "cppyy_call_f",
    [C_METHOD, C_OBJECT, rffi.INT, rffi.VOIDP], rffi.FLOAT,
    threadsafe=ts_call,
    compilation_info=backend.eci)
c_call_d = rffi.llexternal(
    "cppyy_call_d",
    [C_METHOD, C_OBJECT, rffi.INT, rffi.VOIDP], rffi.DOUBLE,
    threadsafe=ts_call,
    compilation_info=backend.eci)

c_call_r = rffi.llexternal(
    "cppyy_call_r",
    [C_METHOD, C_OBJECT, rffi.INT, rffi.VOIDP], rffi.VOIDP,
    threadsafe=ts_call,
    compilation_info=backend.eci)
c_call_s = rffi.llexternal(
    "cppyy_call_s",
    [C_METHOD, C_OBJECT, rffi.INT, rffi.VOIDP], rffi.CCHARP,
    threadsafe=ts_call,
    compilation_info=backend.eci)

c_constructor = rffi.llexternal(
    "cppyy_constructor",
    [C_METHOD, C_OBJECT, rffi.INT, rffi.VOIDP], lltype.Void,
    threadsafe=ts_call,
    compilation_info=backend.eci)
_c_call_o = rffi.llexternal(
    "cppyy_call_o",
    [C_METHOD, C_OBJECT, rffi.INT, rffi.VOIDP, C_TYPE], rffi.LONG,
    threadsafe=ts_call,
    compilation_info=backend.eci)
def c_call_o(method, cppobj, nargs, args, cppclass):
    return _c_call_o(method, cppobj, nargs, args, cppclass.handle)

_c_get_methptr_getter = rffi.llexternal(
    "cppyy_get_methptr_getter",
    [C_SCOPE, C_INDEX], C_METHPTRGETTER_PTR,
    threadsafe=ts_reflect,
    compilation_info=backend.eci,
    elidable_function=True)
def c_get_methptr_getter(cppscope, index):
    return _c_get_methptr_getter(cppscope.handle, index)

# handling of function argument buffer ---------------------------------------
c_allocate_function_args = rffi.llexternal(
    "cppyy_allocate_function_args",
    [rffi.SIZE_T], rffi.VOIDP,
    threadsafe=ts_memory,
    compilation_info=backend.eci)
c_deallocate_function_args = rffi.llexternal(
    "cppyy_deallocate_function_args",
    [rffi.VOIDP], lltype.Void,
    threadsafe=ts_memory,
    compilation_info=backend.eci)
c_function_arg_sizeof = rffi.llexternal(
    "cppyy_function_arg_sizeof",
    [], rffi.SIZE_T,
    threadsafe=ts_memory,
    compilation_info=backend.eci,
    elidable_function=True)
c_function_arg_typeoffset = rffi.llexternal(
    "cppyy_function_arg_typeoffset",
    [], rffi.SIZE_T,
    threadsafe=ts_memory,
    compilation_info=backend.eci,
    elidable_function=True)

# scope reflection information -----------------------------------------------
c_is_namespace = rffi.llexternal(
    "cppyy_is_namespace",
    [C_SCOPE], rffi.INT,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
c_is_enum = rffi.llexternal(
    "cppyy_is_enum",
    [rffi.CCHARP], rffi.INT,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)

# type/class reflection information ------------------------------------------
_c_final_name = rffi.llexternal(
    "cppyy_final_name",
    [C_TYPE], rffi.CCHARP,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_final_name(cpptype):
    return charp2str_free(_c_final_name(cpptype))
_c_scoped_final_name = rffi.llexternal(
    "cppyy_scoped_final_name",
    [C_TYPE], rffi.CCHARP,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_scoped_final_name(cpptype):
    return charp2str_free(_c_scoped_final_name(cpptype))
c_has_complex_hierarchy = rffi.llexternal(
    "cppyy_has_complex_hierarchy",
    [C_TYPE], rffi.INT,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
_c_num_bases = rffi.llexternal(
    "cppyy_num_bases",
    [C_TYPE], rffi.INT,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_num_bases(cppclass):
    return _c_num_bases(cppclass.handle)
_c_base_name = rffi.llexternal(
    "cppyy_base_name",
    [C_TYPE, rffi.INT], rffi.CCHARP,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_base_name(cppclass, base_index):
    return charp2str_free(_c_base_name(cppclass.handle, base_index))
_c_is_subtype = rffi.llexternal(
    "cppyy_is_subtype",
    [C_TYPE, C_TYPE], rffi.INT,
    threadsafe=ts_reflect,
    compilation_info=backend.eci,
    elidable_function=True)
@jit.elidable_promote()
def c_is_subtype(derived, base):
    if derived == base:
        return 1
    return _c_is_subtype(derived.handle, base.handle)

_c_base_offset = rffi.llexternal(
    "cppyy_base_offset",
    [C_TYPE, C_TYPE, C_OBJECT, rffi.INT], rffi.SIZE_T,
    threadsafe=ts_reflect,
    compilation_info=backend.eci,
    elidable_function=True)
@jit.elidable_promote()
def c_base_offset(derived, base, address, direction):
    if derived == base:
        return 0
    return _c_base_offset(derived.handle, base.handle, address, direction)

# method/function reflection information -------------------------------------
_c_num_methods = rffi.llexternal(
    "cppyy_num_methods",
    [C_SCOPE], rffi.INT,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_num_methods(cppscope):
    return _c_num_methods(cppscope.handle)
_c_method_index_at = rffi.llexternal(
    "cppyy_method_index_at",
    [C_SCOPE, rffi.INT], C_INDEX,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_method_index_at(cppscope, imethod):
    return _c_method_index_at(cppscope.handle, imethod)
_c_method_indices_from_name = rffi.llexternal(
    "cppyy_method_indices_from_name",
    [C_SCOPE, rffi.CCHARP], C_INDEX_ARRAY,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_method_indices_from_name(cppscope, name):
    indices = _c_method_indices_from_name(cppscope.handle, name)
    if not indices:
        return []
    py_indices = []
    i = 0
    index = indices[i]
    while index != -1:
        i += 1
        py_indices.append(index)
        index = indices[i]
    c_free(rffi.cast(rffi.VOIDP, indices))   # c_free defined below
    return py_indices

_c_method_name = rffi.llexternal(
    "cppyy_method_name",
    [C_SCOPE, C_INDEX], rffi.CCHARP,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_method_name(cppscope, index):
    return charp2str_free(_c_method_name(cppscope.handle, index))
_c_method_result_type = rffi.llexternal(
    "cppyy_method_result_type",
    [C_SCOPE, C_INDEX], rffi.CCHARP,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_method_result_type(cppscope, index):
    return charp2str_free(_c_method_result_type(cppscope.handle, index))
_c_method_num_args = rffi.llexternal(
    "cppyy_method_num_args",
    [C_SCOPE, C_INDEX], rffi.INT,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_method_num_args(cppscope, index):
    return _c_method_num_args(cppscope.handle, index)
_c_method_req_args = rffi.llexternal(
    "cppyy_method_req_args",
    [C_SCOPE, C_INDEX], rffi.INT,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_method_req_args(cppscope, index):
    return _c_method_req_args(cppscope.handle, index)
_c_method_arg_type = rffi.llexternal(
    "cppyy_method_arg_type",
    [C_SCOPE, C_INDEX, rffi.INT], rffi.CCHARP,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_method_arg_type(cppscope, index, arg_index):
    return charp2str_free(_c_method_arg_type(cppscope.handle, index, arg_index))
_c_method_arg_default = rffi.llexternal(
    "cppyy_method_arg_default",
    [C_SCOPE, C_INDEX, rffi.INT], rffi.CCHARP,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_method_arg_default(cppscope, index, arg_index):
    return charp2str_free(_c_method_arg_default(cppscope.handle, index, arg_index))
_c_method_signature = rffi.llexternal(
    "cppyy_method_signature",
    [C_SCOPE, C_INDEX], rffi.CCHARP,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_method_signature(cppscope, index):
    return charp2str_free(_c_method_signature(cppscope.handle, index))

_c_get_method = rffi.llexternal(
    "cppyy_get_method",
    [C_SCOPE, C_INDEX], C_METHOD,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_get_method(cppscope, index):
    return _c_get_method(cppscope.handle, index)
_c_get_global_operator = rffi.llexternal(
    "cppyy_get_global_operator",
    [C_SCOPE, C_SCOPE, C_SCOPE, rffi.CCHARP], WLAVC_INDEX,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_get_global_operator(nss, lc, rc, op):
    if nss is not None:
        return _c_get_global_operator(nss.handle, lc.handle, rc.handle, op)
    return rffi.cast(WLAVC_INDEX, -1)

# method properties ----------------------------------------------------------
_c_is_constructor = rffi.llexternal(
    "cppyy_is_constructor",
    [C_TYPE, C_INDEX], rffi.INT,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_is_constructor(cppclass, index):
    return _c_is_constructor(cppclass.handle, index)
_c_is_staticmethod = rffi.llexternal(
    "cppyy_is_staticmethod",
    [C_TYPE, C_INDEX], rffi.INT,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_is_staticmethod(cppclass, index):
    return _c_is_staticmethod(cppclass.handle, index)

# data member reflection information -----------------------------------------
_c_num_datamembers = rffi.llexternal(
    "cppyy_num_datamembers",
    [C_SCOPE], rffi.INT,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_num_datamembers(cppscope):
    return _c_num_datamembers(cppscope.handle)
_c_datamember_name = rffi.llexternal(
    "cppyy_datamember_name",
    [C_SCOPE, rffi.INT], rffi.CCHARP,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_datamember_name(cppscope, datamember_index):
    return charp2str_free(_c_datamember_name(cppscope.handle, datamember_index))
_c_datamember_type = rffi.llexternal(
    "cppyy_datamember_type",
    [C_SCOPE, rffi.INT], rffi.CCHARP,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_datamember_type(cppscope, datamember_index):
    return charp2str_free(_c_datamember_type(cppscope.handle, datamember_index))
_c_datamember_offset = rffi.llexternal(
    "cppyy_datamember_offset",
    [C_SCOPE, rffi.INT], rffi.SIZE_T,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_datamember_offset(cppscope, datamember_index):
    return _c_datamember_offset(cppscope.handle, datamember_index)

_c_datamember_index = rffi.llexternal(
    "cppyy_datamember_index",
    [C_SCOPE, rffi.CCHARP], rffi.INT,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_datamember_index(cppscope, name):
    return _c_datamember_index(cppscope.handle, name)

# data member properties -----------------------------------------------------
_c_is_publicdata = rffi.llexternal(
    "cppyy_is_publicdata",
    [C_SCOPE, rffi.INT], rffi.INT,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_is_publicdata(cppscope, datamember_index):
    return _c_is_publicdata(cppscope.handle, datamember_index)
_c_is_staticdata = rffi.llexternal(
    "cppyy_is_staticdata",
    [C_SCOPE, rffi.INT], rffi.INT,
    threadsafe=ts_reflect,
    compilation_info=backend.eci)
def c_is_staticdata(cppscope, datamember_index):
    return _c_is_staticdata(cppscope.handle, datamember_index)

# misc helpers ---------------------------------------------------------------
c_strtoll = rffi.llexternal(
    "cppyy_strtoll",
    [rffi.CCHARP], rffi.LONGLONG,
    threadsafe=ts_helper,
    compilation_info=backend.eci)
c_strtoull = rffi.llexternal(
    "cppyy_strtoull",
    [rffi.CCHARP], rffi.ULONGLONG,
    threadsafe=ts_helper,
    compilation_info=backend.eci)
c_free = rffi.llexternal(
    "cppyy_free",
    [rffi.VOIDP], lltype.Void,
    threadsafe=ts_memory,
    compilation_info=backend.eci)

def charp2str_free(charp):
    string = rffi.charp2str(charp)
    voidp = rffi.cast(rffi.VOIDP, charp)
    c_free(voidp)
    return string

c_charp2stdstring = rffi.llexternal(
    "cppyy_charp2stdstring",
    [rffi.CCHARP], C_OBJECT,
    threadsafe=ts_helper,
    compilation_info=backend.eci)
c_stdstring2stdstring = rffi.llexternal(
    "cppyy_stdstring2stdstring",
    [C_OBJECT], C_OBJECT,
    threadsafe=ts_helper,
    compilation_info=backend.eci)
c_assign2stdstring = rffi.llexternal(
    "cppyy_assign2stdstring",
    [C_OBJECT, rffi.CCHARP], lltype.Void,
    threadsafe=ts_helper,
    compilation_info=backend.eci)
c_free_stdstring = rffi.llexternal(
    "cppyy_free_stdstring",
    [C_OBJECT], lltype.Void,
    threadsafe=ts_helper,
    compilation_info=backend.eci)
