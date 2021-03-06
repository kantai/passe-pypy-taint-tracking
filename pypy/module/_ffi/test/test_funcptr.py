from rpython.rtyper.lltypesystem import rffi
from rpython.rlib.clibffi import get_libc_name
from rpython.rlib.libffi import types
from rpython.rlib.libffi import CDLL
from rpython.rlib.test.test_clibffi import get_libm_name

import sys, py

class BaseAppTestFFI(object):
    spaceconfig = dict(usemodules=('_ffi', '_rawffi'))

    @classmethod
    def prepare_c_example(cls):
        from rpython.tool.udir import udir
        from rpython.translator.tool.cbuild import ExternalCompilationInfo
        from rpython.translator.platform import platform

        c_file = udir.ensure("test__ffi", dir=1).join("foolib.c")
        # automatically collect the C source from the docstrings of the tests
        snippets = ["""
        #ifdef _WIN32
        #define DLLEXPORT __declspec(dllexport)
        #else
        #define DLLEXPORT
        #endif
        """]
        for name in dir(cls):
            if name.startswith('test_'):
                meth = getattr(cls, name)
                # the heuristic to determine it it's really C code could be
                # improved: so far we just check that there is a '{' :-)
                if meth.__doc__ is not None and '{' in meth.__doc__:
                    snippets.append(meth.__doc__)
        #
        c_file.write(py.code.Source('\n'.join(snippets)))
        eci = ExternalCompilationInfo(export_symbols=[])
        return str(platform.compile([c_file], eci, 'x', standalone=False))

    def setup_class(cls):
        space = cls.space
        cls.w_iswin32 = space.wrap(sys.platform == 'win32')
        cls.w_libfoo_name = space.wrap(cls.prepare_c_example())
        cls.w_libc_name = space.wrap(get_libc_name())
        libm_name = get_libm_name(sys.platform)
        cls.w_libm_name = space.wrap(libm_name)
        libm = CDLL(libm_name)
        pow = libm.getpointer('pow', [], types.void)
        pow_addr = rffi.cast(rffi.LONG, pow.funcsym)
        cls.w_pow_addr = space.wrap(pow_addr)

