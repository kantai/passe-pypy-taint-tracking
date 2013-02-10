"""
Built-in functions.
"""

import sys
from rpython.annotator.model import SomeInteger, SomeObject, SomeChar, SomeBool
from rpython.annotator.model import SomeString, SomeTuple, s_Bool, SomeBuiltin
from rpython.annotator.model import SomeUnicodeCodePoint, SomeAddress
from rpython.annotator.model import SomeFloat, unionof, SomeUnicodeString
from rpython.annotator.model import SomePBC, SomeInstance, SomeDict, SomeList
from rpython.annotator.model import SomeWeakRef, SomeIterator
from rpython.annotator.model import SomeOOObject, SomeByteArray
from rpython.annotator.model import annotation_to_lltype, lltype_to_annotation, ll_to_annotation
from rpython.annotator.model import add_knowntypedata
from rpython.annotator.model import s_ImpossibleValue
from rpython.annotator.bookkeeper import getbookkeeper
from rpython.annotator import description
from rpython.flowspace.model import Constant
from rpython.tool.error import AnnotatorError
import rpython.rlib.rarithmetic
import rpython.rlib.objectmodel

# convenience only!
def immutablevalue(x):
    return getbookkeeper().immutablevalue(x)

def constpropagate(func, args_s, s_result):
    """Returns s_result unless all args are constants, in which case the
    func() is called and a constant result is returned (it must be contained
    in s_result).
    """
    args = []
    for s in args_s:
        if not s.is_immutable_constant():
            return s_result
        args.append(s.const)
    try:
        realresult = func(*args)
    except (ValueError, OverflowError):
        # no possible answer for this precise input.  Be conservative
        # and keep the computation non-constant.  Example:
        # unichr(constant-that-doesn't-fit-16-bits) on platforms where
        # the underlying Python has sys.maxunicode == 0xffff.
        return s_result
    s_realresult = immutablevalue(realresult)
    if not s_result.contains(s_realresult):
        raise Exception("%s%r returned %r, which is not contained in %s" % (
            func, args, realresult, s_result))
    return s_realresult

# ____________________________________________________________

def builtin_range(*args):
    s_step = immutablevalue(1)
    if len(args) == 1:
        s_start = immutablevalue(0)
        s_stop = args[0]
    elif len(args) == 2:
        s_start, s_stop = args
    elif len(args) == 3:
        s_start, s_stop = args[:2]
        s_step = args[2]
    else:
        raise Exception, "range() takes 1 to 3 arguments"
    empty = False  # so far
    if not s_step.is_constant():
        step = 0 # this case signals a variable step
    else:
        step = s_step.const
        if step == 0:
            raise Exception, "range() with step zero"
        if s_start.is_constant() and s_stop.is_constant():
            try:
                if len(xrange(s_start.const, s_stop.const, step)) == 0:
                    empty = True
            except TypeError:   # if one of the .const is a Symbolic
                pass
    if empty:
        s_item = s_ImpossibleValue
    else:
        nonneg = False # so far
        if step > 0 or s_step.nonneg:
            nonneg = s_start.nonneg
        elif step < 0:
            nonneg = s_stop.nonneg or (s_stop.is_constant() and
                                       s_stop.const >= -1)
        s_item = SomeInteger(nonneg=nonneg)
    return getbookkeeper().newlist(s_item, range_step=step)

builtin_xrange = builtin_range # xxx for now allow it

def builtin_enumerate(s_obj):
    return SomeIterator(s_obj, "enumerate")

def builtin_bool(s_obj):
    return s_obj.is_true()

def builtin_int(s_obj, s_base=None):
    if isinstance(s_obj, SomeInteger):
        assert not s_obj.unsigned, "instead of int(r_uint(x)), use intmask(r_uint(x))"
    assert (s_base is None or isinstance(s_base, SomeInteger)
            and s_obj.knowntype == str), "only int(v|string) or int(string,int) expected"
    if s_base is not None:
        args_s = [s_obj, s_base]
    else:
        args_s = [s_obj]
    nonneg = isinstance(s_obj, SomeInteger) and s_obj.nonneg
    return constpropagate(int, args_s, SomeInteger(nonneg=nonneg))

