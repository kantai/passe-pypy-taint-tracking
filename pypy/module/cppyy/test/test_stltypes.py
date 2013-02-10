import py, os, sys


currpath = py.path.local(__file__).dirpath()
test_dct = str(currpath.join("stltypesDict.so"))

def setup_module(mod):
    if sys.platform == 'win32':
        py.test.skip("win32 not supported so far")
    err = os.system("cd '%s' && make stltypesDict.so" % currpath)
    if err:
        raise OSError("'make' failed (see stderr)")

class AppTestSTLVECTOR:
    spaceconfig = dict(usemodules=['cppyy'])

    def setup_class(cls):
        cls.w_N = cls.space.wrap(13)
        cls.w_test_dct  = cls.space.wrap(test_dct)
        cls.w_stlvector = cls.space.appexec([], """():
            import cppyy
            return cppyy.load_reflection_info(%r)""" % (test_dct, ))

    def test01_builtin_type_vector_types(self):
        """Test access to std::vector<int>/std::vector<double>"""

        import cppyy

        assert cppyy.gbl.std        is cppyy.gbl.std
        assert cppyy.gbl.std.vector is cppyy.gbl.std.vector

        assert callable(cppyy.gbl.std.vector)

        type_info = (
            ("int",     int),
            ("float",   "float"),
            ("double",  "double"),
        )

        for c_type, p_type in type_info:
            tv1 = getattr(cppyy.gbl.std, 'vector<%s>' % c_type)
            tv2 = cppyy.gbl.std.vector(p_type)
            assert tv1 is tv2
            assert tv1.iterator is cppyy.gbl.std.vector(p_type).iterator

            #----- 
            v = tv1(); v += range(self.N)    # default args from Reflex are useless :/
            if p_type == int:                # only type with == and != reflected in .xml
                assert v.begin().__eq__(v.begin())
                assert v.begin() == v.begin()
                assert v.end() == v.end()
                assert v.begin() != v.end()
                assert v.end() != v.begin()

            #-----
            for i in range(self.N):
                v[i] = i
                assert v[i] == i
                assert v.at(i) == i

            assert v.size() == self.N
            assert len(v) == self.N

            #-----
            v = tv1()
            for i in range(self.N):
                v.push_back(i)
                assert v.size() == i+1
                assert v.at(i) == i
                assert v[i] == i

            assert v.size() == self.N
            assert len(v) == self.N

    def test02_user_type_vector_type(self):
        """Test access to an std::vector<just_a_class>"""

        import cppyy

        assert cppyy.gbl.std        is cppyy.gbl.std
        assert cppyy.gbl.std.vector is cppyy.gbl.std.vector

        assert callable(cppyy.gbl.std.vector)

        tv1 = getattr(cppyy.gbl.std, 'vector<just_a_class>')
        tv2 = cppyy.gbl.std.vector('just_a_class')
        tv3 = cppyy.gbl.std.vector(cppyy.gbl.just_a_class)

        assert tv1 is tv2
        assert tv2 is tv3

        v = tv3()
        assert hasattr(v, 'size' )
        assert hasattr(v, 'push_back' )
        assert hasattr(v, '__getitem__' )
        assert hasattr(v, 'begin' )
        assert hasattr(v, 'end' )

        for i in range(self.N):
             v.push_back(cppyy.gbl.just_a_class())
             v[i].m_i = i
             assert v[i].m_i == i

        assert len(v) == self.N
        v.destruct()

    def test03_empty_vector_type(self):
        """Test behavior of empty std::vector<int>"""

        import cppyy

        v = cppyy.gbl.std.vector(int)()
        for arg in v:
            pass
        v.destruct()

    def test04_vector_iteration(self):
        """Test iteration over an std::vector<int>"""

        import cppyy

        v = cppyy.gbl.std.vector(int)()

        for i in range(self.N):
            v.push_back(i)
            assert v.size() == i+1
            assert v.at(i) == i
            assert v[i] == i

        assert v.size() == self.N
        assert len(v) == self.N

        i = 0
        for arg in v:
            assert arg == i
            i += 1

        assert list(v) == [i for i in range(self.N)]

        v.destruct()

    def test05_push_back_iterables_with_iadd(self):
        """Test usage of += of iterable on push_back-able container"""

        import cppyy

        v = cppyy.gbl.std.vector(int)()

        v += [1, 2, 3]
        assert len(v) == 3
        assert v[0] == 1
        assert v[1] == 2
        assert v[2] == 3

        v += (4, 5, 6)
        assert len(v) == 6
        assert v[3] == 4
        assert v[4] == 5
        assert v[5] == 6

        raises(TypeError, v.__iadd__, (7, '8'))  # string shouldn't pass
        assert len(v) == 7   # TODO: decide whether this should roll-back

        v2 = cppyy.gbl.std.vector(int)()
        v2 += [8, 9]
        assert len(v2) == 2
        assert v2[0] == 8
        assert v2[1] == 9

        v += v2
        assert len(v) == 9
        assert v[6] == 7
        assert v[7] == 8
        assert v[8] == 9

    def test06_vector_indexing(self):
        """Test python-style indexing to an std::vector<int>"""

        import cppyy

        v = cppyy.gbl.std.vector(int)()

        for i in range(self.N):
            v.push_back(i)

        raises(IndexError, 'v[self.N]')
        raises(IndexError, 'v[self.N+1]')

        assert v[-1] == self.N-1
        assert v[-2] == self.N-2

        assert len(v[0:0]) == 0
        assert v[1:2][0] == v[1]

        v2 = v[2:-1]
        assert len(v2) == self.N-3     # 2 off from start, 1 from end
        assert v2[0] == v[2]
        assert v2[-1] == v[-2]
        assert v2[self.N-4] == v[-2]


