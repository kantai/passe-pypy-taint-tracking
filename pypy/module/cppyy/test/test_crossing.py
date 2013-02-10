import py, os, sys
from pypy.module.cpyext.test.test_cpyext import AppTestCpythonExtensionBase

currpath = py.path.local(__file__).dirpath()
test_dct = str(currpath.join("crossingDict.so"))

def setup_module(mod):
    if sys.platform == 'win32':
        py.test.skip("win32 not supported so far")
    err = os.system("cd '%s' && make crossingDict.so" % currpath)
    if err:
        raise OSError("'make' failed (see stderr)")


class AppTestCrossing(AppTestCpythonExtensionBase):
    spaceconfig = dict(usemodules=['cpyext', 'cppyy', 'thread', '_rawffi', '_ffi',
                                   'array', 'itertools', 'rctime', 'binascii'])

    def setup_class(cls):
        # following from AppTestCpythonExtensionBase, with cppyy added
        cls.space.getbuiltinmodule("cpyext")
        from pypy.module.imp.importing import importhook
        importhook(cls.space, "os") # warm up reference counts
        from pypy.module.cpyext.pyobject import RefcountState
        state = cls.space.fromcache(RefcountState)
        state.non_heaptypes_w[:] = []

        # cppyy specific additions (not that the test_dct is loaded late
        # to allow the generated extension module be loaded first)
        cls.w_test_dct    = cls.space.wrap(test_dct)
        cls.w_pre_imports = cls.space.appexec([], """():
            import cppyy, ctypes""")    # prevents leak-checking complaints on ctypes
        from pypy.module.imp.importing import get_so_extension
        cls.w_soext = cls.space.wrap(get_so_extension(cls.space))

    def test00_base_class(self):
        """Test from cpyext; only here to see whether the imported class works"""

        import sys
        init = """
        if (Py_IsInitialized())
            Py_InitModule("foo", NULL);
        """
        self.import_module(name='foo', init=init)
        assert 'foo' in sys.modules

    def test01_build_bar_extension(self):
        """Test that builds the needed extension; runs as test to keep it loaded"""

        import os, ctypes

        init = """
        if (Py_IsInitialized())
            Py_InitModule("bar", methods);
        """
        # note: only the symbols are needed for C, none for python
        body = """
        long bar_unwrap(PyObject* arg)
        {
            return PyLong_AsLong(arg);
        }
        PyObject* bar_wrap(long l)
        {
            return PyLong_FromLong(l);
        }
        static PyMethodDef methods[] = {
            { NULL }
        };
        """

        dirname = self.import_module(name='bar', init=init, body=body, load_it=False)
        fullmodname = os.path.join(dirname, 'bar' + self.soext)
        self.cmodule = ctypes.CDLL(fullmodname, ctypes.RTLD_GLOBAL)

    def test02_crossing_dict(self):
        """Test availability of all needed classes in the dict"""

        import cppyy
        cppyy.load_reflection_info(self.test_dct)

        assert cppyy.gbl.crossing == cppyy.gbl.crossing
        crossing = cppyy.gbl.crossing

        assert crossing.A == crossing.A

    def test03_send_pyobject(self):
        """Test sending a true pyobject to C++"""

        import cppyy
        crossing = cppyy.gbl.crossing

        a = crossing.A()
        assert a.unwrap(13) == 13

    def test04_send_and_receive_pyobject(self):
        """Test receiving a true pyobject from C++"""

        import cppyy
        crossing = cppyy.gbl.crossing

        a = crossing.A()

        assert a.wrap(41) == 41