def builtin_float(s_obj):
    return constpropagate(float, [s_obj], SomeFloat())

def builtin_chr(s_int):
    return constpropagate(chr, [s_int], SomeChar())

def builtin_unichr(s_int):
    return constpropagate(unichr, [s_int], SomeUnicodeCodePoint())

def builtin_unicode(s_unicode):
    return constpropagate(unicode, [s_unicode], SomeUnicodeString())

def builtin_bytearray(s_str):
    return constpropagate(bytearray, [s_str], SomeByteArray())

def our_issubclass(cls1, cls2):
    """ we're going to try to be less silly in the face of old-style classes"""
    from rpython.annotator.classdef import ClassDef
    if cls2 is object:
        return True
    def classify(cls):
        if isinstance(cls, ClassDef):
            return 'def'
        if cls.__module__ == '__builtin__':
            return 'builtin'
        else:
            return 'cls'
    kind1 = classify(cls1)
    kind2 = classify(cls2)
    if kind1 != 'def' and kind2 != 'def':
        return issubclass(cls1, cls2)
    if kind1 == 'builtin' and kind2 == 'def':
        return False
    elif kind1 == 'def' and kind2 == 'builtin':
        return issubclass(object, cls2)
    else:
        bk = getbookkeeper()
        def toclassdef(kind, cls):
            if kind != 'def':
                return bk.getuniqueclassdef(cls)
            else:
                return cls
        return toclassdef(kind1, cls1).issubclass(toclassdef(kind2, cls2))


def builtin_isinstance(s_obj, s_type, variables=None):
    r = SomeBool()
    if s_type.is_constant():
        typ = s_type.const
        if issubclass(typ, rpython.rlib.rarithmetic.base_int):
            r.const = issubclass(s_obj.knowntype, typ)
        else:
            if typ == long:
                getbookkeeper().warning("isinstance(., long) is not RPython")
                r.const = False
                return r

            assert not issubclass(typ, (int, long)) or typ in (bool, int, long), (
                "for integers only isinstance(.,int|r_uint) are supported")

            if s_obj.is_constant():
                r.const = isinstance(s_obj.const, typ)
            elif our_issubclass(s_obj.knowntype, typ):
                if not s_obj.can_be_none():
                    r.const = True 
            elif not our_issubclass(typ, s_obj.knowntype): 
                r.const = False
            elif s_obj.knowntype == int and typ == bool: # xxx this will explode in case of generalisation
                                                   # from bool to int, notice that isinstance( , bool|int)
                                                   # is quite border case for RPython
                r.const = False
        # XXX HACK HACK HACK
        # XXX HACK HACK HACK
        # XXX HACK HACK HACK
        bk = getbookkeeper()
        if variables is None:
            fn, block, i = bk.position_key
            op = block.operations[i]
            assert op.opname == "simple_call" 
            assert len(op.args) == 3
            assert op.args[0] == Constant(isinstance)
            variables = [op.args[1]]
        for variable in variables:
            assert bk.annotator.binding(variable) == s_obj
        knowntypedata = {}
        if not hasattr(typ, '_freeze_') and isinstance(s_type, SomePBC):
            add_knowntypedata(knowntypedata, True, variables, bk.valueoftype(typ))
        r.set_knowntypedata(knowntypedata)
    return r

# note that this one either needs to be constant, or we will create SomeObject
def builtin_hasattr(s_obj, s_attr):
    if not s_attr.is_constant() or not isinstance(s_attr.const, str):
        getbookkeeper().warning('hasattr(%r, %r) is not RPythonic enough' %
                                (s_obj, s_attr))
    r = SomeBool()
    if s_obj.is_immutable_constant():
        r.const = hasattr(s_obj.const, s_attr.const)
    elif (isinstance(s_obj, SomePBC)
          and s_obj.getKind() is description.FrozenDesc):
       answers = {}    
       for d in s_obj.descriptions:
           answer = (d.s_read_attribute(s_attr.const) != s_ImpossibleValue)
           answers[answer] = True
       if len(answers) == 1:
           r.const, = answers
    return r

##def builtin_callable(s_obj):
##    return SomeBool()