class AppTestSTLSTRING:
    spaceconfig = dict(usemodules=['cppyy'])

    def setup_class(cls):
        cls.w_test_dct  = cls.space.wrap(test_dct)
        cls.w_stlstring = cls.space.appexec([], """():
            import cppyy
            return cppyy.load_reflection_info(%r)""" % (test_dct, ))

    def test01_string_argument_passing(self):
        """Test mapping of python strings and std::string"""

        import cppyy
        std = cppyy.gbl.std
        stringy_class = cppyy.gbl.stringy_class

        c, s = stringy_class(""), std.string("test1")

        # pass through const std::string&
        c.set_string1(s)
        assert c.get_string1() == s

        c.set_string1("test2")
        assert c.get_string1() == "test2"

        # pass through std::string (by value)
        s = std.string("test3")
        c.set_string2(s)
        assert c.get_string1() == s

        c.set_string2("test4")
        assert c.get_string1() == "test4"

        # getting through std::string&
        s2 = std.string()
        c.get_string2(s2)
        assert s2 == "test4"

        raises(TypeError, c.get_string2, "temp string")

    def test02_string_data_access(self):
        """Test access to std::string object data members"""

        import cppyy
        std = cppyy.gbl.std
        stringy_class = cppyy.gbl.stringy_class

        c, s = stringy_class(""), std.string("test string")

        c.m_string = "another test"
        assert c.m_string == "another test"
        assert str(c.m_string) == c.m_string
        assert c.get_string1() == "another test"

        return
        # TODO: assignment from object
        c.m_string = s
        assert str(c.m_string) == s
        assert c.m_string == s
        assert c.get_string1() == s

    def test03_string_with_null_character(self):
        """Test that strings with NULL do not get truncated"""

        import cppyy
        std = cppyy.gbl.std
        stringy_class = cppyy.gbl.stringy_class

        return

        t0 = "aap\0noot"
        self.assertEqual(t0, "aap\0noot")

        c, s = stringy_class(""), std.string(t0, len(t0))

        c.set_string1(s)
        assert t0 == c.get_string1()
        assert s == c.get_string1()


class AppTestSTLSTRING:
    spaceconfig = dict(usemodules=['cppyy'])

    def setup_class(cls):
        cls.w_N = cls.space.wrap(13)
        cls.w_test_dct  = cls.space.wrap(test_dct)
        cls.w_stlstring = cls.space.appexec([], """():
            import cppyy
            return cppyy.load_reflection_info(%r)""" % (test_dct, ))

    def test01_builtin_list_type(self):
        """Test access to a list<int>"""

        import cppyy
        from cppyy.gbl import std

        type_info = (
            ("int",     int),
            ("float",   "float"),
            ("double",  "double"),
        )

        for c_type, p_type in type_info:
            tl1 = getattr(std, 'list<%s>' % c_type)
            tl2 = cppyy.gbl.std.list(p_type)
            assert tl1 is tl2
            assert tl1.iterator is cppyy.gbl.std.list(p_type).iterator

            #-----
            a = tl1()
            for i in range(self.N):
                a.push_back( i )

            assert len(a) == self.N
            assert 11 < self.N
            assert 11 in a

            #-----
            ll = list(a)
            for i in range(self.N):
                assert ll[i] == i

            for val in a:
                assert ll[ll.index(val)] == val

    def test02_empty_list_type(self):
        """Test behavior of empty list<int>"""

        import cppyy
        from cppyy.gbl import std

        a = std.list(int)()
        for arg in a:
           pass

