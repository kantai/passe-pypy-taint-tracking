from __future__ import with_statement

import sys

from pypy.conftest import option
from pypy.interpreter.error import OperationError
from pypy.interpreter.gateway import interp2app
from pypy.module.micronumpy.test.test_base import BaseNumpyAppTest
from rpython.rlib.rfloat import isnan, isinf, copysign
from rpython.rlib.rcomplex import c_pow


def rAlmostEqual(a, b, rel_err=2e-15, abs_err=5e-323, msg='', isnumpy=False):
    """Fail if the two floating-point numbers are not almost equal.

    Determine whether floating-point values a and b are equal to within
    a (small) rounding error.  The default values for rel_err and
    abs_err are chosen to be suitable for platforms where a float is
    represented by an IEEE 754 double.  They allow an error of between
    9 and 19 ulps.
    """

    # special values testing
    if isnan(a):
        if isnan(b):
            return True,''
        raise AssertionError(msg + '%r should be nan' % (b,))

    if isinf(a):
        if a == b:
            return True,''
        raise AssertionError(msg + 'finite result where infinity expected: '+ \
                          'expected %r, got %r' % (a, b))

    # if both a and b are zero, check whether they have the same sign
    # (in theory there are examples where it would be legitimate for a
    # and b to have opposite signs; in practice these hardly ever
    # occur).
    if not a and not b and not isnumpy:
        # only check it if we are running on top of CPython >= 2.6
        if sys.version_info >= (2, 6) and copysign(1., a) != copysign(1., b):
            raise AssertionError( msg + \
                    'zero has wrong sign: expected %r, got %r' % (a, b))

    # if a-b overflows, or b is infinite, return False.  Again, in
    # theory there are examples where a is within a few ulps of the
    # max representable float, and then b could legitimately be
    # infinite.  In practice these examples are rare.
    try:
        absolute_error = abs(b-a)
    except OverflowError:
        pass
    else:
        # test passes if either the absolute error or the relative
        # error is sufficiently small.  The defaults amount to an
        # error of between 9 ulps and 19 ulps on an IEEE-754 compliant
        # machine.
        if absolute_error <= max(abs_err, rel_err * abs(a)):
            return True,''
    raise AssertionError(msg + \
            '%r and %r are not sufficiently close, %g > %g' %\
            (a, b, absolute_error, max(abs_err, rel_err*abs(a))))

def parse_testfile(fname):
    """Parse a file with test values

    Empty lines or lines starting with -- are ignored
    yields id, fn, arg_real, arg_imag, exp_real, exp_imag
    """
    with open(fname) as fp:
        for line in fp:
            # skip comment lines and blank lines
            if line.startswith('--') or not line.strip():
                continue

            lhs, rhs = line.split('->')
            id, fn, arg_real, arg_imag = lhs.split()
            rhs_pieces = rhs.split()
            exp_real, exp_imag = rhs_pieces[0], rhs_pieces[1]
            flags = rhs_pieces[2:]

            yield (id, fn,
                   float(arg_real), float(arg_imag),
                   float(exp_real), float(exp_imag),
                   flags
                  )

