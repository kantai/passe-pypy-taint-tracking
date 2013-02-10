import operator
from rpython.tool.pairtype import pairtype
from rpython.annotator import model as annmodel
from rpython.flowspace.model import Constant
from rpython.rtyper.error import TyperError
from rpython.rtyper.rmodel import Repr, IntegerRepr, inputconst
from rpython.rtyper.rmodel import IteratorRepr
from rpython.rtyper.rmodel import externalvsinternal
from rpython.rtyper.lltypesystem.lltype import Void, Signed, Bool
from rpython.rlib.rarithmetic import intmask
from rpython.rlib.unroll import unrolling_iterable

class __extend__(annmodel.SomeTuple):
    def rtyper_makerepr(self, rtyper):
        repr_class = rtyper.type_system.rtuple.TupleRepr
        return repr_class(rtyper, [rtyper.getrepr(s_item) for s_item in self.items])
    
    def rtyper_makekey_ex(self, rtyper):
        keys = [rtyper.makekey(s_item) for s_item in self.items]
        return tuple([self.__class__]+keys)


_gen_eq_function_cache = {}
_gen_hash_function_cache = {}
_gen_str_function_cache = {}

def gen_eq_function(items_r):
    eq_funcs = [r_item.get_ll_eq_function() or operator.eq for r_item in items_r]
    key = tuple(eq_funcs)
    try:
        return _gen_eq_function_cache[key]
    except KeyError:
        autounrolling_funclist = unrolling_iterable(enumerate(eq_funcs))

        def ll_eq(t1, t2):
            equal_so_far = True
            for i, eqfn in autounrolling_funclist:
                if not equal_so_far:
                    return False
                attrname = 'item%d' % i
                item1 = getattr(t1, attrname)
                item2 = getattr(t2, attrname)
                equal_so_far = eqfn(item1, item2)
            return equal_so_far

        _gen_eq_function_cache[key] = ll_eq
        return ll_eq

def gen_hash_function(items_r):
    # based on CPython
    hash_funcs = [r_item.get_ll_hash_function() for r_item in items_r]
    key = tuple(hash_funcs)
    try:
        return _gen_hash_function_cache[key]
    except KeyError:
        autounrolling_funclist = unrolling_iterable(enumerate(hash_funcs))

        def ll_hash(t):
            """Must be kept in sync with rlib.objectmodel._hash_tuple()."""
            x = 0x345678
            for i, hash_func in autounrolling_funclist:
                attrname = 'item%d' % i
                item = getattr(t, attrname)
                y = hash_func(item)
                x = intmask((1000003 * x) ^ y)
            return x

        _gen_hash_function_cache[key] = ll_hash
        return ll_hash

def gen_str_function(tuplerepr):
    items_r = tuplerepr.items_r
    str_funcs = [r_item.ll_str for r_item in items_r]
    key = tuplerepr.rstr_ll, tuple(str_funcs)
    try:
        return _gen_str_function_cache[key]
    except KeyError:
        autounrolling_funclist = unrolling_iterable(enumerate(str_funcs))

        constant = tuplerepr.rstr_ll.ll_constant
        start    = tuplerepr.rstr_ll.ll_build_start
        push     = tuplerepr.rstr_ll.ll_build_push
        finish   = tuplerepr.rstr_ll.ll_build_finish
        length = len(items_r)

        def ll_str(t):
            if length == 0:
                return constant("()")
            buf = start(2 * length + 1)
            push(buf, constant("("), 0)
            for i, str_func in autounrolling_funclist:
                attrname = 'item%d' % i
                item = getattr(t, attrname)
                if i > 0:
                    push(buf, constant(", "), 2 * i)
                push(buf, str_func(item), 2 * i + 1)
            if length == 1:
                push(buf, constant(",)"), 2 * length)
            else:
                push(buf, constant(")"), 2 * length)
            return finish(buf)

        _gen_str_function_cache[key] = ll_str
        return ll_str


class AbstractTupleRepr(Repr):

    def __init__(self, rtyper, items_r):
        self.items_r = []
        self.external_items_r = []
        for item_r in items_r:
            external_repr, internal_repr = externalvsinternal(rtyper, item_r)
            self.items_r.append(internal_repr)
            self.external_items_r.append(external_repr)
        items_r = self.items_r
        self.fieldnames = ['item%d' % i for i in range(len(items_r))]
        self.lltypes = [r.lowleveltype for r in items_r]
        self.tuple_cache = {}

    def getitem(self, llops, v_tuple, index):
        """Generate the operations to get the index'th item of v_tuple,
        in the external repr external_items_r[index]."""
        v = self.getitem_internal(llops, v_tuple, index)
        r_item = self.items_r[index]
        r_external_item = self.external_items_r[index]
        return llops.convertvar(v, r_item, r_external_item)

    def newtuple_cached(cls, hop, items_v):
        r_tuple = hop.r_result
        if hop.s_result.is_constant():
            return inputconst(r_tuple, hop.s_result.const)
        else:
            return cls.newtuple(hop.llops, r_tuple, items_v)
    newtuple_cached = classmethod(newtuple_cached)

    def _rtype_newtuple(cls, hop):
        r_tuple = hop.r_result
        vlist = hop.inputargs(*r_tuple.items_r)
        return cls.newtuple_cached(hop, vlist)
    _rtype_newtuple = classmethod(_rtype_newtuple)

    def convert_const(self, value):
        assert isinstance(value, tuple) and len(value) == len(self.items_r)
        key = tuple([Constant(item) for item in value])
        try:
            return self.tuple_cache[key]
        except KeyError:
            p = self.instantiate()
            self.tuple_cache[key] = p
            for obj, r, name in zip(value, self.items_r, self.fieldnames):
                if r.lowleveltype is not Void:
                    setattr(p, name, r.convert_const(obj))
            return p

    def compact_repr(self):
        return "TupleR %s" % ' '.join([llt._short_name() for llt in self.lltypes])

    def rtype_len(self, hop):
        return hop.inputconst(Signed, len(self.items_r))

    def get_ll_eq_function(self):
        return gen_eq_function(self.items_r)

    def get_ll_hash_function(self):
        return gen_hash_function(self.items_r)

    ll_str = property(gen_str_function)

    def make_iterator_repr(self):
        if len(self.items_r) == 1:
            # subclasses are supposed to set the IteratorRepr attribute
            return self.IteratorRepr(self)
        raise TyperError("can only iterate over tuples of length 1 for now")


