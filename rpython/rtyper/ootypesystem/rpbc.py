from rpython.rtyper.rmodel import CanBeNull, Repr, inputconst, impossible_repr
from rpython.rtyper.rpbc import AbstractClassesPBCRepr, AbstractMethodsPBCRepr, \
        AbstractMultipleFrozenPBCRepr, MethodOfFrozenPBCRepr, \
        AbstractFunctionsPBCRepr, AbstractMultipleUnrelatedFrozenPBCRepr, \
        none_frozen_pbc_repr
from rpython.rtyper.rclass import rtype_new_instance, getinstancerepr
from rpython.rtyper.rclass import getclassrepr, get_type_repr
from rpython.rtyper.rpbc import get_concrete_calltable
from rpython.rtyper import callparse
from rpython.rtyper.ootypesystem import ootype
from rpython.rtyper.ootypesystem.rclass import ClassRepr, InstanceRepr 
from rpython.rtyper.ootypesystem.rclass import mangle, META
from rpython.annotator import model as annmodel
from rpython.annotator import description
from rpython.tool.pairtype import pairtype
from rpython.flowspace.model import Constant, Variable
import types


def rtype_is_None(robj1, rnone2, hop, pos=0):
    if robj1 == none_frozen_pbc_repr:
        return hop.inputconst(ootype.Bool, True)
    v1 = hop.inputarg(robj1, pos)
    return hop.genop('ooisnull', [v1], resulttype=ootype.Bool)


class FunctionsPBCRepr(AbstractFunctionsPBCRepr):
    """Representation selected for a PBC of function(s)."""

    def setup_specfunc(self):
        fields = {}
        for row in self.uniquerows:
            fields[row.attrname] = row.fntype
        return ootype.Instance('specfunc', ootype.ROOT, fields)

    def create_specfunc(self):
        return ootype.new(self.lowleveltype)

    def get_specfunc_row(self, llop, v, c_rowname, resulttype):
        return llop.genop('oogetfield', [v, c_rowname], resulttype=resulttype)
        
class ClassesPBCRepr(AbstractClassesPBCRepr):
    
    def _instantiate_runtime_class(self, hop, v_class, r_instance):
        classdef = hop.s_result.classdef            
        resulttype = getinstancerepr(hop.rtyper, classdef).lowleveltype
        # convert v_class from META to ootype.Class if necessary:
        v_class = get_type_repr(hop.rtyper).fromclasstype(v_class, hop.llops)
        return hop.genop('runtimenew', [v_class], resulttype=resulttype)

    def getlowleveltype(self):
        classdescs = list(self.s_pbc.descriptions)
        # if any of the classdefs get the lowleveltype ootype.Class,
        # we can only pick ootype.Class for us too.  Otherwise META.
        for classdesc in classdescs:
            for classdef in classdesc.getallclassdefs():
                r_class = getclassrepr(self.rtyper, classdef)
                if r_class.lowleveltype == ootype.Class:
                    return ootype.Class
        else:
            return META


def row_method_name(methodname, rowname):
    if rowname is None:
        return methodname
    else:
        return "%s_%s" % (methodname, rowname)
    
class MethodImplementations(object):

    def __init__(self, rtyper, methdescs):
        samplemdesc = iter(methdescs).next()
        concretetable, uniquerows = get_concrete_calltable(rtyper,
                                             samplemdesc.funcdesc.getcallfamily())
        self.row_mapping = {}
        for row in uniquerows:
            sample_as_static_meth = row.itervalues().next()
            SM = ootype.typeOf(sample_as_static_meth)
            M = ootype.Meth(SM.ARGS[1:], SM.RESULT) # cut self
            self.row_mapping[row.attrname] = row, M

    def get(rtyper, s_pbc):
        lst = list(s_pbc.descriptions)
        lst.sort()
        key = tuple(lst)
        try:
            return rtyper.oo_meth_impls[key]
        except KeyError:
            methodsimpl = MethodImplementations(rtyper, s_pbc.descriptions)
            rtyper.oo_meth_impls[key] = methodsimpl
            return methodsimpl
    get = staticmethod(get)

    def get_impl(self, name, methdesc, is_finalizer=False):
        impls = {}
        flags = {}
        if is_finalizer:
            flags['finalizer'] = True
        for rowname, (row, M) in self.row_mapping.iteritems():
            if methdesc is None:
                m = ootype.meth(M, _name=name, abstract=True, **flags)
            else:
                try:
                    impl_graph = row[methdesc.funcdesc].graph
                except KeyError:
                    m = ootype.meth(M, _name=name, abstract=True, **flags) # XXX ???
                else:
                    m = ootype.meth(M, _name=name, graph=impl_graph, **flags)
            derived_name = row_method_name(name, rowname)
            impls[derived_name] = m
        return impls


