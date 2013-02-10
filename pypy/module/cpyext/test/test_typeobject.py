from rpython.rtyper.lltypesystem import rffi, lltype
from pypy.module.cpyext.test.test_cpyext import AppTestCpythonExtensionBase
from pypy.module.cpyext.test.test_api import BaseApiTest
from pypy.module.cpyext.pyobject import PyObject, make_ref, from_ref
from pypy.module.cpyext.typeobject import PyTypeObjectPtr

import py
import sys

class AppTestTypeObject(AppTestCpythonExtensionBase):
    def test_typeobject(self):
        import sys
        module = self.import_module(name='foo')
        assert 'foo' in sys.modules
        assert "copy" in dir(module.fooType)
        obj = module.new()
        print obj.foo
        assert obj.foo == 42
        print "Obj has type", type(obj)
        assert type(obj) is module.fooType
        print "type of obj has type", type(type(obj))
        print "type of type of obj has type", type(type(type(obj)))
        assert module.fooType.__doc__ == "foo is for testing."

    def test_typeobject_method_descriptor(self):
        module = self.import_module(name='foo')
        obj = module.new()
        obj2 = obj.copy()
        assert module.new().name == "Foo Example"
        c = module.fooType.copy
        assert not "im_func" in dir(module.fooType.copy)
        assert module.fooType.copy.__objclass__ is module.fooType
        assert "copy" in repr(module.fooType.copy)
        assert repr(module.fooType) == "<type 'foo.foo'>"
        assert repr(obj2) == "<Foo>"
        assert repr(module.fooType.__call__) == "<slot wrapper '__call__' of 'foo' objects>"
        assert obj2(foo=1, bar=2) == dict(foo=1, bar=2)

        print obj.foo
        assert obj.foo == 42
        assert obj.int_member == obj.foo

    def test_typeobject_data_member(self):
        module = self.import_module(name='foo')
        obj = module.new()
        obj.int_member = 23
        assert obj.int_member == 23
        obj.int_member = 42
        raises(TypeError, "obj.int_member = 'not a number'")
        raises(TypeError, "del obj.int_member")
        raises(TypeError, "obj.int_member_readonly = 42")
        exc = raises(TypeError, "del obj.int_member_readonly")
        assert "readonly" in str(exc.value)
        raises(SystemError, "obj.broken_member")
        raises(SystemError, "obj.broken_member = 42")
        assert module.fooType.broken_member.__doc__ is None
        assert module.fooType.object_member.__doc__ == "A Python object."

    def test_typeobject_object_member(self):
        module = self.import_module(name='foo')
        obj = module.new()
        assert obj.object_member is None
        obj.object_member = "hello"
        assert obj.object_member == "hello"
        del obj.object_member
        del obj.object_member
        assert obj.object_member is None
        raises(AttributeError, "obj.object_member_ex")
        obj.object_member_ex = None
        assert obj.object_member_ex is None
        obj.object_member_ex = 42
        assert obj.object_member_ex == 42
        del obj.object_member_ex
        raises(AttributeError, "del obj.object_member_ex")

        obj.set_foo = 32
        assert obj.foo == 32

    def test_typeobject_string_member(self):
        module = self.import_module(name='foo')
        obj = module.new()
        assert obj.string_member == "Hello from PyPy"
        raises(TypeError, "obj.string_member = 42")
        raises(TypeError, "del obj.string_member")
        obj.unset_string_member()
        assert obj.string_member is None
        assert obj.string_member_inplace == "spam"
        raises(TypeError, "obj.string_member_inplace = 42")
        raises(TypeError, "del obj.string_member_inplace")
        assert obj.char_member == "s"
        obj.char_member = "a"
        assert obj.char_member == "a"
        raises(TypeError, "obj.char_member = 'spam'")
        raises(TypeError, "obj.char_member = 42")
        #
        import sys
        bignum = sys.maxint - 42
        obj.short_member = -12345;     assert obj.short_member == -12345
        obj.long_member = -bignum;     assert obj.long_member == -bignum
        obj.ushort_member = 45678;     assert obj.ushort_member == 45678
        obj.uint_member = 3000000000;  assert obj.uint_member == 3000000000
        obj.ulong_member = 2*bignum;   assert obj.ulong_member == 2*bignum
        obj.byte_member = -99;         assert obj.byte_member == -99
        obj.ubyte_member = 199;        assert obj.ubyte_member == 199
        obj.bool_member = True;        assert obj.bool_member is True
        obj.float_member = 9.25;       assert obj.float_member == 9.25
        obj.double_member = 9.25;      assert obj.double_member == 9.25
        obj.longlong_member = -2**59;  assert obj.longlong_member == -2**59
        obj.ulonglong_member = 2**63;  assert obj.ulonglong_member == 2**63
        obj.ssizet_member = sys.maxint;assert obj.ssizet_member == sys.maxint
        #

    def test_staticmethod(self):
        module = self.import_module(name="foo")
        obj = module.fooType.create()
        assert obj.foo == 42
        obj2 = obj.create()
        assert obj2.foo == 42

    def test_classmethod(self):
        module = self.import_module(name="foo")
        obj = module.fooType.classmeth()
        assert obj is module.fooType

    def test_new(self):
        module = self.import_module(name='foo')
        obj = module.new()
        # call __new__
        newobj = module.UnicodeSubtype(u"xyz")
        assert newobj == u"xyz"
        assert isinstance(newobj, module.UnicodeSubtype)

        assert isinstance(module.fooType(), module.fooType)
        class bar(module.fooType):
            pass
        assert isinstance(bar(), bar)

        fuu = module.UnicodeSubtype
        class fuu2(fuu):
            def baz(self):
                return self
        assert fuu2(u"abc").baz().escape()
        raises(TypeError, module.fooType.object_member.__get__, 1)

    def test_init(self):
        module = self.import_module(name="foo")
        newobj = module.UnicodeSubtype()
        assert newobj.get_val() == 42

        # this subtype should inherit tp_init
        newobj = module.UnicodeSubtype2()
        assert newobj.get_val() == 42

        # this subclass redefines __init__
        class UnicodeSubclass2(module.UnicodeSubtype):
            def __init__(self):
                self.foobar = 32
                super(UnicodeSubclass2, self).__init__()
        
        newobj = UnicodeSubclass2()
        assert newobj.get_val() == 42
        assert newobj.foobar == 32

    def test_metatype(self):
        module = self.import_module(name='foo')
        assert module.MetaType.__mro__ == (module.MetaType, type, object)
        x = module.MetaType('name', (), {})
        assert isinstance(x, type)
        assert isinstance(x, module.MetaType)
        x()

    def test_metaclass_compatible(self):
        # metaclasses should not conflict here
        module = self.import_module(name='foo')
        assert module.MetaType.__mro__ == (module.MetaType, type, object)
        assert type(module.fooType).__mro__ == (type, object)
        y = module.MetaType('other', (module.fooType,), {})
        assert isinstance(y, module.MetaType)
        x = y()
        del x, y

    def test_sre(self):
        module = self.import_module(name='_sre')
        import sre_compile
        sre_compile._sre = module
        assert sre_compile.MAGIC == module.MAGIC
        import re
        import time
        s = u"Foo " * 1000 + u"Bar"
        prog = re.compile(ur"Foo.*Bar")
        assert prog.match(s)
        m = re.search(u"xyz", u"xyzxyz")
        assert m
        m = re.search("xyz", "xyzxyz")
        assert m
        assert "groupdict" in dir(m)
        re._cache.clear()
        re._cache_repl.clear()
        del prog, m

    def test_init_error(self):
        module = self.import_module("foo")
        raises(ValueError, module.InitErrType)

    def test_cmps(self):
        module = self.import_module("comparisons")
        cmpr = module.CmpType()
        assert cmpr == 3
        assert cmpr != 42

    def test_richcompare(self):
        module = self.import_module("comparisons")
        cmpr = module.CmpType()

        # should not crash
        cmpr < 4
        cmpr <= 4
        cmpr > 4
        cmpr >= 4

        assert cmpr.__le__(4) is NotImplemented

    def test_tpcompare(self):
        module = self.import_module("comparisons")
        cmpr = module.OldCmpType()
        assert cmpr < cmpr

    def test_hash(self):
        module = self.import_module("comparisons")
        cmpr = module.CmpType()
        assert hash(cmpr) == 3
        d = {}
        d[cmpr] = 72
        assert d[cmpr] == 72
        assert d[3] == 72

    def test_descriptor(self):
        module = self.import_module("foo")
        prop = module.Property()
        class C(object):
            x = prop
        obj = C()
        assert obj.x == (prop, obj, C)
        assert C.x == (prop, None, C)

        obj.x = 2
        assert obj.y == (prop, 2)
        del obj.x
        assert obj.z == prop

    def test_tp_dict(self):
        foo = self.import_module("foo")
        module = self.import_extension('test', [
           ("read_tp_dict", "METH_O",
            '''
                 PyObject *method;
                 if (!args->ob_type->tp_dict)
                 {
                     PyErr_SetNone(PyExc_ValueError);
                     return NULL;
                 }
                 method = PyDict_GetItemString(
                     args->ob_type->tp_dict, "copy");
                 Py_INCREF(method);
                 return method;
             '''
             )
            ])
        obj = foo.new()
        assert module.read_tp_dict(obj) == foo.fooType.copy

    def test_custom_allocation(self):
        foo = self.import_module("foo")
        obj = foo.newCustom()
        assert type(obj) is foo.Custom
        assert type(foo.Custom) is foo.MetaType

    def test_heaptype(self):
        module = self.import_extension('foo', [
           ("name_by_heaptype", "METH_O",
            '''
                 PyHeapTypeObject *heaptype = (PyHeapTypeObject *)args;
                 Py_INCREF(heaptype->ht_name);
                 return heaptype->ht_name;
             '''
             )
            ])
        class C(object):
            pass
        assert module.name_by_heaptype(C) == "C"
        