class __extend__(pairtype(AbstractTupleRepr, IntegerRepr)):

    def rtype_getitem((r_tup, r_int), hop):
        v_tuple, v_index = hop.inputargs(r_tup, Signed)
        if not isinstance(v_index, Constant):
            raise TyperError("non-constant tuple index")
        if hop.has_implicit_exception(IndexError):
            hop.exception_cannot_occur()
        index = v_index.value
        return r_tup.getitem(hop.llops, v_tuple, index)

class __extend__(AbstractTupleRepr):

    def rtype_getslice(r_tup, hop):
        s_start = hop.args_s[1]
        s_stop = hop.args_s[2]
        assert s_start.is_immutable_constant(),"tuple slicing: needs constants"
        assert s_stop.is_immutable_constant(), "tuple slicing: needs constants"
        start = s_start.const
        stop = s_stop.const
        indices = range(len(r_tup.items_r))[start:stop]
        assert len(indices) == len(hop.r_result.items_r)

        v_tup = hop.inputarg(r_tup, arg=0)
        items_v = [r_tup.getitem_internal(hop.llops, v_tup, i)
                   for i in indices]
        return hop.r_result.newtuple(hop.llops, hop.r_result, items_v)

class __extend__(pairtype(AbstractTupleRepr, Repr)): 
    def rtype_contains((r_tup, r_item), hop):
        s_tup = hop.args_s[0]
        if not s_tup.is_constant():
            raise TyperError("contains() on non-const tuple") 
        t = s_tup.const
        typ = type(t[0]) 
        for x in t[1:]: 
            if type(x) is not typ: 
                raise TyperError("contains() on mixed-type tuple "
                                 "constant %r" % (t,))
        d = {}
        for x in t: 
            d[x] = None 
        hop2 = hop.copy()
        _, _ = hop2.r_s_popfirstarg()
        v_dict = Constant(d)
        s_dict = hop.rtyper.annotator.bookkeeper.immutablevalue(d)
        hop2.v_s_insertfirstarg(v_dict, s_dict)
        return hop2.dispatch()
 
class __extend__(pairtype(AbstractTupleRepr, AbstractTupleRepr)):
    
    def rtype_add((r_tup1, r_tup2), hop):
        v_tuple1, v_tuple2 = hop.inputargs(r_tup1, r_tup2)
        vlist = []
        for i in range(len(r_tup1.items_r)):
            vlist.append(r_tup1.getitem_internal(hop.llops, v_tuple1, i))
        for i in range(len(r_tup2.items_r)):
            vlist.append(r_tup2.getitem_internal(hop.llops, v_tuple2, i))
        return r_tup1.newtuple_cached(hop, vlist)
    rtype_inplace_add = rtype_add

    def rtype_eq((r_tup1, r_tup2), hop):
        s_tup = annmodel.unionof(*hop.args_s)
        r_tup = hop.rtyper.getrepr(s_tup)
        v_tuple1, v_tuple2 = hop.inputargs(r_tup, r_tup)
        ll_eq = r_tup.get_ll_eq_function()
        return hop.gendirectcall(ll_eq, v_tuple1, v_tuple2)

    def rtype_ne(tup1tup2, hop):
        v_res = tup1tup2.rtype_eq(hop)
        return hop.genop('bool_not', [v_res], resulttype=Bool)

    def convert_from_to((r_from, r_to), v, llops):
        if len(r_from.items_r) == len(r_to.items_r):
            if r_from.lowleveltype == r_to.lowleveltype:
                return v
            n = len(r_from.items_r)
            items_v = []
            for i in range(n):
                item_v = r_from.getitem_internal(llops, v, i)
                item_v = llops.convertvar(item_v,
                                              r_from.items_r[i],
                                              r_to.items_r[i])
                items_v.append(item_v)
            return r_from.newtuple(llops, r_to, items_v)
        return NotImplemented

    def rtype_is_((robj1, robj2), hop):
        raise TyperError("cannot compare tuples with 'is'")


class AbstractTupleIteratorRepr(IteratorRepr):

    def newiter(self, hop):
        v_tuple, = hop.inputargs(self.r_tuple)
        citerptr = hop.inputconst(Void, self.lowleveltype)
        return hop.gendirectcall(self.ll_tupleiter, citerptr, v_tuple)

    def rtype_next(self, hop):
        v_iter, = hop.inputargs(self)
        hop.has_implicit_exception(StopIteration) # record that we know about it
        hop.exception_is_here()
        v = hop.gendirectcall(self.ll_tuplenext, v_iter)
        return hop.llops.convertvar(v, self.r_tuple.items_r[0], self.r_tuple.external_items_r[0])

