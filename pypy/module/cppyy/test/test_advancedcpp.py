import py, os, sys

from pypy.module.cppyy import capi


currpath = py.path.local(__file__).dirpath()
test_dct = str(currpath.join("advancedcppDict.so"))

def setup_module(mod):
    if sys.platform == 'win32':
        py.test.skip("win32 not supported so far")
    for refl_dict in ["advancedcppDict.so", "advancedcpp2Dict.so"]:
        err = os.system("cd '%s' && make %s" % (currpath, refl_dict))
        if err:
            raise OSError("'make' failed (see stderr)")

class AppTestADVANCEDCPP:
    spaceconfig = dict(usemodules=['cppyy', 'array'])

    def setup_class(cls):
        cls.w_test_dct = cls.space.wrap(test_dct)
        cls.w_capi_identity = cls.space.wrap(capi.identify())
        cls.w_advanced = cls.space.appexec([], """():
            import cppyy
            return cppyy.load_reflection_info(%r)""" % (test_dct, ))

    def test01_default_arguments(self):
        """Test usage of default arguments"""

        import cppyy
        def test_defaulter(n, t):
            defaulter = getattr(cppyy.gbl, '%s_defaulter' % n)

            d = defaulter()
            assert d.m_a == t(11)
            assert d.m_b == t(22)
            assert d.m_c == t(33)
            d.destruct()

            d = defaulter(0)
            assert d.m_a ==  t(0)
            assert d.m_b == t(22)
            assert d.m_c == t(33)
            d.destruct()

            d = defaulter(1, 2)
            assert d.m_a ==  t(1)
            assert d.m_b ==  t(2)
            assert d.m_c == t(33)
            d.destruct()

            d = defaulter(3, 4, 5)
            assert d.m_a ==  t(3)
            assert d.m_b ==  t(4)
            assert d.m_c ==  t(5)
            d.destruct()
        test_defaulter('short', int)
        test_defaulter('ushort', int)
        test_defaulter('int', int)
        test_defaulter('uint', int)
        test_defaulter('long', long)
        test_defaulter('ulong', long)
        test_defaulter('llong', long)
        test_defaulter('ullong', long)
        test_defaulter('float', float)
        test_defaulter('double', float)

    def test02_simple_inheritance(self):
        """Test binding of a basic inheritance structure"""

        import cppyy
        base_class    = cppyy.gbl.base_class
        derived_class = cppyy.gbl.derived_class

        assert issubclass(derived_class, base_class)
        assert not issubclass(base_class, derived_class)

        b = base_class()
        assert isinstance(b, base_class)
        assert not isinstance(b, derived_class)

        assert b.m_b              == 1
        assert b.get_value()      == 1
        assert b.m_db             == 1.1
        assert b.get_base_value() == 1.1

        b.m_b, b.m_db = 11, 11.11
        assert b.m_b              == 11
        assert b.get_value()      == 11
        assert b.m_db             == 11.11
        assert b.get_base_value() == 11.11

        b.destruct()

        d = derived_class()
        assert isinstance(d, derived_class)
        assert isinstance(d, base_class)

        assert d.m_d                 == 2
        assert d.get_value()         == 2
        assert d.m_dd                == 2.2
        assert d.get_derived_value() == 2.2

        assert d.m_b                 == 1
        assert d.m_db                == 1.1
        assert d.get_base_value()    == 1.1

        d.m_b, d.m_db = 11, 11.11
        d.m_d, d.m_dd = 22, 22.22

        assert d.m_d                 == 22
        assert d.get_value()         == 22
        assert d.m_dd                == 22.22
        assert d.get_derived_value() == 22.22

        assert d.m_b                 == 11
        assert d.m_db                == 11.11
        assert d.get_base_value()    == 11.11

        d.destruct()

    def test03_namespaces(self):
        """Test access to namespaces and inner classes"""

        import cppyy
        gbl = cppyy.gbl

        assert gbl.a_ns      is gbl.a_ns
        assert gbl.a_ns.d_ns is gbl.a_ns.d_ns

        assert gbl.a_ns.b_class              is gbl.a_ns.b_class
        assert gbl.a_ns.b_class.c_class      is gbl.a_ns.b_class.c_class
        assert gbl.a_ns.d_ns.e_class         is gbl.a_ns.d_ns.e_class
        assert gbl.a_ns.d_ns.e_class.f_class is gbl.a_ns.d_ns.e_class.f_class

        assert gbl.a_ns.g_a                           == 11
        assert gbl.a_ns.get_g_a()                     == 11
        assert gbl.a_ns.b_class.s_b                   == 22
        assert gbl.a_ns.b_class().m_b                 == -2
        assert gbl.a_ns.b_class.c_class.s_c           == 33
        assert gbl.a_ns.b_class.c_class().m_c         == -3
        assert gbl.a_ns.d_ns.g_d                      == 44
        assert gbl.a_ns.d_ns.get_g_d()                == 44
        assert gbl.a_ns.d_ns.e_class.s_e              == 55
        assert gbl.a_ns.d_ns.e_class().m_e            == -5
        assert gbl.a_ns.d_ns.e_class.f_class.s_f      == 66
        assert gbl.a_ns.d_ns.e_class.f_class().m_f    == -6

    def test03a_namespace_lookup_on_update(self):
        """Test whether namespaces can be shared across dictionaries."""

        import cppyy
        gbl = cppyy.gbl

        lib2 = cppyy.load_reflection_info("advancedcpp2Dict.so")

        assert gbl.a_ns      is gbl.a_ns
        assert gbl.a_ns.d_ns is gbl.a_ns.d_ns

        assert gbl.a_ns.g_class              is gbl.a_ns.g_class
        assert gbl.a_ns.g_class.h_class      is gbl.a_ns.g_class.h_class
        assert gbl.a_ns.d_ns.i_class         is gbl.a_ns.d_ns.i_class
        assert gbl.a_ns.d_ns.i_class.j_class is gbl.a_ns.d_ns.i_class.j_class

        assert gbl.a_ns.g_g                           ==  77
        assert gbl.a_ns.get_g_g()                     ==  77
        assert gbl.a_ns.g_class.s_g                   ==  88
        assert gbl.a_ns.g_class().m_g                 ==  -7
        assert gbl.a_ns.g_class.h_class.s_h           ==  99
        assert gbl.a_ns.g_class.h_class().m_h         ==  -8
        assert gbl.a_ns.d_ns.g_i                      == 111
        assert gbl.a_ns.d_ns.get_g_i()                == 111
        assert gbl.a_ns.d_ns.i_class.s_i              == 222
        assert gbl.a_ns.d_ns.i_class().m_i            ==  -9
        assert gbl.a_ns.d_ns.i_class.j_class.s_j      == 333
        assert gbl.a_ns.d_ns.i_class.j_class().m_j    == -10

    def test04_template_types(self):
        """Test bindings of templated types"""

        import cppyy
        gbl = cppyy.gbl

        assert gbl.T1 is gbl.T1
        assert gbl.T2 is gbl.T2
        assert gbl.T3 is gbl.T3
        assert not gbl.T1 is gbl.T2
        assert not gbl.T2 is gbl.T3

        assert gbl.T1('int') is gbl.T1('int')
        assert gbl.T1(int)   is gbl.T1('int')
        assert gbl.T2('T1<int>')     is gbl.T2('T1<int>')
        assert gbl.T2(gbl.T1('int')) is gbl.T2('T1<int>')
        assert gbl.T2(gbl.T1(int)) is gbl.T2('T1<int>')
        assert gbl.T3('int,double')    is gbl.T3('int,double')
        assert gbl.T3('int', 'double') is gbl.T3('int,double')
        assert gbl.T3(int, 'double')   is gbl.T3('int,double')
        assert gbl.T3('T1<int>,T2<T1<int> >') is gbl.T3('T1<int>,T2<T1<int> >')
        assert gbl.T3('T1<int>', gbl.T2(gbl.T1(int))) is gbl.T3('T1<int>,T2<T1<int> >')

        assert gbl.a_ns.T4(int) is gbl.a_ns.T4('int')
        assert gbl.a_ns.T4('a_ns::T4<T3<int,double> >')\
               is gbl.a_ns.T4(gbl.a_ns.T4(gbl.T3(int, 'double')))

        #-----
        t1 = gbl.T1(int)()
        assert t1.m_t1    == 1
        assert t1.value() == 1
        t1.destruct()

        #-----
        t1 = gbl.T1(int)(11)
        assert t1.m_t1    == 11
        assert t1.value() == 11
        t1.m_t1 = 111
        assert t1.value() == 111
        assert t1.m_t1    == 111
        t1.destruct()

        #-----
        t2 = gbl.T2(gbl.T1(int))(gbl.T1(int)(32))
        t2.m_t2.m_t1 = 32
        assert t2.m_t2.value() == 32
        assert t2.m_t2.m_t1    == 32
        t2.destruct()

    def test05_abstract_classes(self):
        """Test non-instatiatability of abstract classes"""

        import cppyy
        gbl = cppyy.gbl

        raises(TypeError, gbl.a_class)
        raises(TypeError, gbl.some_abstract_class)

        assert issubclass(gbl.some_concrete_class, gbl.some_abstract_class)

        c = gbl.some_concrete_class()
        assert isinstance(c, gbl.some_concrete_class)
        assert isinstance(c, gbl.some_abstract_class)

    def test06_datamembers(self):
        """Test data member access when using virtual inheritence"""

        import cppyy
        a_class   = cppyy.gbl.a_class
        b_class   = cppyy.gbl.b_class
        c_class_1 = cppyy.gbl.c_class_1
        c_class_2 = cppyy.gbl.c_class_2
        d_class   = cppyy.gbl.d_class

        assert issubclass(b_class, a_class)
        assert issubclass(c_class_1, a_class)
        assert issubclass(c_class_1, b_class)
        assert issubclass(c_class_2, a_class)
        assert issubclass(c_class_2, b_class)
        assert issubclass(d_class, a_class)
        assert issubclass(d_class, b_class)
        assert issubclass(d_class, c_class_2)

        #-----
        b = b_class()
        assert b.m_a          == 1
        assert b.m_da         == 1.1
        assert b.m_b          == 2
        assert b.m_db         == 2.2

        b.m_a = 11
        assert b.m_a          == 11
        assert b.m_b          == 2

        b.m_da = 11.11
        assert b.m_da         == 11.11
        assert b.m_db         == 2.2

        b.m_b = 22
        assert b.m_a          == 11
        assert b.m_da         == 11.11
        assert b.m_b          == 22
        assert b.get_value()  == 22

        b.m_db = 22.22
        assert b.m_db         == 22.22

        b.destruct()

        #-----
        c1 = c_class_1()
        assert c1.m_a         == 1
        assert c1.m_b         == 2
        assert c1.m_c         == 3

        c1.m_a = 11
        assert c1.m_a         == 11

        c1.m_b = 22
        assert c1.m_a         == 11
        assert c1.m_b         == 22

        c1.m_c = 33
        assert c1.m_a         == 11
        assert c1.m_b         == 22
        assert c1.m_c         == 33
        assert c1.get_value() == 33

        c1.destruct()

        #-----
        d = d_class()
        assert d.m_a          == 1
        assert d.m_b          == 2
        assert d.m_c          == 3
        assert d.m_d          == 4

        d.m_a = 11
        assert d.m_a          == 11

        d.m_b = 22
        assert d.m_a          == 11
        assert d.m_b          == 22

        d.m_c = 33
        assert d.m_a          == 11
        assert d.m_b          == 22
        assert d.m_c          == 33

        d.m_d = 44
        assert d.m_a          == 11
        assert d.m_b          == 22
        assert d.m_c          == 33
        assert d.m_d          == 44
        assert d.get_value()  == 44

        d.destruct()

    def test07_pass_by_reference(self):
        """Test reference passing when using virtual inheritance"""

        import cppyy
        gbl = cppyy.gbl
        b_class = gbl.b_class
        c_class = gbl.c_class_2
        d_class = gbl.d_class

        #-----
        b = b_class()
        b.m_a, b.m_b = 11, 22
        assert gbl.get_a(b) == 11
        assert gbl.get_b(b) == 22
        b.destruct()

        #-----
        c = c_class()
        c.m_a, c.m_b, c.m_c = 11, 22, 33
        assert gbl.get_a(c) == 11
        assert gbl.get_b(c) == 22
        assert gbl.get_c(c) == 33
        c.destruct()

        #-----
        d = d_class()
        d.m_a, d.m_b, d.m_c, d.m_d = 11, 22, 33, 44
        assert gbl.get_a(d) == 11
        assert gbl.get_b(d) == 22
        assert gbl.get_c(d) == 33
        assert gbl.get_d(d) == 44
        d.destruct()

    def test08_void_pointer_passing(self):
        """Test passing of variants of void pointer arguments"""

        import cppyy
        pointer_pass        = cppyy.gbl.pointer_pass
        some_concrete_class = cppyy.gbl.some_concrete_class

        pp = pointer_pass()
        o = some_concrete_class()

        assert cppyy.addressof(o) == pp.gime_address_ptr(o)
        assert cppyy.addressof(o) == pp.gime_address_ptr_ptr(o)
        assert cppyy.addressof(o) == pp.gime_address_ptr_ref(o)

        import array
        addressofo = array.array('l', [cppyy.addressof(o)])
        assert addressofo.buffer_info()[0] == pp.gime_address_ptr_ptr(addressofo)

        assert 0 == pp.gime_address_ptr(0)
        assert 0 == pp.gime_address_ptr(None)

        ptr = cppyy.bind_object(0, some_concrete_class)
        assert cppyy.addressof(ptr) == 0
        pp.set_address_ptr_ref(ptr)
        assert cppyy.addressof(ptr) == 0x1234
        pp.set_address_ptr_ptr(ptr)
        assert cppyy.addressof(ptr) == 0x4321

    def test09_opaque_pointer_passing(self):
        """Test passing around of opaque pointers"""

        import cppyy
        some_concrete_class = cppyy.gbl.some_concrete_class

        o = some_concrete_class()

        #cobj = cppyy.as_cobject(o)
        addr = cppyy.addressof(o)

        #assert o == cppyy.bind_object(cobj, some_concrete_class)
        #assert o == cppyy.bind_object(cobj, type(o))
        #assert o == cppyy.bind_object(cobj, o.__class__)
        #assert o == cppyy.bind_object(cobj, "some_concrete_class")
        assert cppyy.addressof(o) == cppyy.addressof(cppyy.bind_object(addr, some_concrete_class))
        assert o == cppyy.bind_object(addr, some_concrete_class)
        assert o == cppyy.bind_object(addr, type(o))
        assert o == cppyy.bind_object(addr, o.__class__)
        #assert o == cppyy.bind_object(addr, "some_concrete_class")

    def test10_object_identity(self):
        """Test object identity"""

        import cppyy
        some_concrete_class  = cppyy.gbl.some_concrete_class
        some_class_with_data = cppyy.gbl.some_class_with_data

        o = some_concrete_class()
        addr = cppyy.addressof(o)

        o2 = cppyy.bind_object(addr, some_concrete_class)
        assert o is o2

        o3 = cppyy.bind_object(addr, some_class_with_data)
        assert not o is o3

        d1 = some_class_with_data()
        d2 = d1.gime_copy()
        assert not d1 is d2

        dd1a = d1.gime_data()
        dd1b = d1.gime_data()
        assert dd1a is dd1b

        dd2 = d2.gime_data()
        assert not dd1a is dd2
        assert not dd1b is dd2

        d2.destruct()
        d1.destruct()

    def test11_multi_methods(self):
        """Test calling of methods from multiple inheritance"""

        import cppyy
        multi = cppyy.gbl.multi

        assert cppyy.gbl.multi1 is multi.__bases__[0]
        assert cppyy.gbl.multi2 is multi.__bases__[1]

        dict_keys = multi.__dict__.keys()
        assert dict_keys.count('get_my_own_int') == 1
        assert dict_keys.count('get_multi1_int') == 0
        assert dict_keys.count('get_multi2_int') == 0

        m = multi(1, 2, 3)
        assert m.get_multi1_int() == 1
        assert m.get_multi2_int() == 2
        assert m.get_my_own_int() == 3

    def test12_actual_type(self):
        """Test that a pointer to base return does an auto-downcast"""

        import cppyy
        base_class = cppyy.gbl.base_class
        derived_class = cppyy.gbl.derived_class

        b = base_class()
        d = derived_class()

        assert b == b.cycle(b)
        assert id(b) == id(b.cycle(b))
        assert b == d.cycle(b)
        assert id(b) == id(d.cycle(b))
        assert d == b.cycle(d)
        assert id(d) == id(b.cycle(d))
        assert d == d.cycle(d)
        assert id(d) == id(d.cycle(d))

        assert isinstance(b.cycle(b), base_class)
        assert isinstance(d.cycle(b), base_class)
        assert isinstance(b.cycle(d), derived_class)
        assert isinstance(d.cycle(d), derived_class)

        assert isinstance(b.clone(), base_class)      # TODO: clone() leaks
        assert isinstance(d.clone(), derived_class)   # TODO: clone() leaks

    def test13_actual_type_virtual_multi(self):
        """Test auto-downcast in adverse inheritance situation"""

        import cppyy

        c1 = cppyy.gbl.create_c1()
        assert type(c1) == cppyy.gbl.c_class_1
        assert c1.m_c == 3
        c1.destruct()

        if self.capi_identity == 'CINT':     # CINT does not support dynamic casts
            return

        c2 = cppyy.gbl.create_c2()
        assert type(c2) == cppyy.gbl.c_class_2
        assert c2.m_c == 3
        c2.destruct()