def builtin_tuple(s_iterable):
    if isinstance(s_iterable, SomeTuple):
        return s_iterable
    return SomeObject()

def builtin_list(s_iterable):
    if isinstance(s_iterable, SomeList):
        return s_iterable.listdef.offspring()
    s_iter = s_iterable.iter()
    return getbookkeeper().newlist(s_iter.next())

def builtin_zip(s_iterable1, s_iterable2): # xxx not actually implemented
    s_iter1 = s_iterable1.iter()
    s_iter2 = s_iterable2.iter()
    s_tup = SomeTuple((s_iter1.next(),s_iter2.next()))
    return getbookkeeper().newlist(s_tup)

def builtin_min(*s_values):
    if len(s_values) == 1: # xxx do we support this?
        s_iter = s_values[0].iter()
        return s_iter.next()
    else:
        return unionof(*s_values)

def builtin_max(*s_values):
    if len(s_values) == 1: # xxx do we support this?
        s_iter = s_values[0].iter()
        return s_iter.next()
    else:
        s = unionof(*s_values)
        if type(s) is SomeInteger and not s.nonneg:
            nonneg = False
            for s1 in s_values:
                nonneg |= s1.nonneg
            if nonneg:
                s = SomeInteger(nonneg=True, knowntype=s.knowntype)
        return s


def OSError_init(s_self, *args):
    pass

def WindowsError_init(s_self, *args):
    pass

def termios_error_init(s_self, *args):
    pass

def object_init(s_self, *args):
    # ignore - mostly used for abstract classes initialization
    pass


def conf():
    return SomeString()

def rarith_intmask(s_obj):
    return SomeInteger()

def rarith_longlongmask(s_obj):
    return SomeInteger(knowntype=rpython.rlib.rarithmetic.r_longlong)

def robjmodel_instantiate(s_clspbc):
    assert isinstance(s_clspbc, SomePBC)
    clsdef = None
    more_than_one = len(s_clspbc.descriptions) > 1
    for desc in s_clspbc.descriptions:
        cdef = desc.getuniqueclassdef()
        if more_than_one:
            getbookkeeper().needs_generic_instantiate[cdef] = True
        if not clsdef:
            clsdef = cdef
        else:
            clsdef = clsdef.commonbase(cdef)
    return SomeInstance(clsdef)

def robjmodel_r_dict(s_eqfn, s_hashfn, s_force_non_null=None):
    if s_force_non_null is None:
        force_non_null = False
    else:
        assert s_force_non_null.is_constant()
        force_non_null = s_force_non_null.const
    dictdef = getbookkeeper().getdictdef(is_r_dict=True,
                                         force_non_null=force_non_null)
    dictdef.dictkey.update_rdict_annotations(s_eqfn, s_hashfn)
    return SomeDict(dictdef)


def robjmodel_hlinvoke(s_repr, s_llcallable, *args_s):
    from rpython.rtyper import rmodel
    from rpython.rtyper.error import TyperError

    assert s_repr.is_constant() and isinstance(s_repr.const, rmodel.Repr), "hlinvoke expects a constant repr as first argument"
    r_func, nimplicitarg = s_repr.const.get_r_implfunc()

    nbargs = len(args_s) + nimplicitarg
    s_sigs = r_func.get_s_signatures((nbargs, (), False, False))
    if len(s_sigs) != 1:
        raise TyperError("cannot hlinvoke callable %r with not uniform"
                         "annotations: %r" % (s_repr.const,
                                              s_sigs))
    _, s_ret = s_sigs[0]
    rresult = r_func.rtyper.getrepr(s_ret)

    return lltype_to_annotation(rresult.lowleveltype)


def robjmodel_keepalive_until_here(*args_s):
    return immutablevalue(None)

def llmemory_cast_ptr_to_adr(s):
    from rpython.annotator.model import SomeInteriorPtr
    assert not isinstance(s, SomeInteriorPtr)
    return SomeAddress()

def llmemory_cast_adr_to_ptr(s, s_type):
    assert s_type.is_constant()
    return SomePtr(s_type.const)

def llmemory_cast_adr_to_int(s, s_mode=None):
    return SomeInteger() # xxx

def llmemory_cast_int_to_adr(s):
    return SomeAddress()

