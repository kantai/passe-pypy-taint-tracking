import sys
from rpython.tool.pairtype import pairtype
from rpython.annotator import model as annmodel
from rpython.flowspace.operation import op_appendices
from rpython.rtyper.lltypesystem.lltype import Signed, Unsigned, Bool, Float, \
     Void, Char, UniChar, malloc, UnsignedLongLong, \
     SignedLongLong, build_number, Number, cast_primitive, typeOf, \
     SignedLongLongLong
from rpython.rtyper.rmodel import IntegerRepr, inputconst
from rpython.rlib.rarithmetic import intmask, r_int, r_uint, r_ulonglong, \
     r_longlong, is_emulated_long
from rpython.rtyper.error import TyperError, MissingRTypeOperation
from rpython.rtyper.rmodel import log
from rpython.rlib import objectmodel

_integer_reprs = {}
def getintegerrepr(lltype, prefix=None):
    try:
        return _integer_reprs[lltype]
    except KeyError:
        pass
    repr = _integer_reprs[lltype] = IntegerRepr(lltype, prefix)
    return repr

class __extend__(annmodel.SomeInteger):
    def rtyper_makerepr(self, rtyper):
        lltype = build_number(None, self.knowntype)
        return getintegerrepr(lltype)

    def rtyper_makekey(self):
        return self.__class__, self.knowntype

signed_repr = getintegerrepr(Signed, 'int_')
signedlonglong_repr = getintegerrepr(SignedLongLong, 'llong_')
signedlonglonglong_repr = getintegerrepr(SignedLongLongLong, 'lllong_')
unsigned_repr = getintegerrepr(Unsigned, 'uint_')
unsignedlonglong_repr = getintegerrepr(UnsignedLongLong, 'ullong_')

class __extend__(pairtype(IntegerRepr, IntegerRepr)):

    def convert_from_to((r_from, r_to), v, llops):
        if r_from.lowleveltype == Signed and r_to.lowleveltype == Unsigned:
            log.debug('explicit cast_int_to_uint')
            return llops.genop('cast_int_to_uint', [v], resulttype=Unsigned)
        if r_from.lowleveltype == Unsigned and r_to.lowleveltype == Signed:
            log.debug('explicit cast_uint_to_int')
            return llops.genop('cast_uint_to_int', [v], resulttype=Signed)
        if r_from.lowleveltype == Signed and r_to.lowleveltype == SignedLongLong:
            return llops.genop('cast_int_to_longlong', [v], resulttype=SignedLongLong)
        if r_from.lowleveltype == SignedLongLong and r_to.lowleveltype == Signed:
            return llops.genop('truncate_longlong_to_int', [v], resulttype=Signed)
        return llops.genop('cast_primitive', [v], resulttype=r_to.lowleveltype)

    #arithmetic

    def rtype_add(_, hop):
        return _rtype_template(hop, 'add')
    rtype_inplace_add = rtype_add

    def rtype_add_ovf(_, hop):
        func = 'add_ovf'
        if hop.r_result.opprefix == 'int_':
            if hop.args_s[1].nonneg:
                func = 'add_nonneg_ovf'
            elif hop.args_s[0].nonneg:
                hop = hop.copy()
                hop.swap_fst_snd_args()
                func = 'add_nonneg_ovf'
        return _rtype_template(hop, func)

    def rtype_sub(_, hop):
        return _rtype_template(hop, 'sub')
    rtype_inplace_sub = rtype_sub

    def rtype_sub_ovf(_, hop):
        return _rtype_template(hop, 'sub_ovf')

    def rtype_mul(_, hop):
        return _rtype_template(hop, 'mul')
    rtype_inplace_mul = rtype_mul

    def rtype_mul_ovf(_, hop):
        return _rtype_template(hop, 'mul_ovf')

    def rtype_floordiv(_, hop):
        return _rtype_template(hop, 'floordiv', [ZeroDivisionError])
    rtype_inplace_floordiv = rtype_floordiv

    def rtype_floordiv_ovf(_, hop):
        return _rtype_template(hop, 'floordiv_ovf', [ZeroDivisionError])

    # turn 'div' on integers into 'floordiv'
    rtype_div         = rtype_floordiv
    rtype_inplace_div = rtype_inplace_floordiv
    rtype_div_ovf     = rtype_floordiv_ovf

    # 'def rtype_truediv' is delegated to the superclass FloatRepr

    def rtype_mod(_, hop):
        return _rtype_template(hop, 'mod', [ZeroDivisionError])
    rtype_inplace_mod = rtype_mod

    def rtype_mod_ovf(_, hop):
        return _rtype_template(hop, 'mod_ovf', [ZeroDivisionError])

    def rtype_xor(_, hop):
        return _rtype_template(hop, 'xor')
    rtype_inplace_xor = rtype_xor

    def rtype_and_(_, hop):
        return _rtype_template(hop, 'and')
    rtype_inplace_and = rtype_and_

    def rtype_or_(_, hop):
        return _rtype_template(hop, 'or')
    rtype_inplace_or = rtype_or_

    def rtype_lshift(_, hop):
        return _rtype_template(hop, 'lshift')
    rtype_inplace_lshift = rtype_lshift

    def rtype_lshift_ovf(_, hop):
        return _rtype_template(hop, 'lshift_ovf')

    def rtype_rshift(_, hop):
        return _rtype_template(hop, 'rshift')
    rtype_inplace_rshift = rtype_rshift

    #comparisons: eq is_ ne lt le gt ge

    def rtype_eq(_, hop): 
        return _rtype_compare_template(hop, 'eq')

    rtype_is_ = rtype_eq

    def rtype_ne(_, hop):
        return _rtype_compare_template(hop, 'ne')

    def rtype_lt(_, hop):
        return _rtype_compare_template(hop, 'lt')

    def rtype_le(_, hop):
        return _rtype_compare_template(hop, 'le')

    def rtype_gt(_, hop):
        return _rtype_compare_template(hop, 'gt')

    def rtype_ge(_, hop):
        return _rtype_compare_template(hop, 'ge')

