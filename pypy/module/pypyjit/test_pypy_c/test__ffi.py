import sys, py
from pypy.module.pypyjit.test_pypy_c.test_00_model import BaseTestPyPyC

class Test__ffi(BaseTestPyPyC):

    def test__ffi_call(self):
        from rpython.rlib.test.test_clibffi import get_libm_name
        def main(libm_name):
            try:
                from _ffi import CDLL, types
            except ImportError:
                sys.stderr.write('SKIP: cannot import _ffi\n')
                return 0

            libm = CDLL(libm_name)
            pow = libm.getfunc('pow', [types.double, types.double],
                               types.double)
            i = 0
            res = 0
            while i < 300:
                tmp = pow(2, 3)   # ID: fficall
                res += tmp
                i += 1
            return pow.getaddr(), res
        #
        libm_name = get_libm_name(sys.platform)
        log = self.run(main, [libm_name])
        pow_addr, res = log.result
        assert res == 8.0 * 300
        py.test.xfail()     # XXX re-optimize _ffi for the JIT?
        loop, = log.loops_by_filename(self.filepath)
        if 'ConstClass(pow)' in repr(loop):   # e.g. OS/X
            pow_addr = 'ConstClass(pow)'
        assert loop.match_by_id('fficall', """
            guard_not_invalidated(descr=...)
            i17 = force_token()
            setfield_gc(p0, i17, descr=<.* .*PyFrame.vable_token .*>)
            f21 = call_release_gil(%s, 2.000000, 3.000000, descr=<Callf 8 ff EF=6>)
            guard_not_forced(descr=...)
            guard_no_exception(descr=...)
        """ % pow_addr)


    def test__ffi_call_frame_does_not_escape(self):
        from rpython.rlib.test.test_clibffi import get_libm_name
        def main(libm_name):
            try:
                from _ffi import CDLL, types
            except ImportError:
                sys.stderr.write('SKIP: cannot import _ffi\n')
                return 0

            libm = CDLL(libm_name)
            pow = libm.getfunc('pow', [types.double, types.double],
                               types.double)

            def mypow(a, b):
                return pow(a, b)

            i = 0
            res = 0
            while i < 300:
                tmp = mypow(2, 3)
                res += tmp
                i += 1
            return pow.getaddr(), res
        #
        libm_name = get_libm_name(sys.platform)
        log = self.run(main, [libm_name])
        pow_addr, res = log.result
        assert res == 8.0 * 300
        loop, = log.loops_by_filename(self.filepath)
        opnames = log.opnames(loop.allops())
        # we only force the virtualref, not its content
        assert opnames.count('new_with_vtable') == 1

    def test__ffi_call_releases_gil(self):
        from rpython.rlib.clibffi import get_libc_name
        def main(libc_name, n):
            import time
            import os
            from threading import Thread
            #
            if os.name == 'nt':
                from _ffi import WinDLL, types
                libc = WinDLL('Kernel32.dll')
                sleep = libc.getfunc('Sleep', [types.uint], types.uint)
                delays = [0]*n + [1000]
            else:
                from _ffi import CDLL, types
                libc = CDLL(libc_name)
                sleep = libc.getfunc('sleep', [types.uint], types.uint)
                delays = [0]*n + [1]
            #
            def loop_of_sleeps(i, delays):
                for delay in delays:
                    sleep(delay)    # ID: sleep
            #
            threads = [Thread(target=loop_of_sleeps, args=[i, delays]) for i in range(5)]
            start = time.time()
            for i, thread in enumerate(threads):
                thread.start()
            for thread in threads:
                thread.join()
            end = time.time()
            return end - start
        log = self.run(main, [get_libc_name(), 200], threshold=150,
                       import_site=True)
        assert 1 <= log.result <= 1.5 # at most 0.5 seconds of overhead
        loops = log.loops_by_id('sleep')
        assert len(loops) == 1 # make sure that we actually JITted the loop


    def test_ctypes_call(self):
        from rpython.rlib.test.test_clibffi import get_libm_name
        def main(libm_name):
            import ctypes
            libm = ctypes.CDLL(libm_name)
            fabs = libm.fabs
            fabs.argtypes = [ctypes.c_double]
            fabs.restype = ctypes.c_double
            x = -4
            i = 0
            while i < 300:
                x = fabs(x)
                x = x - 100
                i += 1
            return fabs._ptr.getaddr(), x

        libm_name = get_libm_name(sys.platform)
        log = self.run(main, [libm_name], import_site=True)
        fabs_addr, res = log.result
        assert res == -4.0
        loop, = log.loops_by_filename(self.filepath)
        ops = loop.allops()
        opnames = log.opnames(ops)
        assert opnames.count('new_with_vtable') == 1 # only the virtualref
        py.test.xfail()     # XXX re-optimize _ffi for the JIT?
        assert opnames.count('call_release_gil') == 1
        idx = opnames.index('call_release_gil')
        call = ops[idx]
        assert (call.args[0] == 'ConstClass(fabs)' or    # e.g. OS/X
                int(call.args[0]) == fabs_addr)


    def test__ffi_struct(self):
        def main():
            from _ffi import _StructDescr, Field, types
            fields = [
                Field('x', types.slong),
                ]
            descr = _StructDescr('foo', fields)
            struct = descr.allocate()
            i = 0
            while i < 300:
                x = struct.getfield('x')   # ID: getfield
                x = x+1
                struct.setfield('x', x)    # ID: setfield
                i += 1
            return struct.getfield('x')
        #
        log = self.run(main, [])
        py.test.xfail()     # XXX re-optimize _ffi for the JIT?
        loop, = log.loops_by_filename(self.filepath)
        assert loop.match_by_id('getfield', """
            guard_not_invalidated(descr=...)
            i57 = getfield_raw(i46, descr=<FieldS dynamic 0>)
        """)
        assert loop.match_by_id('setfield', """
            setfield_raw(i44, i57, descr=<FieldS dynamic 0>)
        """)


    def test__cffi_call(self):
        from rpython.rlib.test.test_clibffi import get_libm_name
        def main(libm_name):
            try:
                import _cffi_backend
            except ImportError:
                sys.stderr.write('SKIP: cannot import _cffi_backend\n')
                return 0

            libm = _cffi_backend.load_library(libm_name)
            BDouble = _cffi_backend.new_primitive_type("double")
            BPow = _cffi_backend.new_function_type([BDouble, BDouble], BDouble)
            pow = libm.load_function(BPow, 'pow')
            i = 0
            res = 0
            while i < 300:
                tmp = pow(2, 3)   # ID: cfficall
                res += tmp
                i += 1
            BLong = _cffi_backend.new_primitive_type("long")
            pow_addr = int(_cffi_backend.cast(BLong, pow))
            return pow_addr, res
        #
        libm_name = get_libm_name(sys.platform)
        log = self.run(main, [libm_name])
        pow_addr, res = log.result
        assert res == 8.0 * 300
        loop, = log.loops_by_filename(self.filepath)
        if 'ConstClass(pow)' in repr(loop):   # e.g. OS/X
            pow_addr = 'ConstClass(pow)'
        assert loop.match_by_id('cfficall', """
            ...
            f1 = call_release_gil(..., descr=<Callf 8 ff EF=6 OS=62>)
            ...
        """)
        # so far just check that call_release_gil() is produced.
        # later, also check that the arguments to call_release_gil()
        # are constants, and that the numerous raw_mallocs are removed
