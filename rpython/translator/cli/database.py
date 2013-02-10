import operator
import string
from rpython.translator.cli.function import Function, log
from rpython.translator.cli.class_ import Class
from rpython.translator.cli.record import Record
from rpython.translator.cli.delegate import Delegate
from rpython.translator.cli.comparer import EqualityComparer
from rpython.translator.cli.node import Node
from rpython.translator.cli.support import string_literal, Counter
from rpython.translator.cli.cts import types
from rpython.rtyper.ootypesystem import ootype
from rpython.rtyper.ootypesystem.module import ll_os, ll_math
from rpython.rtyper.ootypesystem.rtupletype import TUPLE_TYPE
from rpython.translator.cli import dotnet
from rpython.rlib.objectmodel import CDefinedIntSymbolic
from rpython.translator.oosupport.database import Database as OODatabase

try:
    set
except NameError:
    from sets import Set as set

BUILTIN_RECORDS = {
    TUPLE_TYPE([ootype.Signed, ootype.Signed]):
        '[pypylib]pypy.runtime.Record_Signed_Signed',
    TUPLE_TYPE([ootype.String, ootype.String]): 
        '[pypylib]pypy.runtime.Record_String_String',

    ll_math.FREXP_RESULT: '[pypylib]pypy.runtime.Record_Float_Signed',    
    ll_math.MODF_RESULT: '[pypylib]pypy.runtime.Record_Float_Float',
    ll_os.STAT_RESULT: '[pypylib]pypy.runtime.Record_Stat_Result',
    }

class LowLevelDatabase(OODatabase):
    def __init__(self, genoo):
        OODatabase.__init__(self, genoo)
        self.classes = {} # INSTANCE --> class_name
        self.classnames = set() # (namespace, name)
        self.recordnames = {} # RECORD --> name
        self.functions = {} # graph --> function_name
        self.methods = {} # graph --> method_name
        self.consts = {}  # value --> AbstractConst
        self.delegates = {} # StaticMethod --> type_name
        self.const_count = Counter() # store statistics about constants

    def next_count(self):
        return self.unique()

    def _default_record_name(self, RECORD):
        trans = string.maketrans('[]<>(), :', '_________')
        name = ['Record']
        # XXX: refactor this: we need a proper way to ensure unique names
        for f_name, (FIELD_TYPE, f_default) in RECORD._fields.iteritems():
            type_name = FIELD_TYPE._short_name().translate(trans)
            name.append(f_name)
            name.append(type_name)
            
        return '__'.join(name)

    def _default_class_name(self, INSTANCE):
        parts = INSTANCE._name.rsplit('.', 1)
        if len(parts) == 2:
            return parts
        else:
            return None, parts[0]

    def pending_function(self, graph, functype=None):
        if functype is None:
            function = self.genoo.Function(self, graph)
        else:
            function = functype(self, graph)
        self.pending_node(function)
        return function.get_name()

    def pending_class(self, INSTANCE):
        try:
            return self.classes[INSTANCE]
        except KeyError:
            pass
        
        if isinstance(INSTANCE, dotnet.NativeInstance):
            self.classes[INSTANCE] = INSTANCE._name
            return INSTANCE._name
        else:
            namespace, name = self._default_class_name(INSTANCE)
            name = self.get_unique_class_name(namespace, name)
            if namespace is None:
                full_name = name
            else:
                full_name = '%s.%s' % (namespace, name)
            self.classes[INSTANCE] = full_name
            cls = Class(self, INSTANCE, namespace, name)
            self.pending_node(cls)
            return full_name

    def pending_record(self, RECORD):
        try:
            return BUILTIN_RECORDS[RECORD]
        except KeyError:
            pass
        try:
            return self.recordnames[RECORD]
        except KeyError:
            pass
        name = self._default_record_name(RECORD)
        name = self.get_unique_class_name(None, name)
        self.recordnames[RECORD] = name
        r = Record(self, RECORD, name)
        self.pending_node(r)
        return name

    def record_function(self, graph, name):
        self.functions[graph] = name

    def graph_name(self, graph):
        # XXX: graph name are not guaranteed to be unique
        return self.functions.get(graph, None)

    def get_unique_class_name(self, namespace, name):
        base_name = name
        i = 0
        while (namespace, name) in self.classnames:
            name = '%s_%d' % (base_name, i)
            i+= 1
        self.classnames.add((namespace, name))            
        return name

    def class_or_record_name(self, TYPE):
        if TYPE is not ootype.ROOT and isinstance(TYPE, ootype.Instance):
            return self.class_name(TYPE)
        elif isinstance(TYPE, ootype.Record):
            return self.get_record_name(TYPE)
        elif isinstance(TYPE, ootype.OOType):
            return self.cts.lltype_to_cts(TYPE)
        else:
            assert False

    def class_name(self, INSTANCE):
        if INSTANCE is ootype.ROOT:
            return types.object.classname()
        try:
            NATIVE_INSTANCE = INSTANCE._hints['NATIVE_INSTANCE']
            return NATIVE_INSTANCE._name
        except KeyError:
            return self.classes[INSTANCE]

    def get_record_name(self, RECORD):
        try:
            return BUILTIN_RECORDS[RECORD]
        except KeyError:
            return self.recordnames[RECORD]

    def record_delegate(self, TYPE):
        try:
            return self.delegates[TYPE]
        except KeyError:
            name = 'StaticMethod__%d' % len(self.delegates)
            self.delegates[TYPE] = name
            self.pending_node(Delegate(self, TYPE, name))
            return name