def unicodedata_decimal(s_uchr):
    raise TypeError, "unicodedate.decimal() calls should not happen at interp-level"    

def test(*args):
    return s_Bool

def import_func(*args):
    return SomeObject()

# collect all functions
import __builtin__
BUILTIN_ANALYZERS = {}
for name, value in globals().items():
    if name.startswith('builtin_'):
        original = getattr(__builtin__, name[8:])
        BUILTIN_ANALYZERS[original] = value

BUILTIN_ANALYZERS[rpython.rlib.rarithmetic.intmask] = rarith_intmask
BUILTIN_ANALYZERS[rpython.rlib.rarithmetic.longlongmask] = rarith_longlongmask
BUILTIN_ANALYZERS[rpython.rlib.objectmodel.instantiate] = robjmodel_instantiate
BUILTIN_ANALYZERS[rpython.rlib.objectmodel.r_dict] = robjmodel_r_dict
BUILTIN_ANALYZERS[rpython.rlib.objectmodel.hlinvoke] = robjmodel_hlinvoke
BUILTIN_ANALYZERS[rpython.rlib.objectmodel.keepalive_until_here] = robjmodel_keepalive_until_here
BUILTIN_ANALYZERS[rpython.rtyper.lltypesystem.llmemory.cast_ptr_to_adr] = llmemory_cast_ptr_to_adr
BUILTIN_ANALYZERS[rpython.rtyper.lltypesystem.llmemory.cast_adr_to_ptr] = llmemory_cast_adr_to_ptr
BUILTIN_ANALYZERS[rpython.rtyper.lltypesystem.llmemory.cast_adr_to_int] = llmemory_cast_adr_to_int
BUILTIN_ANALYZERS[rpython.rtyper.lltypesystem.llmemory.cast_int_to_adr] = llmemory_cast_int_to_adr

BUILTIN_ANALYZERS[getattr(OSError.__init__, 'im_func', OSError.__init__)] = (
    OSError_init)

try:
    WindowsError
except NameError:
    pass
else:
    BUILTIN_ANALYZERS[getattr(WindowsError.__init__, 'im_func',
                              WindowsError.__init__)] = (
        WindowsError_init)

BUILTIN_ANALYZERS[sys.getdefaultencoding] = conf
try:
    import unicodedata
except ImportError:
    pass
else:
    BUILTIN_ANALYZERS[unicodedata.decimal] = unicodedata_decimal # xxx

# object - just ignore object.__init__
if hasattr(object.__init__, 'im_func'):
    BUILTIN_ANALYZERS[object.__init__.im_func] = object_init
else:
    BUILTIN_ANALYZERS[object.__init__] = object_init    

# import
BUILTIN_ANALYZERS[__import__] = import_func

# annotation of low-level types
from rpython.annotator.model import SomePtr
from rpython.rtyper.lltypesystem import lltype

def malloc(s_T, s_n=None, s_flavor=None, s_zero=None, s_track_allocation=None,
           s_add_memory_pressure=None):
    assert (s_n is None or s_n.knowntype == int
            or issubclass(s_n.knowntype, rpython.rlib.rarithmetic.base_int))
    assert s_T.is_constant()
    if s_n is not None:
        n = 1
    else:
        n = None
    if s_zero:
        assert s_zero.is_constant()
    if s_flavor is None:
        p = lltype.malloc(s_T.const, n)
        r = SomePtr(lltype.typeOf(p))
    else:
        assert s_flavor.is_constant()
        assert s_track_allocation is None or s_track_allocation.is_constant()
        assert (s_add_memory_pressure is None or
                s_add_memory_pressure.is_constant())
        # not sure how to call malloc() for the example 'p' in the
        # presence of s_extraargs
        r = SomePtr(lltype.Ptr(s_T.const))
    return r

def free(s_p, s_flavor, s_track_allocation=None):
    assert s_flavor.is_constant()
    assert s_track_allocation is None or s_track_allocation.is_constant()
    # same problem as in malloc(): some flavors are not easy to
    # malloc-by-example
    #T = s_p.ll_ptrtype.TO
    #p = lltype.malloc(T, flavor=s_flavor.const)
    #lltype.free(p, flavor=s_flavor.const)