class MethodsPBCRepr(AbstractMethodsPBCRepr):

    concretetable = None # set by _setup_repr_final

    def _setup_repr_final(self):
        sampledesc = self.s_pbc.any_description()
        self.concretetable, _ = get_concrete_calltable(self.rtyper,
                                             sampledesc.funcdesc.getcallfamily())

    def rtype_simple_call(self, hop):
        return self.call("simple_call", hop)

    def rtype_call_args(self, hop):
        return self.call("call_args", hop)

    def call(self, opname, hop):
        s_pbc = hop.args_s[0]   # possibly more precise than self.s_pbc        
        args_s = hop.args_s[1:]
        shape, index, callfamily = self._get_shape_index_callfamily(opname, s_pbc, args_s, hop)
        row_of_graphs = callfamily.calltables[shape][index]
        anygraph = row_of_graphs.itervalues().next()  # pick any witness
        hop2 = self.add_instance_arg_to_hop(hop, opname == "call_args")
        vlist = callparse.callparse(self.rtyper, anygraph, hop2, opname,
                                    r_self = self.r_im_self)
        rresult = callparse.getrresult(self.rtyper, anygraph)
        derived_mangled = self._get_method_name(opname, s_pbc, args_s, hop)
        cname = hop.inputconst(ootype.Void, derived_mangled)
        hop.exception_is_here()
        # sanity check: make sure that INSTANCE has the method
        self.r_im_self.setup()
        INSTANCE, meth = self.r_im_self.lowleveltype._lookup(derived_mangled)
        assert meth is not None, 'Missing method %s in class %s'\
               % (derived_mangled, self.r_im_self.lowleveltype)
        v = hop.genop("oosend", [cname]+vlist, resulttype=rresult)
        if hop.r_result is impossible_repr:
            return None      # see test_always_raising_methods
        else:
            return hop.llops.convertvar(v, rresult, hop.r_result)

    def _get_shape_index_callfamily(self, opname, s_pbc, args_s, hop):
        bk = self.rtyper.annotator.bookkeeper
        args = bk.build_args(opname, args_s)
        args = args.prepend(self.s_im_self)
        descs = [desc.funcdesc for desc in s_pbc.descriptions]
        callfamily = descs[0].getcallfamily()
        shape, index = description.FunctionDesc.variant_for_call_site(
                bk, callfamily, descs, args, hop.spaceop)
        return shape, index, callfamily

    def _get_method_name(self, opname, s_pbc, args_s, hop):
        shape, index, callfamily = self._get_shape_index_callfamily(opname, s_pbc, args_s, hop)
        mangled = mangle(self.methodname, self.rtyper.getconfig())
        row = self.concretetable[shape, index]
        derived_mangled = row_method_name(mangled, row.attrname)
        return derived_mangled

class __extend__(pairtype(InstanceRepr, MethodsPBCRepr)):

    def convert_from_to(_, v, llops):
        return v

# ____________________________________________________________

PBCROOT = ootype.Instance('pbcroot', ootype.ROOT)

class MultipleFrozenPBCRepr(AbstractMultipleFrozenPBCRepr):
    """Representation selected for multiple non-callable pre-built constants."""
    def __init__(self, rtyper, access_set):
        self.rtyper = rtyper
        self.access_set = access_set
        self.lowleveltype = ootype.Instance('pbc', PBCROOT, _hints={'immutable': True})
        self.pbc_cache = {}

    def _setup_repr(self):
        fields_list = self._setup_repr_fields()
        ootype.addFields(self.lowleveltype, dict(fields_list))

    def create_instance(self):
        return ootype.new(self.lowleveltype)

    def null_instance(self):
        return ootype.null(self.lowleveltype)

    def getfield(self, vpbc, attr, llops):
        mangled_name, r_value = self.fieldmap[attr]
        cmangledname = inputconst(ootype.Void, mangled_name)
        return llops.genop('oogetfield', [vpbc, cmangledname],
                           resulttype = r_value)

class MultipleUnrelatedFrozenPBCRepr(AbstractMultipleUnrelatedFrozenPBCRepr):
    """Representation selected for multiple non-callable pre-built constants
    with no common access set."""

    lowleveltype = PBCROOT

    def convert_pbc(self, pbc):
        if ootype.typeOf(pbc) != PBCROOT:
            pbc = ootype.ooupcast(PBCROOT, pbc)
        return pbc

    def create_instance(self):
        return ootype.new(PBCROOT)

    def null_instance(self):
        return ootype.null(PBCROOT)

class __extend__(pairtype(MultipleFrozenPBCRepr,
                          MultipleUnrelatedFrozenPBCRepr)):
    def convert_from_to((robj1, robj2), v, llops):
        return llops.genop('ooupcast', [v], resulttype=PBCROOT)