class TestTypes(BaseApiTest):
    def test_type_attributes(self, space, api):
        w_class = space.appexec([], """():
            class A(object):
                pass
            return A
            """)
        ref = make_ref(space, w_class)

        py_type = rffi.cast(PyTypeObjectPtr, ref)
        assert py_type.c_tp_alloc
        assert from_ref(space, py_type.c_tp_mro).wrappeditems is w_class.mro_w

        api.Py_DecRef(ref)

    def test_multiple_inheritance(self, space, api):
        w_class = space.appexec([], """():
            class A(object):
                pass
            class B(object):
                pass
            class C(A, B):
                pass
            return C
            """)
        ref = make_ref(space, w_class)
        api.Py_DecRef(ref)

    def test_lookup(self, space, api):
        w_type = space.w_str
        w_obj = api._PyType_Lookup(w_type, space.wrap("upper"))
        assert space.is_w(w_obj, space.w_str.getdictvalue(space, "upper"))

        w_obj = api._PyType_Lookup(w_type, space.wrap("__invalid"))
        assert w_obj is None
        assert api.PyErr_Occurred() is None
    
class AppTestSlots(AppTestCpythonExtensionBase):
    def test_some_slots(self):
        module = self.import_extension('foo', [
            ("test_type", "METH_O",
             '''
                 if (!args->ob_type->tp_setattro)
                 {
                     PyErr_SetString(PyExc_ValueError, "missing tp_setattro");
                     return NULL;
                 }
                 if (args->ob_type->tp_setattro ==
                     args->ob_type->tp_base->tp_setattro)
                 {
                     PyErr_SetString(PyExc_ValueError, "recursive tp_setattro");
                     return NULL;
                 }
                 Py_RETURN_TRUE;
             '''
             )
            ])
        assert module.test_type(type(None))

    def test_nb_int(self):
        module = self.import_extension('foo', [
            ("nb_int", "METH_O",
             '''
                 if (!args->ob_type->tp_as_number ||
                     !args->ob_type->tp_as_number->nb_int)
                 {
                     PyErr_SetNone(PyExc_ValueError);
                     return NULL;
                 }
                 return args->ob_type->tp_as_number->nb_int(args);
             '''
             )
            ])
        assert module.nb_int(10) == 10
        assert module.nb_int(-12.3) == -12
        raises(ValueError, module.nb_int, "123")

    def test_tp_call(self):
        module = self.import_extension('foo', [
            ("tp_call", "METH_VARARGS",
             '''
                 PyObject *obj = PyTuple_GET_ITEM(args, 0);
                 PyObject *c_args = PyTuple_GET_ITEM(args, 1);
                 if (!obj->ob_type->tp_call)
                 {
                     PyErr_SetNone(PyExc_ValueError);
                     return NULL;
                 }
                 return obj->ob_type->tp_call(obj, c_args, NULL);
             '''
             )
            ])
        class C:
            def __call__(self, *args):
                return args
        assert module.tp_call(C(), ('x', 2)) == ('x', 2)

    def test_tp_str(self):
        module = self.import_extension('foo', [
           ("tp_str", "METH_O",
            '''
                 if (!args->ob_type->tp_str)
                 {
                     PyErr_SetNone(PyExc_ValueError);
                     return NULL;
                 }
                 return args->ob_type->tp_str(args);
             '''
             )
            ])
        class C:
            def __str__(self):
                return "text"
        assert module.tp_str(C()) == "text"

    def test_mp_ass_subscript(self):
        module = self.import_extension('foo', [
           ("new_obj", "METH_NOARGS",
            '''
                PyObject *obj;
                Foo_Type.tp_as_mapping = &tp_as_mapping;
                tp_as_mapping.mp_ass_subscript = mp_ass_subscript;
                if (PyType_Ready(&Foo_Type) < 0) return NULL;
                obj = PyObject_New(PyObject, &Foo_Type);
                return obj;
            '''
            )],
            '''
            static int
            mp_ass_subscript(PyObject *self, PyObject *key, PyObject *value)
            {
                if (PyInt_Check(key)) {
                    PyErr_SetNone(PyExc_ZeroDivisionError);
                    return -1;
                }
                return 0;
            }
            PyMappingMethods tp_as_mapping;
            static PyTypeObject Foo_Type = {
                PyVarObject_HEAD_INIT(NULL, 0)
                "foo.foo",
            };
            ''')
        obj = module.new_obj()
        raises(ZeroDivisionError, obj.__setitem__, 5, None)
        res = obj.__setitem__('foo', None)
        assert res is None

    def test_sq_contains(self):
        module = self.import_extension('foo', [
           ("new_obj", "METH_NOARGS",
            '''
                PyObject *obj;
                Foo_Type.tp_as_sequence = &tp_as_sequence;
                tp_as_sequence.sq_contains = sq_contains;
                if (PyType_Ready(&Foo_Type) < 0) return NULL;
                obj = PyObject_New(PyObject, &Foo_Type);
                return obj;
            '''
            )],
            '''
            static int
            sq_contains(PyObject *self, PyObject *value)
            {
                return 42;
            }
            PySequenceMethods tp_as_sequence;
            static PyTypeObject Foo_Type = {
                PyVarObject_HEAD_INIT(NULL, 0)
                "foo.foo",
            };
            ''')
        obj = module.new_obj()
        res = "foo" in obj
        assert res is True

    def test_tp_iter(self):
        module = self.import_extension('foo', [
           ("tp_iter", "METH_O",
            '''
                 if (!args->ob_type->tp_iter)
                 {
                     PyErr_SetNone(PyExc_ValueError);
                     return NULL;
                 }
                 return args->ob_type->tp_iter(args);
             '''
             ),
           ("tp_iternext", "METH_O",
            '''
                 if (!args->ob_type->tp_iternext)
                 {
                     PyErr_SetNone(PyExc_ValueError);
                     return NULL;
                 }
                 return args->ob_type->tp_iternext(args);
             '''
             )
            ])
        l = [1]
        it = module.tp_iter(l)
        assert type(it) is type(iter([]))
        assert module.tp_iternext(it) == 1
        raises(StopIteration, module.tp_iternext, it)
        
    def test_bool(self):
        module = self.import_extension('foo', [
            ("newInt", "METH_VARARGS",
             """
                IntLikeObject *intObj;
                long intval;
                PyObject *name;

                if (!PyArg_ParseTuple(args, "i", &intval))
                    return NULL;

                IntLike_Type.tp_as_number = &intlike_as_number;
                intlike_as_number.nb_nonzero = intlike_nb_nonzero;
                if (PyType_Ready(&IntLike_Type) < 0) return NULL;
                intObj = PyObject_New(IntLikeObject, &IntLike_Type);
                if (!intObj) {
                    return NULL;
                }

                intObj->value = intval;
                return (PyObject *)intObj;
             """)],
            """
            typedef struct
            {
                PyObject_HEAD
                int value;
            } IntLikeObject;

            static int
            intlike_nb_nonzero(IntLikeObject *v)
            {
                if (v->value == -42) {
                    PyErr_SetNone(PyExc_ValueError);
                    return -1;
                }
                return v->value;
            }

            PyTypeObject IntLike_Type = {
                PyObject_HEAD_INIT(0)
                /*ob_size*/             0,
                /*tp_name*/             "IntLike",
                /*tp_basicsize*/        sizeof(IntLikeObject),
            };
            static PyNumberMethods intlike_as_number;
            """)
        assert not bool(module.newInt(0))
        assert bool(module.newInt(1))
        assert bool(module.newInt(-1))
        raises(ValueError, bool, module.newInt(-42))