def render_immortal(s_p, s_track_allocation=None):
    assert s_track_allocation is None or s_track_allocation.is_constant()

def typeOf(s_val):
    lltype = annotation_to_lltype(s_val, info="in typeOf(): ")
    return immutablevalue(lltype)

def cast_primitive(T, s_v):
    assert T.is_constant()
    return ll_to_annotation(lltype.cast_primitive(T.const, annotation_to_lltype(s_v)._defl()))

def nullptr(T):
    assert T.is_constant()
    p = lltype.nullptr(T.const)
    return immutablevalue(p)

def cast_pointer(PtrT, s_p):
    assert isinstance(s_p, SomePtr), "casting of non-pointer: %r" % s_p
    assert PtrT.is_constant()
    cast_p = lltype.cast_pointer(PtrT.const, s_p.ll_ptrtype._defl())
    return SomePtr(ll_ptrtype=lltype.typeOf(cast_p))

def cast_opaque_ptr(PtrT, s_p):
    assert isinstance(s_p, SomePtr), "casting of non-pointer: %r" % s_p
    assert PtrT.is_constant()
    cast_p = lltype.cast_opaque_ptr(PtrT.const, s_p.ll_ptrtype._defl())
    return SomePtr(ll_ptrtype=lltype.typeOf(cast_p))

def direct_fieldptr(s_p, s_fieldname):
    assert isinstance(s_p, SomePtr), "direct_* of non-pointer: %r" % s_p
    assert s_fieldname.is_constant()
    cast_p = lltype.direct_fieldptr(s_p.ll_ptrtype._example(),
                                    s_fieldname.const)
    return SomePtr(ll_ptrtype=lltype.typeOf(cast_p))

def direct_arrayitems(s_p):
    assert isinstance(s_p, SomePtr), "direct_* of non-pointer: %r" % s_p
    cast_p = lltype.direct_arrayitems(s_p.ll_ptrtype._example())
    return SomePtr(ll_ptrtype=lltype.typeOf(cast_p))

def direct_ptradd(s_p, s_n):
    assert isinstance(s_p, SomePtr), "direct_* of non-pointer: %r" % s_p
    # don't bother with an example here: the resulting pointer is the same
    return s_p

def cast_ptr_to_int(s_ptr): # xxx
    return SomeInteger()

def cast_int_to_ptr(PtrT, s_int):
    assert PtrT.is_constant()
    return SomePtr(ll_ptrtype=PtrT.const)

def identityhash(s_obj):
    assert isinstance(s_obj, (SomePtr, SomeOOObject, SomeOOInstance))
    return SomeInteger()

def getRuntimeTypeInfo(T):
    assert T.is_constant()
    return immutablevalue(lltype.getRuntimeTypeInfo(T.const))

def runtime_type_info(s_p):
    assert isinstance(s_p, SomePtr), "runtime_type_info of non-pointer: %r" % s_p
    return SomePtr(lltype.typeOf(lltype.runtime_type_info(s_p.ll_ptrtype._example())))

def constPtr(T):
    assert T.is_constant()
    return immutablevalue(lltype.Ptr(T.const))

BUILTIN_ANALYZERS[lltype.malloc] = malloc
BUILTIN_ANALYZERS[lltype.free] = free
BUILTIN_ANALYZERS[lltype.render_immortal] = render_immortal
BUILTIN_ANALYZERS[lltype.typeOf] = typeOf
BUILTIN_ANALYZERS[lltype.cast_primitive] = cast_primitive
BUILTIN_ANALYZERS[lltype.nullptr] = nullptr
BUILTIN_ANALYZERS[lltype.cast_pointer] = cast_pointer
BUILTIN_ANALYZERS[lltype.cast_opaque_ptr] = cast_opaque_ptr
BUILTIN_ANALYZERS[lltype.direct_fieldptr] = direct_fieldptr
BUILTIN_ANALYZERS[lltype.direct_arrayitems] = direct_arrayitems
BUILTIN_ANALYZERS[lltype.direct_ptradd] = direct_ptradd
BUILTIN_ANALYZERS[lltype.cast_ptr_to_int] = cast_ptr_to_int
BUILTIN_ANALYZERS[lltype.cast_int_to_ptr] = cast_int_to_ptr
BUILTIN_ANALYZERS[lltype.identityhash] = identityhash
BUILTIN_ANALYZERS[lltype.getRuntimeTypeInfo] = getRuntimeTypeInfo
BUILTIN_ANALYZERS[lltype.runtime_type_info] = runtime_type_info
BUILTIN_ANALYZERS[lltype.Ptr] = constPtr