class AppTestUfuncs(BaseNumpyAppTest):
    def setup_class(cls):
        import os
        BaseNumpyAppTest.setup_class.im_func(cls)
        fname128 = os.path.join(os.path.dirname(__file__), 'complex_testcases.txt')
        fname64 = os.path.join(os.path.dirname(__file__), 'complex64_testcases.txt')
        cls.w_testcases128 = cls.space.wrap(list(parse_testfile(fname128)))
        cls.w_testcases64 = cls.space.wrap(list(parse_testfile(fname64)))

        cls.w_runAppDirect = cls.space.wrap(option.runappdirect)
        cls.w_isWindows = cls.space.wrap(os.name == 'nt')

        if cls.runappdirect:
            def cls_rAlmostEqual(space, *args, **kwargs):
                return rAlmostEqual(*args, **kwargs)
            cls.w_rAlmostEqual = cls.space.wrap(cls_rAlmostEqual)
            def cls_c_pow(space, *args):
                return c_pow(*args)
            cls.w_c_pow = cls.space.wrap(cls_c_pow)
        else:
            def cls_rAlmostEqual(space, __args__):
                args, kwargs = __args__.unpack()
                args = map(space.unwrap, args)
                kwargs = dict([
                    (k, space.unwrap(v))
                    for k, v in kwargs.iteritems()
                ])
                if '__pypy__' not in sys.builtin_module_names:
                    kwargs['isnumpy'] = True
                return space.wrap(rAlmostEqual(*args, **kwargs))
            cls.w_rAlmostEqual = cls.space.wrap(interp2app(cls_rAlmostEqual))
            def cls_c_pow(space, args_w):
                try:
                    retVal = c_pow(*map(space.unwrap, args_w))
                    return space.wrap(retVal)
                except ZeroDivisionError, e:
                    raise OperationError(cls.space.w_ZeroDivisionError,
                            cls.space.wrap(e.message))
                except OverflowError, e:
                    raise OperationError(cls.space.w_OverflowError,
                            cls.space.wrap(e.message))
                except ValueError, e:
                    raise OperationError(cls.space.w_ValueError,
                            cls.space.wrap(e.message))
            cls.w_c_pow = cls.space.wrap(interp2app(cls_c_pow))

    def test_fabs(self):
        from _numpypy import fabs, complex128

        a = complex128(complex(-5., 5.))
        raises(TypeError, fabs, a)

    def test_fmax(self):
        from _numpypy import fmax, array
        nnan, nan, inf, ninf = float('-nan'), float('nan'), float('inf'), float('-inf')
        a = array((complex(ninf, 10), complex(10, ninf), 
                   complex( inf, 10), complex(10,  inf),
                   5+5j, 5-5j, -5+5j, -5-5j,
                   0+5j, 0-5j, 5, -5,
                   complex(nan, 0), complex(0, nan)), dtype = complex)
        b = [ninf]*a.size
        res = [a[0 ], a[1 ], a[2 ], a[3 ], 
               a[4 ], a[5 ], a[6 ], a[7 ],
               a[8 ], a[9 ], a[10], a[11],
               b[12], b[13]]
        assert (fmax(a, b) == res).all()
        b = [inf]*a.size
        res = [b[0 ], b[1 ], a[2 ], b[3 ], 
               b[4 ], b[5 ], b[6 ], b[7 ],
               b[8 ], b[9 ], b[10], b[11],
               b[12], b[13]]
        assert (fmax(a, b) == res).all()
        b = [0]*a.size
        res = [b[0 ], a[1 ], a[2 ], a[3 ], 
               a[4 ], a[5 ], b[6 ], b[7 ],
               a[8 ], b[9 ], a[10], b[11],
               b[12], b[13]]
        assert (fmax(a, b) == res).all()

    def test_fmin(self):
        from _numpypy import fmin, array
        nnan, nan, inf, ninf = float('-nan'), float('nan'), float('inf'), float('-inf')
        a = array((complex(ninf, 10), complex(10, ninf), 
                   complex( inf, 10), complex(10,  inf),
                   5+5j, 5-5j, -5+5j, -5-5j,
                   0+5j, 0-5j, 5, -5,
                   complex(nan, 0), complex(0, nan)), dtype = complex)
        b = [inf]*a.size
        res = [a[0 ], a[1 ], b[2 ], a[3 ], 
               a[4 ], a[5 ], a[6 ], a[7 ],
               a[8 ], a[9 ], a[10], a[11],
               b[12], b[13]]
        assert (fmin(a, b) == res).all()
        b = [ninf]*a.size
        res = [b[0 ], b[1 ], b[2 ], b[3 ], 
               b[4 ], b[5 ], b[6 ], b[7 ],
               b[8 ], b[9 ], b[10], b[11],
               b[12], b[13]]
        assert (fmin(a, b) == res).all()
        b = [0]*a.size
        res = [a[0 ], b[1 ], b[2 ], b[3 ], 
               b[4 ], b[5 ], a[6 ], a[7 ],
               b[8 ], a[9 ], b[10], a[11],
               b[12], b[13]]
        assert (fmin(a, b) == res).all()

    def test_signbit(self):
        from _numpypy import signbit
        raises(TypeError, signbit, complex(1,1))

    def test_reciprocal(self):
        from _numpypy import array, reciprocal, complex64, complex128, clongdouble

        inf = float('inf')
        nan = float('nan')
        #complex    
        orig = [2.+4.j, -2.+4.j, 2.-4.j, -2.-4.j, 
                complex(inf, 3), complex(inf, -3), complex(inf, -inf), 
                complex(nan, 3), 0+0j, 0-0j]
        a2 = 2.**2 + 4.**2
        r = 2. / a2
        i = 4. / a2
        cnan = complex(nan, nan)
        expected = [complex(r, -i), complex(-r, -i), complex(r, i), 
                    complex(-r, i), 
                    -0j, 0j, cnan, 
                    cnan, cnan, cnan]
        for c, rel_err in ((complex64, 2e-7), (complex128, 2e-15), (clongdouble, 2e-15)):
            actual = reciprocal(array([orig], dtype=c))
            for b, a, e in zip(orig, actual, expected):
                assert (a[0].real - e.real) < rel_err
                assert (a[0].imag - e.imag) < rel_err

    def test_floorceiltrunc(self):
        from _numpypy import array, floor, ceil, trunc
        a = array([ complex(-1.4, -1.4), complex(-1.5, -1.5)]) 
        raises(TypeError, floor, a)
        raises(TypeError, ceil, a)
        raises(TypeError, trunc, a)

    def test_copysign(self):
        from _numpypy import copysign, complex128
        a = complex128(complex(-5., 5.))
        b = complex128(complex(0., 0.))
        raises(TypeError, copysign, a, b)

    def test_exp2(self):
        from _numpypy import array, exp2, complex128, complex64, clongfloat
        inf = float('inf')
        ninf = -float('inf')
        nan = float('nan')
        cmpl = complex
        for c,rel_err in ((complex128, 2e-15), (complex64, 1e-7), (clongfloat, 2e-15)):
            a = [cmpl(-5., 0), cmpl(-5., -5.), cmpl(-5., 5.),
                       cmpl(0., -5.), cmpl(0., 0.), cmpl(0., 5.),
                       cmpl(-0., -5.), cmpl(-0., 0.), cmpl(-0., 5.),
                       cmpl(-0., -0.), cmpl(inf, 0.), cmpl(inf, 5.),
                       cmpl(inf, -0.), cmpl(ninf, 0.), cmpl(ninf, 5.),
                       cmpl(ninf, -0.), cmpl(ninf, inf), cmpl(inf, inf),
                       cmpl(ninf, ninf), cmpl(5., inf), cmpl(5., ninf),
                       cmpl(nan, 5.), cmpl(5., nan), cmpl(nan, nan),
                     ]
            b = exp2(array(a,dtype=c))
            for i in range(len(a)):
                try:
                    res = self.c_pow((2,0), (a[i].real, a[i].imag))
                except OverflowError:
                    res = (inf, nan)
                except ValueError:
                    res = (nan, nan)
                msg = 'result of 2**%r(%r) got %r expected %r\n ' % \
                            (c,a[i], b[i], res)
                # cast untranslated boxed results to float,
                # does no harm when translated
                t1 = float(res[0])        
                t2 = float(b[i].real)        
                self.rAlmostEqual(t1, t2, rel_err=rel_err, msg=msg)
                t1 = float(res[1])        
                t2 = float(b[i].imag)        
                self.rAlmostEqual(t1, t2, rel_err=rel_err, msg=msg)

    def test_expm1(self):
        import math, cmath
        from _numpypy import array, expm1, complex128, complex64
        inf = float('inf')
        ninf = -float('inf')
        nan = float('nan')
        cmpl = complex
        for c,rel_err in ((complex128, 2e-15), (complex64, 1e-7)):
            a = [cmpl(-5., 0), cmpl(-5., -5.), cmpl(-5., 5.),
                       cmpl(0., -5.), cmpl(0., 0.), cmpl(0., 5.),
                       cmpl(-0., -5.), cmpl(-0., 0.), cmpl(-0., 5.),
                       cmpl(-0., -0.), cmpl(inf, 0.), cmpl(inf, 5.),
                       cmpl(inf, -0.), cmpl(ninf, 0.), cmpl(ninf, 5.),
                       cmpl(ninf, -0.), cmpl(ninf, inf), cmpl(inf, inf),
                       cmpl(ninf, ninf), cmpl(5., inf), cmpl(5., ninf),
                       cmpl(nan, 5.), cmpl(5., nan), cmpl(nan, nan),
                     ]
            b = expm1(array(a,dtype=c))
            for i in range(len(a)):
                try:
                    res = cmath.exp(a[i]) - 1.
                    if a[i].imag == 0. and math.copysign(1., a[i].imag)<0:
                        res = cmpl(res.real, -0.)
                    elif a[i].imag == 0.:
                        res = cmpl(res.real, 0.)
                except OverflowError:
                    res = cmpl(inf, nan)
                except ValueError:
                    res = cmpl(nan, nan)
                msg = 'result of expm1(%r(%r)) got %r expected %r\n ' % \
                            (c,a[i], b[i], res)
                # cast untranslated boxed results to float,
                # does no harm when translated
                t1 = float(res.real)        
                t2 = float(b[i].real)        
                self.rAlmostEqual(t1, t2, rel_err=rel_err, msg=msg)
                t1 = float(res.imag)        
                t2 = float(b[i].imag)        
                self.rAlmostEqual(t1, t2, rel_err=rel_err, msg=msg)

    def test_not_complex(self):
        from _numpypy import (radians, deg2rad, degrees, rad2deg,
                  isneginf, isposinf, logaddexp, logaddexp2, fmod,
                  arctan2)
        raises(TypeError, radians, complex(90,90))
        raises(TypeError, deg2rad, complex(90,90))
        raises(TypeError, degrees, complex(90,90))
        raises(TypeError, rad2deg, complex(90,90))
        raises(TypeError, isneginf, complex(1, 1))
        raises(TypeError, isposinf, complex(1, 1))
        raises(TypeError, logaddexp, complex(1, 1), complex(3, 3))
        raises(TypeError, logaddexp2, complex(1, 1), complex(3, 3))
        raises(TypeError, arctan2, complex(1, 1), complex(3, 3))
        raises (TypeError, fmod, complex(90,90), 3) 

    def test_isnan_isinf(self):
        from _numpypy import isnan, isinf, array
        assert (isnan(array([0.2+2j, complex(float('inf'),0), 
                complex(0,float('inf')), complex(0,float('nan')),
                complex(float('nan'), 0)], dtype=complex)) == \
                [False, False, False, True, True]).all()

        assert (isinf(array([0.2+2j, complex(float('inf'),0), 
                complex(0,float('inf')), complex(0,float('nan')),
                complex(float('nan'), 0)], dtype=complex)) == \
                [False, True, True, False, False]).all()


    def test_square(self):
        from _numpypy import square
        assert square(complex(3, 4)) == complex(3,4) * complex(3, 4)

    def test_power_complex(self):
        inf = float('inf')
        ninf = -float('inf')
        nan = float('nan')
        cmpl = complex
        from math import copysign
        from _numpypy import power, array, complex128, complex64
        # note: in some settings (namely a x86-32 build without the JIT),
        # gcc optimizes the code in rlib.rcomplex.c_pow() to not truncate
        # the 10-byte values down to 8-byte values.  It ends up with more
        # imprecision than usual (hence 2e-13 instead of 2e-15).
        for c,rel_err in ((complex128, 2e-13), (complex64, 4e-7)):
            a = array([cmpl(-5., 0), cmpl(-5., -5.), cmpl(-5., 5.),
                       cmpl(0., -5.), cmpl(0., 0.), cmpl(0., 5.),
                       cmpl(-0., -5.), cmpl(-0., 0.), cmpl(-0., 5.),
                       cmpl(-0., -0.), cmpl(inf, 0.), cmpl(inf, 5.),
                       cmpl(inf, -0.), cmpl(ninf, 0.), cmpl(ninf, 5.),
                       cmpl(ninf, -0.), cmpl(ninf, inf), cmpl(inf, inf),
                       cmpl(ninf, ninf), cmpl(5., inf), cmpl(5., ninf),
                       cmpl(nan, 5.), cmpl(5., nan), cmpl(nan, nan),
                     ], dtype=c)
            for p in (3, -1, 10000, 2.3, -10000, 10+3j):
                b = power(a, p)
                for i in range(len(a)):
                    try:
                        r = self.c_pow((float(a[i].real), float(a[i].imag)), 
                                (float(p.real), float(p.imag)))
                    except ZeroDivisionError:
                        r = (nan, nan)
                    except OverflowError:
                        r = (inf, -copysign(inf, a[i].imag))
                    except ValueError:
                        r = (nan, nan)
                    msg = 'result of %r(%r)**%r got %r expected %r\n ' % \
                            (c,a[i], p, b[i], r)
                    t1 = float(r[0])        
                    t2 = float(b[i].real)        
                    self.rAlmostEqual(t1, t2, rel_err=rel_err, msg=msg)
                    t1 = float(r[1])        
                    t2 = float(b[i].imag)
                    self.rAlmostEqual(t1, t2, rel_err=rel_err, msg=msg)

    def test_conjugate(self):
        from _numpypy import conj, conjugate, complex128, complex64
        import _numpypy as np

        c0 = complex128(complex(2.5, 0))
        c1 = complex64(complex(1, 2))

        assert conj is conjugate
        assert conj(c0) == c0
        assert conj(c1) == complex(1, -2)
        assert conj(1) == 1
        assert conj(-3) == -3
        assert conj(float('-inf')) == float('-inf')


        assert np.conjugate(1+2j) == 1-2j

        x = np.eye(2) + 1j * np.eye(2)
        for a, b in zip(np.conjugate(x), np.array([[ 1.-1.j,  0.-0.j], [ 0.-0.j,  1.-1.j]])):
            assert a[0] == b[0]
            assert a[1] == b[1]

    def test_logn(self):
        import math, cmath
        # log and log10 are tested in math (1:1 from rcomplex)
        from _numpypy import log2, array, complex128, complex64, log1p
        inf = float('inf')
        ninf = -float('inf')
        nan = float('nan')
        cmpl = complex
        log_2 = math.log(2)
        a = [cmpl(-5., 0), cmpl(-5., -5.), cmpl(-5., 5.),
             cmpl(0., -5.), cmpl(0., 0.), cmpl(0., 5.),
             cmpl(-0., -5.), cmpl(-0., 0.), cmpl(-0., 5.),
             cmpl(-0., -0.), cmpl(inf, 0.), cmpl(inf, 5.),
             cmpl(inf, -0.), cmpl(ninf, 0.), cmpl(ninf, 5.),
             cmpl(ninf, -0.), cmpl(ninf, inf), cmpl(inf, inf),
             cmpl(ninf, ninf), cmpl(5., inf), cmpl(5., ninf),
             cmpl(nan, 5.), cmpl(5., nan), cmpl(nan, nan),
            ]
        for c,rel_err in ((complex128, 2e-15), (complex64, 1e-7)):
            b = log2(array(a,dtype=c))
            for i in range(len(a)):
                try:
                    _res = cmath.log(a[i])
                    res = cmpl(_res.real / log_2, _res.imag / log_2)
                except OverflowError:
                    res = cmpl(inf, nan)
                except ValueError:
                    res = cmpl(ninf, 0)
                msg = 'result of log2(%r(%r)) got %r expected %r\n ' % \
                            (c,a[i], b[i], res)
                # cast untranslated boxed results to float,
                # does no harm when translated
                t1 = float(res.real)        
                t2 = float(b[i].real)        
                self.rAlmostEqual(t1, t2, rel_err=rel_err, msg=msg)
                t1 = float(res.imag)        
                t2 = float(b[i].imag)        
                self.rAlmostEqual(t1, t2, rel_err=rel_err, msg=msg)
        for c,rel_err in ((complex128, 2e-15), (complex64, 1e-7)):
            b = log1p(array(a,dtype=c))
            for i in range(len(a)):
                try:
                    #be careful, normal addition wipes out +-0j
                    res = cmath.log(cmpl(a[i].real+1, a[i].imag))
                except OverflowError:
                    res = cmpl(inf, nan)
                except ValueError:
                    res = cmpl(ninf, 0)
                msg = 'result of log1p(%r(%r)) got %r expected %r\n ' % \
                            (c,a[i], b[i], res)
                # cast untranslated boxed results to float,
                # does no harm when translated
                t1 = float(res.real)        
                t2 = float(b[i].real)        
                self.rAlmostEqual(t1, t2, rel_err=rel_err, msg=msg)
                t1 = float(res.imag)        
                t2 = float(b[i].imag)        
                self.rAlmostEqual(t1, t2, rel_err=rel_err, msg=msg)

    def test_logical_ops(self):
        from _numpypy import logical_and, logical_or, logical_xor, logical_not

        c1 = complex(1, 1)
        c3 = complex(3, 0)
        c0 = complex(0, 0)
        assert (logical_and([True, False , True, True], [c1, c1, c3, c0])
                == [True, False, True, False]).all()
        assert (logical_or([True, False, True, False], [c1, c3, c0, c0])
                == [True, True, True, False]).all()
        assert (logical_xor([True, False, True, False], [c1, c3, c0, c0])
                == [False, True, True, False]).all()
        assert (logical_not([c1, c0]) == [False, True]).all()

    def test_minimum(self):
        from _numpypy import array, minimum

        a = array([-5.0+5j, -5.0-5j, -0.0-10j, 1.0+10j])
        b = array([ 3.0+10.0j, 3.0, -2.0+2.0j, -3.0+4.0j])
        c = minimum(a, b)
        for i in range(4):
            assert c[i] == min(a[i], b[i])

    def test_maximum(self):
        from _numpypy import array, maximum

        a = array([-5.0+5j, -5.0-5j, -0.0-10j, 1.0+10j])
        b = array([ 3.0+10.0j, 3.0, -2.0+2.0j, -3.0+4.0j])
        c = maximum(a, b)
        for i in range(4):
            assert c[i] == max(a[i], b[i])

    def test_basic(self):
        from _numpypy import (complex128, complex64, add, array, dtype,
            subtract as sub, multiply, divide, negative, abs, floor_divide,
            real, imag, sign, clongfloat)
        from _numpypy import (equal, not_equal, greater, greater_equal, less,
                less_equal, isnan)
        assert real(4.0) == 4.0
        assert imag(0.0) == 0.0
        a = array([complex(3.0, 4.0)])
        b = a.real
        assert b.dtype == dtype(float)
        for complex_ in complex64, complex128, clongfloat:

            O = complex(0, 0)
            c0 = complex_(complex(2.5, 0))
            c1 = complex_(complex(1, 2))
            c2 = complex_(complex(3, 4))
            c3 = complex_(complex(-3, -3))

            assert equal(c0, 2.5)
            assert equal(c1, complex_(complex(1, 2)))
            assert equal(c1, complex(1, 2))
            assert equal(c1, c1)
            assert not_equal(c1, c2)
            assert not equal(c1, c2)

            assert less(c1, c2)
            assert less_equal(c1, c2)
            assert less_equal(c1, c1)
            assert not less(c1, c1)

            assert greater(c2, c1)
            assert greater_equal(c2, c1)
            assert not greater(c1, c2)

            assert add(c1, c2) == complex_(complex(4, 6))
            assert add(c1, c2) == complex(4, 6)
            
            assert sub(c0, c0) == sub(c1, c1) == 0
            assert sub(c1, c2) == complex(-2, -2)
            assert negative(complex(1,1)) == complex(-1, -1)
            assert negative(complex(0, 0)) == 0
            

            assert multiply(1, c1) == c1
            assert multiply(2, c2) == complex(6, 8)
            assert multiply(c1, c2) == complex(-5, 10)

            assert divide(c0, 1) == c0
            assert divide(c2, -1) == negative(c2)
            assert divide(c1, complex(0, 1)) == complex(2, -1)
            n = divide(c1, O)
            assert repr(n.real) == 'inf'
            assert repr(n.imag).startswith('inf') #can be inf*j or infj
            assert divide(c0, c0) == 1
            res = divide(c2, c1)
            assert abs(res.real-2.2) < 0.001
            assert abs(res.imag+0.4) < 0.001

            assert floor_divide(c0, c0) == complex(1, 0)
            assert isnan(floor_divide(c0, complex(0, 0)).real)
            assert floor_divide(c0, complex(0, 0)).imag == 0.0

            assert abs(c0) == 2.5
            assert abs(c2) == 5
            assert sign(complex(0, 0)) == 0
            assert sign(complex(-42, 0)) == -1
            assert sign(complex(42, 0)) == 1
            assert sign(complex(-42, 2)) == -1
            assert sign(complex(42, 2)) == 1
            assert sign(complex(-42, -3)) == -1
            assert sign(complex(42, -3)) == 1
            assert sign(complex(0, -42)) == -1
            assert sign(complex(0, 42)) == 1

            inf_c = complex_(complex(float('inf'), 0.))
            assert repr(abs(inf_c)) == 'inf'
            assert repr(abs(complex(float('nan'), float('nan')))) == 'nan'
            # numpy actually raises an AttributeError, 
            # but _numpypy raises a TypeError
            raises((TypeError, AttributeError), 'c2.real = 10.')
            raises((TypeError, AttributeError), 'c2.imag = 10.')
            assert(real(c2) == 3.0)
            assert(imag(c2) == 4.0)

    def test_math(self):
        if self.isWindows:
            skip('windows does not support c99 complex')
        import sys
        import _numpypy as np
        rAlmostEqual = self.rAlmostEqual

        for complex_, abs_err, testcases in (\
                 (np.complex128, 5e-323, self.testcases128),
                 # (np.complex64,  5e-32,  self.testcases64), 
                ):
            for id, fn, ar, ai, er, ei, flags in testcases:
                arg = complex_(complex(ar, ai))
                expected = (er, ei)
                if fn.startswith('acos'):
                    fn = 'arc' + fn[1:]
                elif fn.startswith('asin'):
                    fn = 'arc' + fn[1:]
                elif fn.startswith('atan'):
                    fn = 'arc' + fn[1:]
                elif fn in ('rect', 'polar'):
                    continue
                function = getattr(np, fn)
                _actual = function(arg)
                actual = (_actual.real, _actual.imag)

                if 'ignore-real-sign' in flags:
                    actual = (abs(actual[0]), actual[1])
                    expected = (abs(expected[0]), expected[1])
                if 'ignore-imag-sign' in flags:
                    actual = (actual[0], abs(actual[1]))
                    expected = (expected[0], abs(expected[1]))

                # for the real part of the log function, we allow an
                # absolute error of up to 2e-15.
                if fn in ('log', 'log10'):
                    real_abs_err = 2e-15
                else:
                    real_abs_err = abs_err

                error_message = (
                    '%s: %s(%r(%r, %r))\n'
                    'Expected: complex(%r, %r)\n'
                    'Received: complex(%r, %r)\n'
                    ) % (id, fn, complex_, ar, ai,
                         expected[0], expected[1],
                         actual[0], actual[1])
    
                # since rAlmostEqual is a wrapped function,
                # convert arguments to avoid boxed values
                rAlmostEqual(float(expected[0]), float(actual[0]),
                               abs_err=real_abs_err, msg=error_message)
                rAlmostEqual(float(expected[1]), float(actual[1]),
                                   msg=error_message)
                sys.stderr.write('.')
            sys.stderr.write('\n')
