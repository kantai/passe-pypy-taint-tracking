import py, os, sys
from rpython.tool.udir import udir
from rpython.rlib.jit import JitDriver, unroll_parameters, set_param
from rpython.rlib.jit import PARAMETERS, dont_look_inside
from rpython.rlib.jit import promote
from rpython.rlib import jit_hooks
from rpython.jit.metainterp.jitprof import Profiler
from rpython.jit.backend.detect_cpu import getcpuclass
from rpython.jit.backend.test.support import CCompiledMixin
from rpython.jit.codewriter.policy import StopAtXPolicy
from rpython.translator.translator import TranslationContext
from rpython.config.translationoption import DEFL_GC
from rpython.rlib import rgc
from rpython.jit.backend.arm.test.support import skip_unless_run_slow_tests
skip_unless_run_slow_tests()

class TestTranslationARM(CCompiledMixin):
    CPUClass = getcpuclass()

    def _get_TranslationContext(self):
        t = TranslationContext()
        t.config.translation.gc = DEFL_GC   # 'hybrid' or 'minimark'
        t.config.translation.gcrootfinder = 'shadowstack'
        return t

    def _check_cbuilder(self, cbuilder):
        pass

    def test_stuff_translates(self):
        # this is a basic test that tries to hit a number of features and their
        # translation:
        # - jitting of loops and bridges
        # - virtualizables
        # - set_param interface
        # - profiler
        # - full optimizer
        # - floats neg and abs

        class Frame(object):
            _virtualizable2_ = ['i']

            def __init__(self, i):
                self.i = i

        @dont_look_inside
        def myabs(x):
            return abs(x)

        jitdriver = JitDriver(greens = [],
                              reds = ['total', 'frame', 'j'],
                              virtualizables = ['frame'])
        def f(i, j):
            for param, _ in unroll_parameters:
                defl = PARAMETERS[param]
                set_param(jitdriver, param, defl)
            set_param(jitdriver, "threshold", 3)
            set_param(jitdriver, "trace_eagerness", 2)
            total = 0
            frame = Frame(i)
            j = float(j)
            while frame.i > 3:
                jitdriver.can_enter_jit(frame=frame, total=total, j=j)
                jitdriver.jit_merge_point(frame=frame, total=total, j=j)
                total += frame.i
                if frame.i >= 20:
                    frame.i -= 2
                frame.i -= 1
                j *= -0.712
                if j + (-j):    raise ValueError
                k = myabs(j)
                if k - abs(j):  raise ValueError
                if k - abs(-j): raise ValueError
            return chr(total % 253)
        #
        from rpython.rtyper.lltypesystem import lltype, rffi
        from rpython.rlib.libffi import types, CDLL, ArgChain
        from rpython.rlib.test.test_clibffi import get_libm_name
        libm_name = get_libm_name(sys.platform)
        jitdriver2 = JitDriver(greens=[], reds = ['i', 'func', 'res', 'x'])
        def libffi_stuff(i, j):
            lib = CDLL(libm_name)
            func = lib.getpointer('fabs', [types.double], types.double)
            res = 0.0
            x = float(j)
            while i > 0:
                jitdriver2.jit_merge_point(i=i, res=res, func=func, x=x)
                promote(func)
                argchain = ArgChain()
                argchain.arg(x)
                res = func.call(argchain, rffi.DOUBLE)
                i -= 1
            return res
        #
        def main(i, j):
            a_char = f(i, j)
            a_float = libffi_stuff(i, j)
            return ord(a_char) * 10 + int(a_float)
        expected = main(40, -49)
        res = self.meta_interp(main, [40, -49])
        assert res == expected

    def test_direct_assembler_call_translates(self):
        """Test CALL_ASSEMBLER and the recursion limit"""
        from rpython.rlib.rstackovf import StackOverflow

        class Thing(object):
            def __init__(self, val):
                self.val = val

        class Frame(object):
            _virtualizable2_ = ['thing']

        driver = JitDriver(greens = ['codeno'], reds = ['i', 'frame'],
                           virtualizables = ['frame'],
                           get_printable_location = lambda codeno: str(codeno))
        class SomewhereElse(object):
            pass

        somewhere_else = SomewhereElse()

        def change(newthing):
            somewhere_else.frame.thing = newthing

        def main(codeno):
            frame = Frame()
            somewhere_else.frame = frame
            frame.thing = Thing(0)
            portal(codeno, frame)
            return frame.thing.val

        def portal(codeno, frame):
            i = 0
            while i < 10:
                driver.can_enter_jit(frame=frame, codeno=codeno, i=i)
                driver.jit_merge_point(frame=frame, codeno=codeno, i=i)
                nextval = frame.thing.val
                if codeno == 0:
                    subframe = Frame()
                    subframe.thing = Thing(nextval)
                    nextval = portal(1, subframe)
                elif frame.thing.val > 40:
                    change(Thing(13))
                    nextval = 13
                frame.thing = Thing(nextval + 1)
                i += 1
            return frame.thing.val

        driver2 = JitDriver(greens = [], reds = ['n'])

        def main2(bound):
            try:
                while portal2(bound) == -bound+1:
                    bound *= 2
            except StackOverflow:
                pass
            return bound

        def portal2(n):
            while True:
                driver2.jit_merge_point(n=n)
                n -= 1
                if n <= 0:
                    return n
                n = portal2(n)
        assert portal2(10) == -9

        def mainall(codeno, bound):
            return main(codeno) + main2(bound)

        res = self.meta_interp(mainall, [0, 1], inline=True,
                               policy=StopAtXPolicy(change))
        print hex(res)
        assert res & 255 == main(0)
        bound = res & ~255
        assert 1024 <= bound <= 131072
        assert bound & (bound-1) == 0       # a power of two

    def test_jit_get_stats(self):
        driver = JitDriver(greens = [], reds = ['i'])
        
        def f():
            i = 0
            while i < 100000:
                driver.jit_merge_point(i=i)
                i += 1

        def main():
            jit_hooks.stats_set_debug(None, True)
            f()
            ll_times = jit_hooks.stats_get_loop_run_times(None)
            return len(ll_times)

        res = self.meta_interp(main, [])
        assert res == 3
        # one for loop, one for entry point and one for the prologue