class AppTestFFI(BaseAppTestFFI):

    def setup_class(cls):
        BaseAppTestFFI.setup_class.im_func(cls)
        space = cls.space
        # these are needed for test_single_float_args
        from ctypes import c_float
        f_12_34 = c_float(12.34).value
        f_56_78 = c_float(56.78).value
        f_result = c_float(f_12_34 + f_56_78).value
        cls.w_f_12_34_plus_56_78 = space.wrap(f_result)

    def test_libload(self):
        import _ffi
        _ffi.CDLL(self.libc_name)

    def test_libload_fail(self):
        import _ffi
        raises(OSError, _ffi.CDLL, "xxxxx_this_name_does_not_exist_xxxxx")

    def test_libload_None(self):
        if self.iswin32:
            skip("unix specific")
        from _ffi import CDLL, types
        # this should return *all* loaded libs, dlopen(NULL)
        dll = CDLL(None)
        # Assume CPython, or PyPy compiled with cpyext
        res = dll.getfunc('Py_IsInitialized', [], types.slong)()
        assert res == 1

    def test_callfunc(self):
        from _ffi import CDLL, types
        libm = CDLL(self.libm_name)
        pow = libm.getfunc('pow', [types.double, types.double], types.double)
        assert pow(2, 3) == 8

    def test_getaddr(self):
        from _ffi import CDLL, types
        libm = CDLL(self.libm_name)
        pow = libm.getfunc('pow', [types.double, types.double], types.double)
        assert pow.getaddr() == self.pow_addr

    def test_getaddressindll(self):
        import sys
        from _ffi import CDLL
        libm = CDLL(self.libm_name)
        pow_addr = libm.getaddressindll('pow')
        fff = sys.maxint*2-1
        if sys.platform == 'win32' or sys.platform == 'darwin':
            fff = sys.maxint*2+1
        assert pow_addr == self.pow_addr & fff

    def test_func_fromaddr(self):
        from _ffi import CDLL, types, FuncPtr
        libm = CDLL(self.libm_name)
        pow_addr = libm.getaddressindll('pow')
        pow = FuncPtr.fromaddr(pow_addr, 'pow', [types.double, types.double],
                               types.double)
        assert pow(2, 3) == 8

    def test_int_args(self):
        """
            DLLEXPORT int sum_xy(int x, int y)
            {
                return x+y;
            }
        """
        import sys
        from _ffi import CDLL, types
        libfoo = CDLL(self.libfoo_name)
        sum_xy = libfoo.getfunc('sum_xy', [types.sint, types.sint], types.sint)
        assert sum_xy(30, 12) == 42
        assert sum_xy(sys.maxint*2, 0) == -2

    def test_void_result(self):
        """
            int dummy = 0;
            DLLEXPORT void set_dummy(int val) { dummy = val; }
            DLLEXPORT int get_dummy() { return dummy; }
        """
        from _ffi import CDLL, types
        libfoo = CDLL(self.libfoo_name)
        set_dummy = libfoo.getfunc('set_dummy', [types.sint], types.void)
        get_dummy = libfoo.getfunc('get_dummy', [], types.sint)
        assert get_dummy() == 0
        assert set_dummy(42) is None
        assert get_dummy() == 42
        set_dummy(0)

    def test_pointer_args(self):
        """
            extern int dummy; // defined in test_void_result 
            DLLEXPORT int* get_dummy_ptr() { return &dummy; }
            DLLEXPORT void set_val_to_ptr(int* ptr, int val) { *ptr = val; }
        """
        from _ffi import CDLL, types
        libfoo = CDLL(self.libfoo_name)
        get_dummy = libfoo.getfunc('get_dummy', [], types.sint)
        get_dummy_ptr = libfoo.getfunc('get_dummy_ptr', [], types.void_p)
        set_val_to_ptr = libfoo.getfunc('set_val_to_ptr',
                                        [types.void_p, types.sint],
                                        types.void)
        assert get_dummy() == 0
        ptr = get_dummy_ptr()
        set_val_to_ptr(ptr, 123)
        assert get_dummy() == 123
        set_val_to_ptr(ptr, 0)

    def test_convert_pointer_args(self):
        """
            extern int dummy; // defined in test_void_result 
            DLLEXPORT int* get_dummy_ptr(); // defined in test_pointer_args
            DLLEXPORT void set_val_to_ptr(int* ptr, int val); // ditto
        """
        from _ffi import CDLL, types

        class MyPointerWrapper(object):
            def __init__(self, value):
                self.value = value
            def _as_ffi_pointer_(self, ffitype):
                assert ffitype is types.void_p
                return self.value
        
        libfoo = CDLL(self.libfoo_name)
        get_dummy = libfoo.getfunc('get_dummy', [], types.sint)
        get_dummy_ptr = libfoo.getfunc('get_dummy_ptr', [], types.void_p)
        set_val_to_ptr = libfoo.getfunc('set_val_to_ptr',
                                        [types.void_p, types.sint],
                                        types.void)
        assert get_dummy() == 0
        ptr = get_dummy_ptr()
        assert type(ptr) in (int, long)
        ptr2 = MyPointerWrapper(ptr)
        set_val_to_ptr(ptr2, 123)
        assert get_dummy() == 123
        set_val_to_ptr(ptr2, 0)

    def test_convert_strings_to_char_p(self):
        """
            DLLEXPORT
            long mystrlen(char* s)
            {
                long len = 0;
                while(*s++)
                    len++;
                return len;
            }
        """
        from _ffi import CDLL, types
        import _rawffi
        libfoo = CDLL(self.libfoo_name)
        mystrlen = libfoo.getfunc('mystrlen', [types.char_p], types.slong)
        #
        # first, try automatic conversion from a string
        assert mystrlen('foobar') == 6
        # then, try to pass an explicit pointer
        CharArray = _rawffi.Array('c')
        mystr = CharArray(7, 'foobar')
        assert mystrlen(mystr.buffer) == 6
        mystr.free()
        mystrlen.free_temp_buffers()

    def test_convert_unicode_to_unichar_p(self):
        """
            #include <wchar.h>
            DLLEXPORT
            long mystrlen_u(wchar_t* s)
            {
                long len = 0;
                while(*s++)
                    len++;
                return len;
            }
        """
        from _ffi import CDLL, types
        import _rawffi
        libfoo = CDLL(self.libfoo_name)
        mystrlen = libfoo.getfunc('mystrlen_u', [types.unichar_p], types.slong)
        #
        # first, try automatic conversion from strings and unicode
        assert mystrlen('foobar') == 6
        assert mystrlen(u'foobar') == 6
        assert mystrlen(u'ab\u2070') == 3
        # then, try to pass an explicit pointer
        UniCharArray = _rawffi.Array('u')
        mystr = UniCharArray(7, u'foobar')
        assert mystrlen(mystr.buffer) == 6
        mystr.free()
        mystrlen.free_temp_buffers()

    def test_keepalive_temp_buffer(self):
        """
            DLLEXPORT
            char* do_nothing(char* s)
            {
                return s;
            }
        """
        from _ffi import CDLL, types
        import _rawffi
        libfoo = CDLL(self.libfoo_name)
        do_nothing = libfoo.getfunc('do_nothing', [types.char_p], types.char_p)
        CharArray = _rawffi.Array('c')
        #
        ptr = do_nothing('foobar')
        array = CharArray.fromaddress(ptr, 7)
        assert list(array) == list('foobar\00')
        do_nothing.free_temp_buffers()

    def test_typed_pointer_args(self):
        """
            extern int dummy; // defined in test_void_result 
            DLLEXPORT int* get_dummy_ptr(); // defined in test_pointer_args
            DLLEXPORT void set_val_to_ptr(int* ptr, int val); // ditto
        """
        from _ffi import CDLL, types

        libfoo = CDLL(self.libfoo_name)
        intptr = types.Pointer(types.sint)
        get_dummy = libfoo.getfunc('get_dummy', [], types.sint)
        get_dummy_ptr = libfoo.getfunc('get_dummy_ptr', [], intptr)
        set_val_to_ptr = libfoo.getfunc('set_val_to_ptr', [intptr, types.sint], types.void)
        assert get_dummy() == 0
        ptr = get_dummy_ptr()
        set_val_to_ptr(ptr, 123)
        assert get_dummy() == 123
        set_val_to_ptr(ptr, 0)

    def test_huge_pointer_args(self):
        """
            #include <stdlib.h>
            DLLEXPORT long is_null_ptr(void* ptr) { return ptr == NULL; }
        """
        import sys
        from _ffi import CDLL, types
        libfoo = CDLL(self.libfoo_name)
        is_null_ptr = libfoo.getfunc('is_null_ptr', [types.void_p], types.ulong)
        assert not is_null_ptr(sys.maxint+1)

    def test_unsigned_long_args(self):
        """
            DLLEXPORT unsigned long sum_xy_ul(unsigned long x, unsigned long y)
            {
                return x+y;
            }
        """
        import sys
        from _ffi import CDLL, types
        libfoo = CDLL(self.libfoo_name)
        sum_xy = libfoo.getfunc('sum_xy_ul', [types.ulong, types.ulong],
                                types.ulong)
        assert sum_xy(sys.maxint, 12) == sys.maxint+12
        assert sum_xy(sys.maxint+1, 12) == sys.maxint+13
        #
        res = sum_xy(sys.maxint*2+3, 0)
        assert res == 1

    def test_unsigned_short_args(self):
        """
            DLLEXPORT unsigned short sum_xy_us(unsigned short x, unsigned short y)
            {
                return x+y;
            }
        """
        from _ffi import CDLL, types
        libfoo = CDLL(self.libfoo_name)
        sum_xy = libfoo.getfunc('sum_xy_us', [types.ushort, types.ushort],
                                types.ushort)
        assert sum_xy(32000, 8000) == 40000
        assert sum_xy(60000, 30000) == 90000 % 65536

    def test_unsigned_byte_args(self):
        """
            DLLEXPORT unsigned char sum_xy_ub(unsigned char x, unsigned char y)
            {
                return x+y;
            }
        """
        from _ffi import CDLL, types
        libfoo = CDLL(self.libfoo_name)
        sum_xy = libfoo.getfunc('sum_xy_us', [types.ubyte, types.ubyte],
                                types.ubyte)
        assert sum_xy(100, 40) == 140
        assert sum_xy(200, 60) == 260 % 256

    def test_unsigned_int_args(self):
        r"""
            DLLEXPORT unsigned int sum_xy_ui(unsigned int x, unsigned int y)
            {
                return x+y;
            }
        """
        import sys
        from _ffi import CDLL, types
        maxint32 = 2147483647
        libfoo = CDLL(self.libfoo_name)
        sum_xy = libfoo.getfunc('sum_xy_ui', [types.uint, types.uint],
                                types.uint)
        assert sum_xy(maxint32, 1) == maxint32+1
        assert sum_xy(maxint32, maxint32+2) == 0

    def test_signed_byte_args(self):
        """
            DLLEXPORT signed char sum_xy_sb(signed char x, signed char y)
            {
                return x+y;
            }
        """
        from _ffi import CDLL, types
        libfoo = CDLL(self.libfoo_name)
        sum_xy = libfoo.getfunc('sum_xy_sb', [types.sbyte, types.sbyte],
                                types.sbyte)
        assert sum_xy(10, 20) == 30
        assert sum_xy(100, 28) == -128

    def test_char_args(self):
        """
            DLLEXPORT char my_toupper(char x)
            {
                return x - ('a'-'A');
            }
        """
        from _ffi import CDLL, types
        libfoo = CDLL(self.libfoo_name)
        my_toupper = libfoo.getfunc('my_toupper', [types.char],
                                    types.char)
        assert my_toupper('c') == 'C'

    def test_unichar_args(self):
        """
            #include <stddef.h>
            DLLEXPORT wchar_t sum_xy_wc(wchar_t x, wchar_t y)
            {
                return x + y;
            }
        """
        from _ffi import CDLL, types
        libfoo = CDLL(self.libfoo_name)
        sum_xy = libfoo.getfunc('sum_xy_wc', [types.unichar, types.unichar],
                                types.unichar)
        res = sum_xy(unichr(1000), unichr(2000))
        assert type(res) is unicode
        assert ord(res) == 3000

    def test_single_float_args(self):
        """
            DLLEXPORT float sum_xy_float(float x, float y)
            {
                return x+y;
            }
        """
        from _ffi import CDLL, types
        libfoo = CDLL(self.libfoo_name)
        sum_xy = libfoo.getfunc('sum_xy_float', [types.float, types.float],
                                types.float)
        res = sum_xy(12.34, 56.78)
        assert res == self.f_12_34_plus_56_78


    def test_slonglong_args(self):
        """
            DLLEXPORT long long sum_xy_longlong(long long x, long long y)
            {
                return x+y;
            }
        """
        from _ffi import CDLL, types
        maxint32 = 2147483647 # we cannot really go above maxint on 64 bits
                              # (and we would not test anything, as there long
                              # is the same as long long)

        libfoo = CDLL(self.libfoo_name)
        sum_xy = libfoo.getfunc('sum_xy_longlong', [types.slonglong, types.slonglong],
                                types.slonglong)
        x = maxint32+1
        y = maxint32+2
        res = sum_xy(x, y)
        expected = maxint32*2 + 3
        assert res == expected

    def test_ulonglong_args(self):
        """
            DLLEXPORT unsigned long long sum_xy_ulonglong(unsigned long long x,
                                                unsigned long long y)
            {
                return x+y;
            }
        """
        from _ffi import CDLL, types
        maxint64 = 9223372036854775807 # maxint64+1 does not fit into a
                                       # longlong, but it does into a
                                       # ulonglong
        libfoo = CDLL(self.libfoo_name)
        sum_xy = libfoo.getfunc('sum_xy_ulonglong', [types.ulonglong, types.ulonglong],
                                types.ulonglong)
        x = maxint64+1
        y = 2
        res = sum_xy(x, y)
        expected = maxint64 + 3
        assert res == expected
        #
        res = sum_xy(maxint64*2+3, 0)
        assert res == 1

    def test_byval_argument(self):
        """
            struct Point {
                long x;
                long y;
            };

            DLLEXPORT long sum_point(struct Point p) {
                return p.x + p.y;
            }
        """
        from _ffi import CDLL, types, _StructDescr, Field
        Point = _StructDescr('Point', [
                Field('x', types.slong),
                Field('y', types.slong),
                ])
        libfoo = CDLL(self.libfoo_name)
        sum_point = libfoo.getfunc('sum_point', [Point.ffitype], types.slong)
        #
        p = Point.allocate()
        p.setfield('x', 30)
        p.setfield('y', 12)
        res = sum_point(p)
        assert res == 42

    def test_byval_result(self):
        """
            DLLEXPORT struct Point make_point(long x, long y) {
                struct Point p;
                p.x = x;
                p.y = y;
                return p;
            }
        """
        from _ffi import CDLL, types, _StructDescr, Field
        Point = _StructDescr('Point', [
                Field('x', types.slong),
                Field('y', types.slong),
                ])
        libfoo = CDLL(self.libfoo_name)
        make_point = libfoo.getfunc('make_point', [types.slong, types.slong],
                                    Point.ffitype)
        #
        p = make_point(12, 34)
        assert p.getfield('x') == 12
        assert p.getfield('y') == 34

    # XXX: support for _rawffi structures should be killed as soon as we
    # implement ctypes.Structure on top of _ffi. In the meantime, we support
    # both
    def test_byval_argument__rawffi(self):
        """
            // defined above
            struct Point;
            DLLEXPORT long sum_point(struct Point p);
        """
        import _rawffi
        from _ffi import CDLL, types
        POINT = _rawffi.Structure([('x', 'l'), ('y', 'l')])
        ffi_point = POINT.get_ffi_type()
        libfoo = CDLL(self.libfoo_name)
        sum_point = libfoo.getfunc('sum_point', [ffi_point], types.slong)
        #
        p = POINT()
        p.x = 30
        p.y = 12
        res = sum_point(p)
        assert res == 42
        p.free()

    def test_byval_result__rawffi(self):
        """
            // defined above
            DLLEXPORT struct Point make_point(long x, long y);
        """
        import _rawffi
        from _ffi import CDLL, types
        POINT = _rawffi.Structure([('x', 'l'), ('y', 'l')])
        ffi_point = POINT.get_ffi_type()
        libfoo = CDLL(self.libfoo_name)
        make_point = libfoo.getfunc('make_point', [types.slong, types.slong], ffi_point)
        #
        p = make_point(12, 34)
        assert p.x == 12
        assert p.y == 34
        p.free()


    def test_TypeError_numargs(self):
        from _ffi import CDLL, types
        libfoo = CDLL(self.libfoo_name)
        sum_xy = libfoo.getfunc('sum_xy', [types.sint, types.sint], types.sint)
        raises(TypeError, "sum_xy(1, 2, 3)")
        raises(TypeError, "sum_xy(1)")

    def test_TypeError_voidarg(self):
        from _ffi import CDLL, types
        libfoo = CDLL(self.libfoo_name)
        raises(TypeError, "libfoo.getfunc('sum_xy', [types.void], types.sint)")
        
    def test_OSError_loading(self):
        from _ffi import CDLL, types
        raises(OSError, "CDLL('I do not exist')")

    def test_AttributeError_missing_function(self):
        from _ffi import CDLL, types
        libfoo = CDLL(self.libfoo_name)
        raises(AttributeError, "libfoo.getfunc('I_do_not_exist', [], types.void)")
        if self.iswin32:
            skip("unix specific")
        libnone = CDLL(None)
        raises(AttributeError, "libnone.getfunc('I_do_not_exist', [], types.void)")

    def test_calling_convention1(self):
        if not self.iswin32:
            skip("windows specific")
        from _ffi import WinDLL, types
        libm = WinDLL(self.libm_name)
        pow = libm.getfunc('pow', [types.double, types.double], types.double)
        try:
            pow(2, 3)
        except ValueError, e:
            assert e.message.startswith('Procedure called with')
        else:
            assert 0, 'test must assert, wrong calling convention'

    def test_calling_convention2(self):
        if not self.iswin32:
            skip("windows specific")
        from _ffi import WinDLL, types
        kernel = WinDLL('Kernel32.dll')
        sleep = kernel.getfunc('Sleep', [types.uint], types.void)
        sleep(10)

    def test_calling_convention3(self):
        if not self.iswin32:
            skip("windows specific")
        from _ffi import CDLL, types
        wrong_kernel = CDLL('Kernel32.dll')
        wrong_sleep = wrong_kernel.getfunc('Sleep', [types.uint], types.void)
        try:
            wrong_sleep(10)
        except ValueError, e:
            assert e.message.startswith('Procedure called with')
        else:
            assert 0, 'test must assert, wrong calling convention'

    def test_func_fromaddr2(self):
        if not self.iswin32:
            skip("windows specific")
        from _ffi import CDLL, types, FuncPtr
        from _rawffi import FUNCFLAG_STDCALL
        libm = CDLL(self.libm_name)
        pow_addr = libm.getaddressindll('pow')
        wrong_pow = FuncPtr.fromaddr(pow_addr, 'pow', 
                [types.double, types.double], types.double, FUNCFLAG_STDCALL)
        try:
            wrong_pow(2, 3) == 8
        except ValueError, e:
            assert e.message.startswith('Procedure called with')
        else:
            assert 0, 'test must assert, wrong calling convention'

    def test_func_fromaddr3(self):
        if not self.iswin32:
            skip("windows specific")
        from _ffi import WinDLL, types, FuncPtr
        from _rawffi import FUNCFLAG_STDCALL
        kernel = WinDLL('Kernel32.dll')
        sleep_addr = kernel.getaddressindll('Sleep')
        sleep = FuncPtr.fromaddr(sleep_addr, 'sleep', [types.uint], 
                            types.void, FUNCFLAG_STDCALL)
        sleep(10)

    def test_by_ordinal(self):
        """
            int DLLEXPORT AAA_first_ordinal_function()
            {
                return 42;
            }
        """
        if not self.iswin32:
            skip("windows specific")
        from _ffi import CDLL, types
        libfoo = CDLL(self.libfoo_name)
        f_name = libfoo.getfunc('AAA_first_ordinal_function', [], types.sint)
        f_ordinal = libfoo.getfunc(1, [], types.sint)
        assert f_name.getaddr() == f_ordinal.getaddr()