# ootype
from rpython.annotator.model import SomeOOInstance, SomeOOClass, SomeOOStaticMeth
from rpython.rtyper.ootypesystem import ootype

def new(I):
    assert I.is_constant()
    i = ootype.new(I.const)
    r = SomeOOInstance(ootype.typeOf(i))
    return r

def oonewarray(s_type, length):
    assert s_type.is_constant()
    return SomeOOInstance(s_type.const)

def null(I_OR_SM):
    assert I_OR_SM.is_constant()
    null = ootype.null(I_OR_SM.const)
    r = lltype_to_annotation(ootype.typeOf(null))
    return r

def instanceof(i, I):
    assert I.is_constant()
    assert isinstance(I.const, ootype.Instance)
    return s_Bool

def classof(i):
    assert isinstance(i, SomeOOInstance) 
    return SomeOOClass(i.ootype)

def subclassof(class1, class2):
    assert isinstance(class1, SomeOOClass) 
    assert isinstance(class2, SomeOOClass) 
    return s_Bool

def runtimenew(c):
    assert isinstance(c, SomeOOClass)
    if c.ootype is None:
        return s_ImpossibleValue   # can't call runtimenew(NULL)
    else:
        return SomeOOInstance(c.ootype)

def ooupcast(I, i):
    assert isinstance(I.const, ootype.Instance)
    if ootype.isSubclass(i.ootype, I.const):
        return SomeOOInstance(I.const)
    else:
        raise AnnotatorError, 'Cannot cast %s to %s' % (i.ootype, I.const)

def oodowncast(I, i):
    assert isinstance(I.const, ootype.Instance)
    if ootype.isSubclass(I.const, i.ootype):
        return SomeOOInstance(I.const)
    else:
        raise AnnotatorError, 'Cannot cast %s to %s' % (i.ootype, I.const)

def cast_to_object(obj):
    assert isinstance(obj, SomeOOStaticMeth) or \
           (isinstance(obj, SomeOOClass) and obj.ootype is None) or \
           isinstance(obj.ootype, ootype.OOType)
    return SomeOOObject()

def cast_from_object(T, obj):
    TYPE = T.const
    if TYPE is ootype.Object:
        return SomeOOObject()
    elif TYPE is ootype.Class:
        return SomeOOClass(ootype.ROOT) # ???
    elif isinstance(TYPE, ootype.StaticMethod):
        return SomeOOStaticMeth(TYPE)
    elif isinstance(TYPE, ootype.OOType):
        return SomeOOInstance(TYPE)
    else:
        raise AnnotatorError, 'Cannot cast Object to %s' % TYPE

BUILTIN_ANALYZERS[ootype.instanceof] = instanceof
BUILTIN_ANALYZERS[ootype.new] = new
BUILTIN_ANALYZERS[ootype.oonewarray] = oonewarray
BUILTIN_ANALYZERS[ootype.null] = null
BUILTIN_ANALYZERS[ootype.runtimenew] = runtimenew
BUILTIN_ANALYZERS[ootype.classof] = classof
BUILTIN_ANALYZERS[ootype.subclassof] = subclassof
BUILTIN_ANALYZERS[ootype.ooupcast] = ooupcast
BUILTIN_ANALYZERS[ootype.oodowncast] = oodowncast
BUILTIN_ANALYZERS[ootype.cast_to_object] = cast_to_object
BUILTIN_ANALYZERS[ootype.cast_from_object] = cast_from_object

#________________________________
# weakrefs

import weakref

def weakref_ref(s_obj):
    if not isinstance(s_obj, SomeInstance):
        raise Exception("cannot take a weakref to %r" % (s_obj,))
    if s_obj.can_be_None:
        raise Exception("should assert that the instance we take "
                        "a weakref to cannot be None")
    return SomeWeakRef(s_obj.classdef)