class TestTranslationRemoveTypePtrARM(CCompiledMixin):
    CPUClass = getcpuclass()

    def _get_TranslationContext(self):
        t = TranslationContext()
        t.config.translation.gc = DEFL_GC   # 'hybrid' or 'minimark'
        t.config.translation.gcrootfinder = 'shadowstack'
        t.config.translation.list_comprehension_operations = True
        t.config.translation.gcremovetypeptr = True
        return t

    def test_external_exception_handling_translates(self):
        jitdriver = JitDriver(greens = [], reds = ['n', 'total'])

        class ImDone(Exception):
            def __init__(self, resvalue):
                self.resvalue = resvalue

        @dont_look_inside
        def f(x, total):
            if x <= 30:
                raise ImDone(total * 10)
            if x > 200:
                return 2
            raise ValueError
        @dont_look_inside
        def g(x):
            if x > 150:
                raise ValueError
            return 2
        class Base:
            def meth(self):
                return 2
        class Sub(Base):
            def meth(self):
                return 1
        @dont_look_inside
        def h(x):
            if x < 20000:
                return Sub()
            else:
                return Base()
        def myportal(i):
            set_param(jitdriver, "threshold", 3)
            set_param(jitdriver, "trace_eagerness", 2)
            total = 0
            n = i
            while True:
                jitdriver.can_enter_jit(n=n, total=total)
                jitdriver.jit_merge_point(n=n, total=total)
                try:
                    total += f(n, total)
                except ValueError:
                    total += 1
                try:
                    total += g(n)
                except ValueError:
                    total -= 1
                n -= h(n).meth()   # this is to force a GUARD_CLASS
        def main(i):
            try:
                myportal(i)
            except ImDone, e:
                return e.resvalue

        # XXX custom fishing, depends on the exact env var and format
        logfile = udir.join('test_ztranslation.log')
        os.environ['PYPYLOG'] = 'jit-log-opt:%s' % (logfile,)
        try:
            res = self.meta_interp(main, [400])
            assert res == main(400)
        finally:
            del os.environ['PYPYLOG']

        guard_class = 0
        for line in open(str(logfile)):
            if 'guard_class' in line:
                guard_class += 1
        # if we get many more guard_classes, it means that we generate
        # guards that always fail (the following assert's original purpose
        # is to catch the following case: each GUARD_CLASS is misgenerated
        # and always fails with "gcremovetypeptr")
        assert 0 < guard_class < 10