#Helper functions

def _rtype_template(hop, func, implicit_excs=[]):
    if func.endswith('_ovf'):
        if hop.s_result.unsigned:
            raise TyperError("forbidden unsigned " + func)
        else:
            hop.has_implicit_exception(OverflowError)

    for implicit_exc in implicit_excs:
        if hop.has_implicit_exception(implicit_exc):
            appendix = op_appendices[implicit_exc]
            func += '_' + appendix

    r_result = hop.r_result
    if r_result.lowleveltype == Bool:
        repr = signed_repr
    else:
        repr = r_result
    if func.startswith(('lshift', 'rshift')):
        repr2 = signed_repr
    else:
        repr2 = repr
    vlist = hop.inputargs(repr, repr2)
    hop.exception_is_here()

    prefix = repr.opprefix

    v_res = hop.genop(prefix+func, vlist, resulttype=repr)
    bothnonneg = hop.args_s[0].nonneg and hop.args_s[1].nonneg
    if prefix in ('int_', 'llong_') and not bothnonneg:

        # cpython, and rpython, assumed that integer division truncates
        # towards -infinity.  however, in C99 and most (all?) other
        # backends, integer division truncates towards 0.  so assuming
        # that, we call a helper function that applies the necessary
        # correction in the right cases.

        op = func.split('_', 1)[0]

        if op == 'floordiv':
            llfunc = globals()['ll_correct_' + prefix + 'floordiv']
            v_res = hop.gendirectcall(llfunc, vlist[0], vlist[1], v_res)
        elif op == 'mod':
            llfunc = globals()['ll_correct_' + prefix + 'mod']
            v_res = hop.gendirectcall(llfunc, vlist[1], v_res)

    v_res = hop.llops.convertvar(v_res, repr, r_result)
    return v_res


INT_BITS_1 = r_int.BITS - 1
LLONG_BITS_1 = r_longlong.BITS - 1

def ll_correct_int_floordiv(x, y, r):
    p = r * y
    if y < 0: u = p - x
    else:     u = x - p
    return r + (u >> INT_BITS_1)

def ll_correct_llong_floordiv(x, y, r):
    p = r * y
    if y < 0: u = p - x
    else:     u = x - p
    return r + (u >> LLONG_BITS_1)

def ll_correct_int_mod(y, r):
    if y < 0: u = -r
    else:     u = r
    return r + (y & (u >> INT_BITS_1))

def ll_correct_llong_mod(y, r):
    if y < 0: u = -r
    else:     u = r
    return r + (y & (u >> LLONG_BITS_1))


#Helper functions for comparisons

def _rtype_compare_template(hop, func):
    s_int1, s_int2 = hop.args_s
    if s_int1.unsigned or s_int2.unsigned:
        if not s_int1.nonneg or not s_int2.nonneg:
            raise TyperError("comparing a signed and an unsigned number")

    repr = hop.rtyper.makerepr(annmodel.unionof(s_int1, s_int2)).as_int
    vlist = hop.inputargs(repr, repr)
    hop.exception_is_here()
    return hop.genop(repr.opprefix+func, vlist, resulttype=Bool)


#