BUILTIN_ANALYZERS[weakref.ref] = weakref_ref

def llweakref_create(s_obj):
    if (not isinstance(s_obj, SomePtr) or
        s_obj.ll_ptrtype.TO._gckind != 'gc'):
        raise Exception("bad type for argument to weakref_create(): %r" % (
            s_obj,))
    return SomePtr(llmemory.WeakRefPtr)

def llweakref_deref(s_ptrtype, s_wref):
    if not (s_ptrtype.is_constant() and
            isinstance(s_ptrtype.const, lltype.Ptr) and
            s_ptrtype.const.TO._gckind == 'gc'):
        raise Exception("weakref_deref() arg 1 must be a constant "
                        "ptr type, got %s" % (s_ptrtype,))
    if not (isinstance(s_wref, SomePtr) and
            s_wref.ll_ptrtype == llmemory.WeakRefPtr):
        raise Exception("weakref_deref() arg 2 must be a WeakRefPtr, "
                        "got %s" % (s_wref,))
    return SomePtr(s_ptrtype.const)

def llcast_ptr_to_weakrefptr(s_ptr):
    assert isinstance(s_ptr, SomePtr)
    return SomePtr(llmemory.WeakRefPtr)

def llcast_weakrefptr_to_ptr(s_ptrtype, s_wref):
    if not (s_ptrtype.is_constant() and
            isinstance(s_ptrtype.const, lltype.Ptr)):
        raise Exception("cast_weakrefptr_to_ptr() arg 1 must be a constant "
                        "ptr type, got %s" % (s_ptrtype,))
    if not (isinstance(s_wref, SomePtr) and
            s_wref.ll_ptrtype == llmemory.WeakRefPtr):
        raise Exception("cast_weakrefptr_to_ptr() arg 2 must be a WeakRefPtr, "
                        "got %s" % (s_wref,))
    return SomePtr(s_ptrtype.const)

from rpython.rtyper.lltypesystem import llmemory
BUILTIN_ANALYZERS[llmemory.weakref_create] = llweakref_create
BUILTIN_ANALYZERS[llmemory.weakref_deref ] = llweakref_deref
BUILTIN_ANALYZERS[llmemory.cast_ptr_to_weakrefptr] = llcast_ptr_to_weakrefptr
BUILTIN_ANALYZERS[llmemory.cast_weakrefptr_to_ptr] = llcast_weakrefptr_to_ptr

#________________________________
# non-gc objects

def robjmodel_free_non_gc_object(obj):
    pass

BUILTIN_ANALYZERS[rpython.rlib.objectmodel.free_non_gc_object] = (
    robjmodel_free_non_gc_object)

#_________________________________
# memory address

def raw_malloc(s_size):
    assert isinstance(s_size, SomeInteger) #XXX add noneg...?
    return SomeAddress()

def raw_malloc_usage(s_size):
    assert isinstance(s_size, SomeInteger) #XXX add noneg...?
    return SomeInteger(nonneg=True)

def raw_free(s_addr):
    assert isinstance(s_addr, SomeAddress)

def raw_memclear(s_addr, s_int):
    assert isinstance(s_addr, SomeAddress)
    assert isinstance(s_int, SomeInteger)

def raw_memcopy(s_addr1, s_addr2, s_int):
    assert isinstance(s_addr1, SomeAddress)
    assert isinstance(s_addr2, SomeAddress)
    assert isinstance(s_int, SomeInteger) #XXX add noneg...?

BUILTIN_ANALYZERS[llmemory.raw_malloc] = raw_malloc
BUILTIN_ANALYZERS[llmemory.raw_malloc_usage] = raw_malloc_usage
BUILTIN_ANALYZERS[llmemory.raw_free] = raw_free
BUILTIN_ANALYZERS[llmemory.raw_memclear] = raw_memclear
BUILTIN_ANALYZERS[llmemory.raw_memcopy] = raw_memcopy

#_________________________________
# offsetof/sizeof


def offsetof(TYPE, fldname):
    return SomeInteger()

BUILTIN_ANALYZERS[llmemory.offsetof] = offsetof

