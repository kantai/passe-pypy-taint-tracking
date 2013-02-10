from pypy.module.cpyext.test.test_api import BaseApiTest
from pypy.module.cpyext.test.test_cpyext import AppTestCpythonExtensionBase
from pypy.interpreter.function import Function, Method

class TestClassObject(BaseApiTest):
    def test_newinstance(self, space, api):
        w_class = space.appexec([], """():
            class C:
                x = None
                def __init__(self, *args, **kwargs):
                    self.x = 1
                    self.args = args
                    self.__dict__.update(kwargs)
            return C
        """)

        assert api.PyClass_Check(w_class)

        w_instance = api.PyInstance_NewRaw(w_class, None)
        assert api.PyInstance_Check(w_instance)
        assert space.getattr(w_instance, space.wrap('x')) is space.w_None

        w_instance = api.PyInstance_NewRaw(w_class, space.wrap(dict(a=3)))
        assert space.getattr(w_instance, space.wrap('x')) is space.w_None
        assert space.unwrap(space.getattr(w_instance, space.wrap('a'))) == 3

        w_instance = api.PyInstance_New(w_class,
                                        space.wrap((3,)), space.wrap(dict(y=2)))
        assert space.unwrap(space.getattr(w_instance, space.wrap('x'))) == 1
        assert space.unwrap(space.getattr(w_instance, space.wrap('y'))) == 2
        assert space.unwrap(space.getattr(w_instance, space.wrap('args'))) == (3,)
        

    def test_lookup(self, space, api):
        w_instance = space.appexec([], """():
            class C:
                def __init__(self):
                    self.x = None
                def f(self): pass
            return C()
        """)

        assert api.PyInstance_Check(w_instance)
        assert api.PyObject_GetAttr(w_instance, space.wrap('x')) is space.w_None
        assert api._PyInstance_Lookup(w_instance, space.wrap('x')) is space.w_None
        assert api._PyInstance_Lookup(w_instance, space.wrap('y')) is None
        assert not api.PyErr_Occurred()

        # getattr returns a bound method
        assert not isinstance(api.PyObject_GetAttr(w_instance, space.wrap('f')), Function)
        # _PyInstance_Lookup returns the raw descriptor
        assert isinstance(api._PyInstance_Lookup(w_instance, space.wrap('f')), Function)

    def test_pyclass_new(self, space, api):
        w_bases = space.newtuple([])
        w_dict = space.newdict()
        w_name = space.wrap("C")
        w_class = api.PyClass_New(w_bases, w_dict, w_name)
        assert not space.isinstance_w(w_class, space.w_type)
        w_instance = space.call_function(w_class)
        assert api.PyInstance_Check(w_instance)
        assert space.is_true(space.call_method(space.builtin, "isinstance",
                                               w_instance, w_class))

class AppTestStringObject(AppTestCpythonExtensionBase):
    def test_class_type(self):
        module = self.import_extension('foo', [
            ("get_classtype", "METH_NOARGS",
             """
                 Py_INCREF(&PyClass_Type);
                 return &PyClass_Type;
             """)])
        class C: pass
        assert module.get_classtype() is type(C)
