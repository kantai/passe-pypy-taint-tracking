
from pypy.module.micronumpy.test.test_base import BaseNumpyAppTest

class AppTestNumSupport(BaseNumpyAppTest):
    def test_where(self):
        from _numpypy import where, ones, zeros, array
        a = [1, 2, 3, 0, -3]
        a = where(array(a) > 0, ones(5), zeros(5))
        assert (a == [1, 1, 1, 0, 0]).all()

    def test_where_differing_dtypes(self):
        from _numpypy import array, ones, zeros, where
        a = [1, 2, 3, 0, -3]
        a = where(array(a) > 0, ones(5, dtype=int), zeros(5, dtype=float))
        assert (a == [1, 1, 1, 0, 0]).all()

    def test_where_broadcast(self):
        from _numpypy import array, where
        a = where(array([[1, 2, 3], [4, 5, 6]]) > 3, [1, 1, 1], 2)
        assert (a == [[2, 2, 2], [1, 1, 1]]).all()
        a = where(True, [1, 1, 1], 2)
        assert (a == [1, 1, 1]).all()

    def test_where_errors(self):
        from _numpypy import where, array
        raises(ValueError, "where([1, 2, 3], [3, 4, 5])")
        raises(ValueError, "where([1, 2, 3], [3, 4, 5], [6, 7])")
        assert where(True, 1, 2) == array(1)
        assert where(False, 1, 2) == array(2)
        assert (where(True, [1, 2, 3], 2) == [1, 2, 3]).all()
        assert (where(False, 1, [1, 2, 3]) == [1, 2, 3]).all()
        assert (where([1, 2, 3], True, False) == [True, True, True]).all()

    #def test_where_1_arg(self):
    #    xxx

    def test_where_invalidates(self):
        from _numpypy import where, ones, zeros, array
        a = array([1, 2, 3, 0, -3])
        b = where(a > 0, ones(5), zeros(5))
        a[0] = 0
        assert (b == [1, 1, 1, 0, 0]).all()


    def test_dot(self):
        from _numpypy import array, dot, arange
        a = array(range(5))
        assert dot(a, a) == 30.0

        a = array(range(5))
        assert a.dot(range(5)) == 30
        assert dot(range(5), range(5)) == 30
        assert (dot(5, [1, 2, 3]) == [5, 10, 15]).all()

        a = arange(12).reshape(3, 4)
        b = arange(12).reshape(4, 3)
        c = a.dot(b)
        assert (c == [[ 42, 48, 54], [114, 136, 158], [186, 224, 262]]).all()

        a = arange(24).reshape(2, 3, 4)
        raises(ValueError, "a.dot(a)")
        b = a[0, :, :].T
        #Superfluous shape test makes the intention of the test clearer
        assert a.shape == (2, 3, 4)
        assert b.shape == (4, 3)
        c = dot(a, b)
        assert (c == [[[14, 38, 62], [38, 126, 214], [62, 214, 366]],
                   [[86, 302, 518], [110, 390, 670], [134, 478, 822]]]).all()
        c = dot(a, b[:, 2])
        assert (c == [[62, 214, 366], [518, 670, 822]]).all()
        a = arange(3*2*6).reshape((3,2,6))
        b = arange(3*2*6)[::-1].reshape((2,6,3))
        assert dot(a, b)[2,0,1,2] == 1140
        assert (dot([[1,2],[3,4]],[5,6]) == [17, 39]).all()

    def test_dot_constant(self):
        from _numpypy import array, dot
        a = array(range(5))
        b = a.dot(2.5)
        for i in xrange(5):
            assert b[i] == 2.5 * a[i]
        c = dot(4, 3.0)
        assert c == 12.0
        c = array(3.0).dot(array(4))
        assert c == 12.0