class __extend__(IntegerRepr):

    def convert_const(self, value):
        if isinstance(value, objectmodel.Symbolic):
            return value
        T = typeOf(value)
        if isinstance(T, Number) or T is Bool:
            return cast_primitive(self.lowleveltype, value)
        raise TyperError("not an integer: %r" % (value,))

    def get_ll_eq_function(self):
        return None
    get_ll_gt_function = get_ll_eq_function
    get_ll_lt_function = get_ll_eq_function
    get_ll_ge_function = get_ll_eq_function
    get_ll_le_function = get_ll_eq_function

    def get_ll_ge_function(self):
        return None 

    def get_ll_hash_function(self):
        if (sys.maxint == 2147483647 and
            self.lowleveltype in (SignedLongLong, UnsignedLongLong)):
            return ll_hash_long_long
        return ll_hash_int

    get_ll_fasthash_function = get_ll_hash_function

    def get_ll_dummyval_obj(self, rtyper, s_value):
        # if >= 0, then all negative values are special
        if s_value.nonneg and self.lowleveltype is Signed:
            return signed_repr    # whose ll_dummy_value is -1
        else:
            return None

    ll_dummy_value = -1

    def rtype_chr(_, hop):
        vlist =  hop.inputargs(Signed)
        if hop.has_implicit_exception(ValueError):
            hop.exception_is_here()
            hop.gendirectcall(ll_check_chr, vlist[0])
        else:
            hop.exception_cannot_occur()
        return hop.genop('cast_int_to_char', vlist, resulttype=Char)

    def rtype_unichr(_, hop):
        vlist = hop.inputargs(Signed)
        if hop.has_implicit_exception(ValueError):
            hop.exception_is_here()
            hop.gendirectcall(ll_check_unichr, vlist[0])
        else:
            hop.exception_cannot_occur()
        return hop.genop('cast_int_to_unichar', vlist, resulttype=UniChar)

    def rtype_is_true(self, hop):
        assert self is self.as_int   # rtype_is_true() is overridden in BoolRepr
        vlist = hop.inputargs(self)
        return hop.genop(self.opprefix + 'is_true', vlist, resulttype=Bool)

    #Unary arithmetic operations    
    
    def rtype_abs(self, hop):
        self = self.as_int
        vlist = hop.inputargs(self)
        if hop.s_result.unsigned:
            return vlist[0]
        else:
            return hop.genop(self.opprefix + 'abs', vlist, resulttype=self)

    def rtype_abs_ovf(self, hop):
        self = self.as_int
        if hop.s_result.unsigned:
            raise TyperError("forbidden uint_abs_ovf")
        else:
            vlist = hop.inputargs(self)
            hop.has_implicit_exception(OverflowError) # record we know about it
            hop.exception_is_here()
            return hop.genop(self.opprefix + 'abs_ovf', vlist, resulttype=self)

    def rtype_invert(self, hop):
        self = self.as_int
        vlist = hop.inputargs(self)
        return hop.genop(self.opprefix + 'invert', vlist, resulttype=self)
        
    def rtype_neg(self, hop):
        self = self.as_int
        vlist = hop.inputargs(self)
        if hop.s_result.unsigned:
            # implement '-r_uint(x)' with unsigned subtraction '0 - x'
            zero = self.lowleveltype._defl()
            vlist.insert(0, hop.inputconst(self.lowleveltype, zero))
            return hop.genop(self.opprefix + 'sub', vlist, resulttype=self)
        else:
            return hop.genop(self.opprefix + 'neg', vlist, resulttype=self)

    def rtype_neg_ovf(self, hop):
        self = self.as_int
        if hop.s_result.unsigned:
            # this is supported (and turns into just 0-x) for rbigint.py
            hop.exception_cannot_occur()
            return self.rtype_neg(hop)
        else:
            vlist = hop.inputargs(self)
            hop.has_implicit_exception(OverflowError) # record we know about it
            hop.exception_is_here()
            return hop.genop(self.opprefix + 'neg_ovf', vlist, resulttype=self)

    def rtype_pos(self, hop):
        self = self.as_int
        vlist = hop.inputargs(self)
        return vlist[0]

    def rtype_int(self, hop):
        if self.lowleveltype in (Unsigned, UnsignedLongLong):
            raise TyperError("use intmask() instead of int(r_uint(...))")
        vlist = hop.inputargs(Signed)
        hop.exception_cannot_occur()
        return vlist[0]

    def rtype_float(_, hop):
        vlist = hop.inputargs(Float)
        hop.exception_cannot_occur()
        return vlist[0]

    # version picked by specialisation based on which
    # type system rtyping is using, from <type_system>.ll_str module
    def ll_str(self, i):
        raise NotImplementedError
    ll_str._annspecialcase_ = "specialize:ts('ll_str.ll_int_str')"

    def rtype_hex(self, hop):
        self = self.as_int
        varg = hop.inputarg(self, 0)
        true = inputconst(Bool, True)
        fn = hop.rtyper.type_system.ll_str.ll_int2hex
        return hop.gendirectcall(fn, varg, true)

    def rtype_oct(self, hop):
        self = self.as_int
        varg = hop.inputarg(self, 0)
        true = inputconst(Bool, True)
        fn = hop.rtyper.type_system.ll_str.ll_int2oct
        return hop.gendirectcall(fn, varg, true)

def ll_hash_int(n):
    return intmask(n)

def ll_hash_long_long(n):
    return intmask(intmask(n) + 9 * intmask(n >> 32))

def ll_check_chr(n):
    if 0 <= n <= 255:
        return
    else:
        raise ValueError

def ll_check_unichr(n):
    from rpython.rlib.runicode import MAXUNICODE
    if 0 <= n <= MAXUNICODE:
        return
    else:
        raise ValueError
