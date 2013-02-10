
import py, sys

from pypy.conftest import option
from pypy.module.micronumpy.appbridge import get_appbridge_cache
from pypy.module.micronumpy.iter import Chunk, Chunks
from pypy.module.micronumpy.interp_numarray import W_NDimArray
from pypy.module.micronumpy.test.test_base import BaseNumpyAppTest

class MockDtype(object):
    class itemtype(object):
        @staticmethod
        def malloc(size):
            return None

        @staticmethod
        def get_element_size():
            return 1

    def get_size(self):
        return 1


def create_slice(a, chunks):
    return Chunks(chunks).apply(a).implementation

def create_array(*args, **kwargs):
    return W_NDimArray.from_shape(*args, **kwargs).implementation

class TestNumArrayDirect(object):
    def newslice(self, *args):
        return self.space.newslice(*[self.space.wrap(arg) for arg in args])

    def newtuple(self, *args):
        args_w = []
        for arg in args:
            if isinstance(arg, int):
                args_w.append(self.space.wrap(arg))
            else:
                args_w.append(arg)
        return self.space.newtuple(args_w)

    def test_strides_f(self):
        a = create_array([10, 5, 3], MockDtype(), order='F')
        assert a.strides == [1, 10, 50]
        assert a.backstrides == [9, 40, 100]

    def test_strides_c(self):
        a = create_array([10, 5, 3], MockDtype(), order='C')
        assert a.strides == [15, 3, 1]
        assert a.backstrides == [135, 12, 2]

    def test_create_slice_f(self):
        a = create_array([10, 5, 3], MockDtype(), order='F')
        s = create_slice(a, [Chunk(3, 0, 0, 1)])
        assert s.start == 3
        assert s.strides == [10, 50]
        assert s.backstrides == [40, 100]
        s = create_slice(a, [Chunk(1, 9, 2, 4)])
        assert s.start == 1
        assert s.strides == [2, 10, 50]
        assert s.backstrides == [6, 40, 100]
        s = create_slice(a, [Chunk(1, 5, 3, 2), Chunk(1, 2, 1, 1), Chunk(1, 0, 0, 1)])
        assert s.shape == [2, 1]
        assert s.strides == [3, 10]
        assert s.backstrides == [3, 0]
        s = create_slice(a, [Chunk(0, 10, 1, 10), Chunk(2, 0, 0, 1)])
        assert s.start == 20
        assert s.shape == [10, 3]

    def test_create_slice_c(self):
        a = create_array([10, 5, 3], MockDtype(), order='C')
        s = create_slice(a, [Chunk(3, 0, 0, 1)])
        assert s.start == 45
        assert s.strides == [3, 1]
        assert s.backstrides == [12, 2]
        s = create_slice(a, [Chunk(1, 9, 2, 4)])
        assert s.start == 15
        assert s.strides == [30, 3, 1]
        assert s.backstrides == [90, 12, 2]
        s = create_slice(a, [Chunk(1, 5, 3, 2), Chunk(1, 2, 1, 1),
                            Chunk(1, 0, 0, 1)])
        assert s.start == 19
        assert s.shape == [2, 1]
        assert s.strides == [45, 3]
        assert s.backstrides == [45, 0]
        s = create_slice(a, [Chunk(0, 10, 1, 10), Chunk(2, 0, 0, 1)])
        assert s.start == 6
        assert s.shape == [10, 3]

    def test_slice_of_slice_f(self):
        a = create_array([10, 5, 3], MockDtype(), order='F')
        s = create_slice(a, [Chunk(5, 0, 0, 1)])
        assert s.start == 5
        s2 = create_slice(s, [Chunk(3, 0, 0, 1)])
        assert s2.shape == [3]
        assert s2.strides == [50]
        assert s2.parent is a
        assert s2.backstrides == [100]
        assert s2.start == 35
        s = create_slice(a, [Chunk(1, 5, 3, 2)])
        s2 = create_slice(s, [Chunk(0, 2, 1, 2), Chunk(2, 0, 0, 1)])
        assert s2.shape == [2, 3]
        assert s2.strides == [3, 50]
        assert s2.backstrides == [3, 100]
        assert s2.start == 1 * 15 + 2 * 3

    def test_slice_of_slice_c(self):
        a = create_array([10, 5, 3], MockDtype(), order='C')
        s = create_slice(a, [Chunk(5, 0, 0, 1)])
        assert s.start == 15 * 5
        s2 = create_slice(s, [Chunk(3, 0, 0, 1)])
        assert s2.shape == [3]
        assert s2.strides == [1]
        assert s2.parent is a
        assert s2.backstrides == [2]
        assert s2.start == 5 * 15 + 3 * 3
        s = create_slice(a, [Chunk(1, 5, 3, 2)])
        s2 = create_slice(s, [Chunk(0, 2, 1, 2), Chunk(2, 0, 0, 1)])
        assert s2.shape == [2, 3]
        assert s2.strides == [45, 1]
        assert s2.backstrides == [45, 2]
        assert s2.start == 1 * 15 + 2 * 3

    def test_negative_step_f(self):
        a = create_array([10, 5, 3], MockDtype(), order='F')
        s = create_slice(a, [Chunk(9, -1, -2, 5)])
        assert s.start == 9
        assert s.strides == [-2, 10, 50]
        assert s.backstrides == [-8, 40, 100]

    def test_negative_step_c(self):
        a = create_array([10, 5, 3], MockDtype(), order='C')
        s = create_slice(a, [Chunk(9, -1, -2, 5)])
        assert s.start == 135
        assert s.strides == [-30, 3, 1]
        assert s.backstrides == [-120, 12, 2]

    def test_shape_agreement(self):
        from pypy.module.micronumpy.strides import _shape_agreement
        assert _shape_agreement([3], [3]) == [3]
        assert _shape_agreement([1, 2, 3], [1, 2, 3]) == [1, 2, 3]
        _shape_agreement([2], [3]) == 0
        assert _shape_agreement([4, 4], []) == [4, 4]
        assert _shape_agreement([8, 1, 6, 1], [7, 1, 5]) == [8, 7, 6, 5]
        assert _shape_agreement([5, 2], [4, 3, 5, 2]) == [4, 3, 5, 2]

    def test_calc_new_strides(self):
        from pypy.module.micronumpy.strides import calc_new_strides
        assert calc_new_strides([2, 4], [4, 2], [4, 2], "C") == [8, 2]
        assert calc_new_strides([2, 4, 3], [8, 3], [1, 16], 'F') == [1, 2, 16]
        assert calc_new_strides([2, 3, 4], [8, 3], [1, 16], 'F') is None
        assert calc_new_strides([24], [2, 4, 3], [48, 6, 1], 'C') is None
        assert calc_new_strides([24], [2, 4, 3], [24, 6, 2], 'C') == [2]
        assert calc_new_strides([105, 1], [3, 5, 7], [35, 7, 1],'C') == [1, 1]
        assert calc_new_strides([1, 105], [3, 5, 7], [35, 7, 1],'C') == [105, 1]
        assert calc_new_strides([1, 105], [3, 5, 7], [35, 7, 1],'F') is None
        assert calc_new_strides([1, 1, 1, 105, 1], [15, 7], [7, 1],'C') == \
                                    [105, 105, 105, 1, 1]
        assert calc_new_strides([1, 1, 105, 1, 1], [7, 15], [1, 7],'F') == \
                                    [1, 1, 1, 105, 105]

    def test_to_coords(self):
        from pypy.module.micronumpy.strides import to_coords

        def _to_coords(index, order):
            return to_coords(self.space, [2, 3, 4], 24, order,
                             self.space.wrap(index))[0]

        assert _to_coords(0, 'C') == [0, 0, 0]
        assert _to_coords(1, 'C') == [0, 0, 1]
        assert _to_coords(-1, 'C') == [1, 2, 3]
        assert _to_coords(5, 'C') == [0, 1, 1]
        assert _to_coords(13, 'C') == [1, 0, 1]
        assert _to_coords(0, 'F') == [0, 0, 0]
        assert _to_coords(1, 'F') == [1, 0, 0]
        assert _to_coords(-1, 'F') == [1, 2, 3]
        assert _to_coords(5, 'F') == [1, 2, 0]
        assert _to_coords(13, 'F') == [1, 0, 2]

    def test_find_shape(self):
        from pypy.module.micronumpy.strides import find_shape_and_elems

        space = self.space
        shape, elems = find_shape_and_elems(space,
                                            space.newlist([space.wrap("a"),
                                                           space.wrap("b")]),
                                            None)
        assert shape == [2]
        assert space.str_w(elems[0]) == "a"
        assert space.str_w(elems[1]) == "b"

    def test_from_shape_and_storage(self):
        from rpython.rlib.rawstorage import alloc_raw_storage, raw_storage_setitem
        from rpython.rtyper.lltypesystem import rffi
        from pypy.module.micronumpy.interp_dtype import get_dtype_cache
        storage = alloc_raw_storage(4, track_allocation=False, zero=True)
        for i in range(4):
            raw_storage_setitem(storage, i, rffi.cast(rffi.UCHAR, i))
        #
        dtypes = get_dtype_cache(self.space)
        w_array = W_NDimArray.from_shape_and_storage([2, 2], storage, dtypes.w_int8dtype)
        def get(i, j):
            return w_array.getitem(self.space, [i, j]).value
        assert get(0, 0) == 0
        assert get(0, 1) == 1
        assert get(1, 0) == 2
        assert get(1, 1) == 3

class AppTestNumArray(BaseNumpyAppTest):
    def w_CustomIndexObject(self, index):
        class CustomIndexObject(object):
            def __init__(self, index):
                self.index = index
            def __index__(self):
                return self.index

        return CustomIndexObject(index)

    def w_CustomIndexIntObject(self, index, value):
        class CustomIndexIntObject(object):
            def __init__(self, index, value):
                self.index = index
                self.value = value
            def __index__(self):
                return self.index
            def __int__(self):
                return self.value

        return CustomIndexIntObject(index, value)

    def w_CustomIntObject(self, value):
        class CustomIntObject(object):
            def __init__(self, value):
                self.value = value
            def __index__(self):
                return self.value

        return CustomIntObject(value)

    def test_ndarray(self):
        from _numpypy import ndarray, array, dtype

        assert type(ndarray) is type
        assert type(array) is not type
        a = ndarray((2, 3))
        assert a.shape == (2, 3)
        assert a.dtype == dtype(float)

        raises(TypeError, ndarray, [[1], [2], [3]])

        a = ndarray(3, dtype=int)
        assert a.shape == (3,)
        assert a.dtype is dtype(int)
        a = ndarray([], dtype=float)
        assert a.shape == ()

    def test_ndmin(self):
        from _numpypy import array

        arr = array([[[1]]], ndmin=1)
        assert arr.shape == (1, 1, 1)

    def test_noop_ndmin(self):
        from _numpypy import array

        arr = array([1], ndmin=3)
        assert arr.shape == (1, 1, 1)

    def test_type(self):
        from _numpypy import array
        ar = array(range(5))
        assert type(ar) is type(ar + ar)

    def test_ndim(self):
        from _numpypy import array
        x = array(0.2)
        assert x.ndim == 0
        x = array([1, 2])
        assert x.ndim == 1
        x = array([[1, 2], [3, 4]])
        assert x.ndim == 2
        x = array([[[1, 2], [3, 4]], [[5, 6], [7, 8]]])
        assert x.ndim == 3
        # numpy actually raises an AttributeError, but _numpypy raises an
        # TypeError
        raises((TypeError, AttributeError), 'x.ndim = 3')

    def test_init(self):
        from _numpypy import zeros
        a = zeros(15)
        # Check that storage was actually zero'd.
        assert a[10] == 0.0
        # And check that changes stick.
        a[13] = 5.3
        assert a[13] == 5.3
        assert zeros(()).shape == ()

    def test_size(self):
        from _numpypy import array,arange,cos
        assert array(3).size == 1
        a = array([1, 2, 3])
        assert a.size == 3
        assert (a + a).size == 3
        ten = cos(1 + arange(10)).size
        assert ten == 10

    def test_empty(self):
        """
        Test that empty() works.
        """

        from _numpypy import empty
        a = empty(2)
        a[1] = 1.0
        assert a[1] == 1.0

    def test_ones(self):
        from _numpypy import ones
        a = ones(3)
        assert len(a) == 3
        assert a[0] == 1
        raises(IndexError, "a[3]")
        a[2] = 4
        assert a[2] == 4

    def test_copy(self):
        from _numpypy import arange, array
        a = arange(5)
        b = a.copy()
        for i in xrange(5):
            assert b[i] == a[i]
        a[3] = 22
        assert b[3] == 3

        a = array(1)
        assert a.copy() == a

        a = arange(8)
        b = a[::2]
        c = b.copy()
        assert (c == b).all()
        assert ((a + a).copy() == (a + a)).all()

        a = arange(15).reshape(5,3)
        b = a.copy()
        assert (b == a).all()

    def test_iterator_init(self):
        from _numpypy import array
        a = array(range(5))
        assert a[3] == 3

    def test_getitem(self):
        from _numpypy import array
        a = array(range(5))
        raises(IndexError, "a[5]")
        a = a + a
        raises(IndexError, "a[5]")
        assert a[-1] == 8
        raises(IndexError, "a[-6]")

    def test_getitem_float(self):
        from _numpypy import array
        a = array([1, 2, 3, 4])
        assert a[1.2] == 2
        assert a[1.6] == 2
        assert a[-1.2] == 4

    def test_getitem_tuple(self):
        from _numpypy import array
        a = array(range(5))
        raises(IndexError, "a[(1,2)]")
        for i in xrange(5):
            assert a[(i,)] == i
        b = a[()]
        for i in xrange(5):
            assert a[i] == b[i]

    def test_getitem_nd(self):
        from _numpypy import arange
        a = arange(15).reshape(3, 5)
        assert a[1, 3] == 8
        assert a.T[1, 2] == 11

    def test_getitem_obj_index(self):
        from _numpypy import arange

        a = arange(10)

        assert a[self.CustomIndexObject(1)] == 1

    def test_getitem_obj_prefer_index_to_int(self):
        from _numpypy import arange

        a = arange(10)


        assert a[self.CustomIndexIntObject(0, 1)] == 0

    def test_getitem_obj_int(self):
        from _numpypy import arange

        a = arange(10)

        assert a[self.CustomIntObject(1)] == 1

    def test_setitem(self):
        from _numpypy import array
        a = array(range(5))
        a[-1] = 5.0
        assert a[4] == 5.0
        raises(IndexError, "a[5] = 0.0")
        raises(IndexError, "a[-6] = 3.0")

    def test_setitem_tuple(self):
        from _numpypy import array
        a = array(range(5))
        raises(IndexError, "a[(1,2)] = [0,1]")
        for i in xrange(5):
            a[(i,)] = i + 1
            assert a[i] == i + 1
        a[()] = range(5)
        for i in xrange(5):
            assert a[i] == i

    def test_setitem_obj_index(self):
        from _numpypy import arange

        a = arange(10)

        a[self.CustomIndexObject(1)] = 100
        assert a[1] == 100

    def test_setitem_obj_prefer_index_to_int(self):
        from _numpypy import arange

        a = arange(10)

        a[self.CustomIndexIntObject(0, 1)] = 100
        assert a[0] == 100

    def test_setitem_obj_int(self):
        from _numpypy import arange

        a = arange(10)

        a[self.CustomIntObject(1)] = 100

        assert a[1] == 100

    def test_access_swallow_exception(self):
        class ErrorIndex(object):
            def __index__(self):
                return 1 / 0

        class ErrorInt(object):
            def __int__(self):
                return 1 / 0

        # numpy will swallow errors in __int__ and __index__ and
        # just raise IndexError.

        from _numpypy import arange
        a = arange(10)
        raises(IndexError, "a[ErrorIndex()] == 0")
        raises(IndexError, "a[ErrorInt()] == 0")

    def test_setslice_array(self):
        from _numpypy import array
        a = array(range(5))
        b = array(range(2))
        a[1:4:2] = b
        assert a[1] == 0.
        assert a[3] == 1.
        b[::-1] = b
        assert b[0] == 1.
        assert b[1] == 0.

    def test_setslice_of_slice_array(self):
        from _numpypy import array, zeros
        a = zeros(5)
        a[::2] = array([9., 10., 11.])
        assert a[0] == 9.
        assert a[2] == 10.
        assert a[4] == 11.
        a[1:4:2][::-1] = array([1., 2.])
        assert a[0] == 9.
        assert a[1] == 2.
        assert a[2] == 10.
        assert a[3] == 1.
        assert a[4] == 11.
        a = zeros(10)
        a[::2][::-1][::2] = array(range(1, 4))
        assert a[8] == 1.
        assert a[4] == 2.
        assert a[0] == 3.

    def test_setslice_list(self):
        from _numpypy import array
        a = array(range(5), float)
        b = [0., 1.]
        a[1:4:2] = b
        assert a[1] == 0.
        assert a[3] == 1.

    def test_setslice_constant(self):
        from _numpypy import array
        a = array(range(5), float)
        a[1:4:2] = 0.
        assert a[1] == 0.
        assert a[3] == 0.

    def test_newaxis(self):
        import math
        from _numpypy import array, cos, zeros
        from numpypy.core.numeric import newaxis
        a = array(range(5))
        b = array([range(5)])
        assert (a[newaxis] == b).all()
        a = array(range(3))
        b = array([1, 3])
        expected = zeros((3, 2))
        for x in range(3):
            for y in range(2):
                expected[x, y] = math.cos(a[x]) * math.cos(b[y])
        assert ((cos(a)[:,newaxis] * cos(b).T) == expected).all()

    def test_newaxis_slice(self):
        from _numpypy import array
        from numpypy.core.numeric import newaxis

        a = array(range(5))
        b = array(range(1,5))
        c = array([range(1,5)])
        d = array([[x] for x in range(1,5)])

        assert (a[1:] == b).all()
        assert (a[1:,newaxis] == d).all()
        assert (a[newaxis,1:] == c).all()

    def test_newaxis_assign(self):
        from _numpypy import array
        from numpypy.core.numeric import newaxis

        a = array(range(5))
        a[newaxis,1] = [2]
        assert a[1] == 2

    def test_newaxis_virtual(self):
        from _numpypy import array
        from numpypy.core.numeric import newaxis

        a = array(range(5))
        b = (a + a)[newaxis]
        c = array([[0, 2, 4, 6, 8]])
        assert (b == c).all()

    def test_newaxis_then_slice(self):
        from _numpypy import array
        from numpypy.core.numeric import newaxis
        a = array(range(5))
        b = a[newaxis]
        assert b.shape == (1, 5)
        assert (b[0,1:] == a[1:]).all()

    def test_slice_then_newaxis(self):
        from _numpypy import array
        from numpypy.core.numeric import newaxis
        a = array(range(5))
        b = a[2:]
        assert (b[newaxis] == [[2, 3, 4]]).all()

    def test_scalar(self):
        from _numpypy import array, dtype
        a = array(3)
        raises(IndexError, "a[0]")
        raises(IndexError, "a[0] = 5")
        assert a.size == 1
        assert a.shape == ()
        assert a.dtype is dtype(int)

    def test_len(self):
        from _numpypy import array
        a = array(range(5))
        assert len(a) == 5
        assert len(a + a) == 5

    def test_shape(self):
        from _numpypy import array
        a = array(range(5))
        assert a.shape == (5,)
        b = a + a
        assert b.shape == (5,)
        c = a[:3]
        assert c.shape == (3,)
        assert array([]).shape == (0,)

    def test_set_shape(self):
        from _numpypy import array, zeros
        a = array([])
        raises(ValueError, "a.shape = []")
        a = array(range(12))
        a.shape = (3, 4)
        assert (a == [range(4), range(4, 8), range(8, 12)]).all()
        a.shape = (3, 2, 2)
        assert a[1, 1, 1] == 7
        a.shape = (3, -1, 2)
        assert a.shape == (3, 2, 2)
        a.shape = 12
        assert a.shape == (12, )
        exc = raises(ValueError, "a.shape = 10")
        assert str(exc.value) == "total size of new array must be unchanged"
        a = array(3)
        a.shape = ()
        #numpy allows this
        a.shape = (1,)
        assert a[0] == 3
        a = array(range(6)).reshape(2,3).T
        raises(AttributeError, 'a.shape = 6')

    def test_reshape(self):
        from _numpypy import array, zeros
        a = array(range(12))
        exc = raises(ValueError, "b = a.reshape((3, 10))")
        assert str(exc.value) == "total size of new array must be unchanged"
        b = a.reshape((3, 4))
        assert b.shape == (3, 4)
        assert (b == [range(4), range(4, 8), range(8, 12)]).all()
        b[:, 0] = 1000
        assert (a == [1000, 1, 2, 3, 1000, 5, 6, 7, 1000, 9, 10, 11]).all()
        a = zeros((4, 2, 3))
        a.shape = (12, 2)
        (a + a).reshape(2, 12) # assert did not explode
        a = array([[[[]]]])
        assert a.reshape((0,)).shape == (0,)

    def test_slice_reshape(self):
        from _numpypy import zeros, arange
        a = zeros((4, 2, 3))
        b = a[::2, :, :]
        b.shape = (2, 6)
        exc = raises(AttributeError, "b.shape = 12")
        assert str(exc.value) == \
                           "incompatible shape for a non-contiguous array"
        b = a[::2, :, :].reshape((2, 6))
        assert b.shape == (2, 6)
        b = arange(20)[1:17:2]
        b.shape = (4, 2)
        assert (b == [[1, 3], [5, 7], [9, 11], [13, 15]]).all()
        c = b.reshape((2, 4))
        assert (c == [[1, 3, 5, 7], [9, 11, 13, 15]]).all()

        z = arange(96).reshape((12, -1))
        assert z.shape == (12, 8)
        y = z.reshape((4, 3, 8))
        v = y[:, ::2, :]
        w = y.reshape(96)
        u = v.reshape(64)
        assert y[1, 2, 1] == z[5, 1]
        y[1, 2, 1] = 1000
        # z, y, w, v are views of eachother
        assert z[5, 1] == 1000
        assert v[1, 1, 1] == 1000
        assert w[41] == 1000
        # u is not a view, it is a copy!
        assert u[25] == 41

        a = zeros((5, 2))
        assert a.reshape(-1).shape == (10,)

        raises(ValueError, arange(10).reshape, (5, -1, -1))

    def test_reshape_varargs(self):
        from _numpypy import arange
        z = arange(96).reshape(12, -1)
        y = z.reshape(4, 3, 8)
        assert y.shape == (4, 3, 8)

    def test_scalar_reshape(self):
        from numpypy import array
        a = array(3)
        assert a.reshape([1, 1]).shape == (1, 1)
        assert a.reshape([1]).shape == (1,)
        raises(ValueError, "a.reshape(3)")

    def test_strides(self):
        from _numpypy import array
        a = array([[1.0, 2.0],
                   [3.0, 4.0]])
        assert a.strides == (16, 8)
        assert a[1:].strides == (16, 8)

    def test_strides_scalar(self):
        from _numpypy import array
        a = array(42)
        assert a.strides == ()

    def test_add(self):
        from _numpypy import array
        a = array(range(5))
        b = a + a
        for i in range(5):
            assert b[i] == i + i

        a = array([True, False, True, False], dtype="?")
        b = array([True, True, False, False], dtype="?")
        c = a + b
        for i in range(4):
            assert c[i] == bool(a[i] + b[i])

    def test_add_other(self):
        from _numpypy import array
        a = array(range(5))
        b = array([i for i in reversed(range(5))])
        c = a + b
        for i in range(5):
            assert c[i] == 4

    def test_add_constant(self):
        from _numpypy import array
        a = array(range(5))
        b = a + 5
        for i in range(5):
            assert b[i] == i + 5

    def test_radd(self):
        from _numpypy import array
        r = 3 + array(range(3))
        for i in range(3):
            assert r[i] == i + 3
        r = [1, 2] + array([1, 2])
        assert (r == [2, 4]).all()

    def test_add_list(self):
        from _numpypy import array, ndarray
        a = array(range(5))
        b = list(reversed(range(5)))
        c = a + b
        assert isinstance(c, ndarray)
        for i in range(5):
            assert c[i] == 4

    def test_subtract(self):
        from _numpypy import array
        a = array(range(5))
        b = a - a
        for i in range(5):
            assert b[i] == 0

    def test_subtract_other(self):
        from _numpypy import array
        a = array(range(5))
        b = array([1, 1, 1, 1, 1])
        c = a - b
        for i in range(5):
            assert c[i] == i - 1

    def test_subtract_constant(self):
        from _numpypy import array
        a = array(range(5))
        b = a - 5
        for i in range(5):
            assert b[i] == i - 5

    def test_scalar_subtract(self):
        from _numpypy import int32
        assert int32(2) - 1 == 1
        assert 1 - int32(2) == -1

    def test_mul(self):
        import _numpypy

        a = _numpypy.array(range(5))
        b = a * a
        for i in range(5):
            assert b[i] == i * i
        assert b.dtype is a.dtype

        a = _numpypy.array(range(5), dtype=bool)
        b = a * a
        assert b.dtype is _numpypy.dtype(bool)
        assert b[0] is _numpypy.False_
        for i in range(1, 5):
            assert b[i] is _numpypy.True_

    def test_mul_constant(self):
        from _numpypy import array
        a = array(range(5))
        b = a * 5
        for i in range(5):
            assert b[i] == i * 5

    def test_div(self):
        from math import isnan
        from _numpypy import array, dtype

        a = array(range(1, 6))
        b = a / a
        for i in range(5):
            assert b[i] == 1

        a = array(range(1, 6), dtype=bool)
        b = a / a
        assert b.dtype is dtype("int8")
        for i in range(5):
            assert b[i] == 1

        a = array([-1, 0, 1])
        b = array([0, 0, 0])
        c = a / b
        assert (c == [0, 0, 0]).all()

        a = array([-1.0, 0.0, 1.0])
        b = array([0.0, 0.0, 0.0])
        c = a / b
        assert c[0] == float('-inf')
        assert isnan(c[1])
        assert c[2] == float('inf')

        b = array([-0.0, -0.0, -0.0])
        c = a / b
        assert c[0] == float('inf')
        assert isnan(c[1])
        assert c[2] == float('-inf')

    def test_div_other(self):
        from _numpypy import array
        a = array(range(5))
        b = array([2, 2, 2, 2, 2], float)
        c = a / b
        for i in range(5):
            assert c[i] == i / 2.0

    def test_div_constant(self):
        from _numpypy import array
        a = array(range(5))
        b = a / 5.0
        for i in range(5):
            assert b[i] == i / 5.0

    def test_floordiv(self):
        from math import isnan
        from _numpypy import array, dtype

        a = array(range(1, 6))
        b = a // a
        assert (b == [1, 1, 1, 1, 1]).all()

        a = array(range(1, 6), dtype=bool)
        b = a // a
        assert b.dtype is dtype("int8")
        assert (b == [1, 1, 1, 1, 1]).all()

        a = array([-1, 0, 1])
        b = array([0, 0, 0])
        c = a // b
        assert (c == [0, 0, 0]).all()

        a = array([-1.0, 0.0, 1.0])
        b = array([0.0, 0.0, 0.0])
        c = a // b
        assert c[0] == float('-inf')
        assert isnan(c[1])
        assert c[2] == float('inf')

        b = array([-0.0, -0.0, -0.0])
        c = a // b
        assert c[0] == float('inf')
        assert isnan(c[1])
        assert c[2] == float('-inf')

    def test_floordiv_other(self):
        from _numpypy import array
        a = array(range(5))
        b = array([2, 2, 2, 2, 2], float)
        c = a // b
        assert (c == [0, 0, 1, 1, 2]).all()

    def test_rfloordiv(self):
        from _numpypy import array
        a = array(range(1, 6))
        b = 3 // a
        assert (b == [3, 1, 1, 0, 0]).all()

    def test_floordiv_constant(self):
        from _numpypy import array
        a = array(range(5))
        b = a // 2
        assert (b == [0, 0, 1, 1, 2]).all()

    def test_truediv(self):
        from operator import truediv
        from _numpypy import arange

        assert (truediv(arange(5), 2) == [0., .5, 1., 1.5, 2.]).all()
        assert (truediv(2, arange(3)) == [float("inf"), 2., 1.]).all()

    def test_divmod(self):
        from _numpypy import arange

        a, b = divmod(arange(10), 3)
        assert (a == [0, 0, 0, 1, 1, 1, 2, 2, 2, 3]).all()
        assert (b == [0, 1, 2, 0, 1, 2, 0, 1, 2, 0]).all()

    def test_rdivmod(self):
        from _numpypy import arange

        a, b = divmod(3, arange(1, 5))
        assert (a == [3, 1, 1, 0]).all()
        assert (b == [0, 1, 0, 3]).all()

    def test_lshift(self):
        from _numpypy import array

        a = array([0, 1, 2, 3])
        assert (a << 2 == [0, 4, 8, 12]).all()
        a = array([True, False])
        assert (a << 2 == [4, 0]).all()
        a = array([1.0])
        raises(TypeError, lambda: a << 2)

    def test_rlshift(self):
        from _numpypy import arange

        a = arange(3)
        assert (2 << a == [2, 4, 8]).all()

    def test_rshift(self):
        from _numpypy import arange, array

        a = arange(10)
        assert (a >> 2 == [0, 0, 0, 0, 1, 1, 1, 1, 2, 2]).all()
        a = array([True, False])
        assert (a >> 1 == [0, 0]).all()
        a = arange(3, dtype=float)
        raises(TypeError, lambda: a >> 1)

    def test_rrshift(self):
        from _numpypy import arange

        a = arange(5)
        assert (2 >> a == [2, 1, 0, 0, 0]).all()

    def test_pow(self):
        from _numpypy import array
        a = array(range(5), float)
        b = a ** a
        for i in range(5):
            assert b[i] == i ** i

        a = array(range(5))
        assert (a ** 2 == a * a).all()

    def test_pow_other(self):
        from _numpypy import array
        a = array(range(5), float)
        b = array([2, 2, 2, 2, 2])
        c = a ** b
        for i in range(5):
            assert c[i] == i ** 2

    def test_pow_constant(self):
        from _numpypy import array
        a = array(range(5), float)
        b = a ** 2
        for i in range(5):
            assert b[i] == i ** 2

    def test_mod(self):
        from _numpypy import array
        a = array(range(1, 6))
        b = a % a
        for i in range(5):
            assert b[i] == 0

        a = array(range(1, 6), float)
        b = (a + 1) % a
        assert b[0] == 0
        for i in range(1, 5):
            assert b[i] == 1

    def test_mod_other(self):
        from _numpypy import array
        a = array(range(5))
        b = array([2, 2, 2, 2, 2])
        c = a % b
        for i in range(5):
            assert c[i] == i % 2

    def test_mod_constant(self):
        from _numpypy import array
        a = array(range(5))
        b = a % 2
        for i in range(5):
            assert b[i] == i % 2

    def test_rand(self):
        from _numpypy import arange

        a = arange(5)
        assert (3 & a == [0, 1, 2, 3, 0]).all()

    def test_ror(self):
        from _numpypy import arange

        a = arange(5)
        assert (3 | a == [3, 3, 3, 3, 7]).all()

    def test_xor(self):
        from _numpypy import arange

        a = arange(5)
        assert (a ^ 3 == [3, 2, 1, 0, 7]).all()

    def test_rxor(self):
        from _numpypy import arange

        a = arange(5)
        assert (3 ^ a == [3, 2, 1, 0, 7]).all()

    def test_pos(self):
        from _numpypy import array
        a = array([1., -2., 3., -4., -5.])
        b = +a
        for i in range(5):
            assert b[i] == a[i]

        a = +array(range(5))
        for i in range(5):
            assert a[i] == i

    def test_neg(self):
        from _numpypy import array
        a = array([1., -2., 3., -4., -5.])
        b = -a
        for i in range(5):
            assert b[i] == -a[i]

        a = -array(range(5), dtype="int8")
        for i in range(5):
            assert a[i] == -i

    def test_abs(self):
        from _numpypy import array
        a = array([1., -2., 3., -4., -5.])
        b = abs(a)
        for i in range(5):
            assert b[i] == abs(a[i])

        a = abs(array(range(-5, 5), dtype="int8"))
        for i in range(-5, 5):
            assert a[i + 5] == abs(i)

    def test_auto_force(self):
        from _numpypy import array
        a = array(range(5))
        b = a - 1
        a[2] = 3
        for i in range(5):
            assert b[i] == i - 1

        a = array(range(5))
        b = a + a
        c = b + b
        b[1] = 5
        assert c[1] == 4

    def test_getslice(self):
        from _numpypy import array
        a = array(range(5))
        s = a[1:5]
        assert len(s) == 4
        for i in range(4):
            assert s[i] == a[i + 1]

        s = (a + a)[1:2]
        assert len(s) == 1
        assert s[0] == 2
        s[:1] = array([5])
        assert s[0] == 5

    def test_getslice_step(self):
        from _numpypy import array
        a = array(range(10))
        s = a[1:9:2]
        assert len(s) == 4
        for i in range(4):
            assert s[i] == a[2 * i + 1]

    def test_slice_update(self):
        from _numpypy import array
        a = array(range(5))
        s = a[0:3]
        s[1] = 10
        assert a[1] == 10
        a[2] = 20
        assert s[2] == 20

    def test_slice_invaidate(self):
        # check that slice shares invalidation list with
        from _numpypy import array
        a = array(range(5))
        s = a[0:2]
        b = array([10, 11])
        c = s + b
        a[0] = 100
        assert c[0] == 10
        assert c[1] == 12
        d = s + b
        a[1] = 101
        assert d[0] == 110
        assert d[1] == 12

    def test_mean(self):
        from _numpypy import array, arange
        a = array(range(5))
        assert a.mean() == 2.0
        assert a[:4].mean() == 1.5
        a = array(range(105)).reshape(3, 5, 7)
        b = a.mean(axis=0)
        assert b[0, 0] == 35.
        assert a.mean(axis=0)[0, 0] == 35
        assert (b == array(range(35, 70), dtype=float).reshape(5, 7)).all()
        assert (a.mean(2) == array(range(0, 15), dtype=float).reshape(3, 5) * 7 + 3).all()
        assert (arange(10).reshape(5, 2).mean(axis=1) == [0.5, 2.5, 4.5, 6.5, 8.5]).all()
        assert (a.mean(axis=-1) == a.mean(axis=2)).all()
        raises(ValueError, a.mean, -4)
        raises(ValueError, a.mean, 3)
        a = arange(10).reshape(5, 2)
        assert (a.mean(1) == [0.5, 2.5, 4.5, 6.5, 8.5]).all()

    def test_sum(self):
        from _numpypy import array
        a = array(range(5))
        assert a.sum() == 10
        assert a[:4].sum() == 6

        a = array([True] * 5, bool)
        assert a.sum() == 5

        raises(TypeError, 'a.sum(axis=0, out=3)')
        raises(ValueError, 'a.sum(axis=2)')
        d = array(0.)
        b = a.sum(out=d)
        assert b == d
        assert b is d

    def test_reduce_nd(self):
        from numpypy import arange, array, multiply
        a = arange(15).reshape(5, 3)
        assert a.sum() == 105
        assert a.max() == 14
        assert array([]).sum() == 0.0
        raises(ValueError, 'array([]).max()')
        assert (a.sum(0) == [30, 35, 40]).all()
        assert (a.sum(axis=0) == [30, 35, 40]).all()
        assert (a.sum(1) == [3, 12, 21, 30, 39]).all()
        assert (a.sum(-1) == a.sum(-1)).all()
        assert (a.sum(-2) == a.sum(-2)).all()
        raises(ValueError, a.sum, -3)
        raises(ValueError, a.sum, 2)
        assert (a.max(0) == [12, 13, 14]).all()
        assert (a.max(1) == [2, 5, 8, 11, 14]).all()
        assert ((a + a).max() == 28)
        assert ((a + a).max(0) == [24, 26, 28]).all()
        assert ((a + a).sum(1) == [6, 24, 42, 60, 78]).all()
        assert (multiply.reduce(a) == array([0, 3640, 12320])).all()
        a = array(range(105)).reshape(3, 5, 7)
        assert (a[:, 1, :].sum(0) == [126, 129, 132, 135, 138, 141, 144]).all()
        assert (a[:, 1, :].sum(1) == [70, 315, 560]).all()
        raises (ValueError, 'a[:, 1, :].sum(2)')
        assert ((a + a).T.sum(2).T == (a + a).sum(0)).all()
        assert (a.reshape(1,-1).sum(0) == range(105)).all()
        assert (a.reshape(1,-1).sum(1) == 5460)
        assert (array([[1,2],[3,4]]).prod(0) == [3, 8]).all()
        assert (array([[1,2],[3,4]]).prod(1) == [2, 12]).all()

    def test_identity(self):
        from _numpypy import identity, array
        from _numpypy import int32, float64, dtype
        a = identity(0)
        assert len(a) == 0
        assert a.dtype == dtype('float64')
        assert a.shape == (0, 0)
        b = identity(1, dtype=int32)
        assert len(b) == 1
        assert b[0][0] == 1
        assert b.shape == (1, 1)
        assert b.dtype == dtype('int32')
        c = identity(2)
        assert c.shape == (2, 2)
        assert (c == [[1, 0], [0, 1]]).all()
        d = identity(3, dtype='int32')
        assert d.shape == (3, 3)
        assert d.dtype == dtype('int32')
        assert (d == [[1, 0, 0], [0, 1, 0], [0, 0, 1]]).all()
   
    def test_eye(self):
        from _numpypy import eye
        from _numpypy import int32, dtype
        a = eye(0)
        assert len(a) == 0
        assert a.dtype == dtype('float64')
        assert a.shape == (0, 0)
        b = eye(1, dtype=int32)
        assert len(b) == 1
        assert b[0][0] == 1
        assert b.shape == (1, 1)
        assert b.dtype == dtype('int32')
        c = eye(2)
        assert c.shape == (2, 2)
        assert (c == [[1, 0], [0, 1]]).all()
        d = eye(3, dtype='int32')
        assert d.shape == (3, 3)
        assert d.dtype == dtype('int32')
        assert (d == [[1, 0, 0], [0, 1, 0], [0, 0, 1]]).all()
        e = eye(3, 4)
        assert e.shape == (3, 4)
        assert (e == [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]).all()
        f = eye(2, 4, k=3)
        assert f.shape == (2, 4)
        assert (f == [[0, 0, 0, 1], [0, 0, 0, 0]]).all()
        g = eye(3, 4, k=-1)
        assert g.shape == (3, 4)
        assert (g == [[0, 0, 0, 0], [1, 0, 0, 0], [0, 1, 0, 0]]).all()




    def test_prod(self):
        from _numpypy import array
        a = array(range(1, 6))
        assert a.prod() == 120.0
        assert a[:4].prod() == 24.0

    def test_max(self):
        from _numpypy import array
        a = array([-1.2, 3.4, 5.7, -3.0, 2.7])
        assert a.max() == 5.7
        b = array([])
        raises(ValueError, "b.max()")

    def test_max_add(self):
        from _numpypy import array
        a = array([-1.2, 3.4, 5.7, -3.0, 2.7])
        assert (a + a).max() == 11.4

    def test_min(self):
        from _numpypy import array
        a = array([-1.2, 3.4, 5.7, -3.0, 2.7])
        assert a.min() == -3.0
        b = array([])
        raises(ValueError, "b.min()")

    def test_argmax(self):
        from _numpypy import array
        a = array([-1.2, 3.4, 5.7, -3.0, 2.7])
        r = a.argmax()
        assert r == 2
        b = array([])
        raises(ValueError, b.argmax)

        a = array(range(-5, 5))
        r = a.argmax()
        assert r == 9
        b = a[::2]
        r = b.argmax()
        assert r == 4
        r = (a + a).argmax()
        assert r == 9
        a = array([1, 0, 0])
        assert a.argmax() == 0
        a = array([0, 0, 1])
        assert a.argmax() == 2

    def test_argmin(self):
        from _numpypy import array
        a = array([-1.2, 3.4, 5.7, -3.0, 2.7])
        assert a.argmin() == 3
        b = array([])
        raises(ValueError, "b.argmin()")

    def test_all(self):
        from _numpypy import array
        a = array(range(5))
        assert a.all() == False
        a[0] = 3.0
        assert a.all() == True
        b = array([])
        assert b.all() == True

    def test_any(self):
        from _numpypy import array, zeros
        a = array(range(5))
        assert a.any() == True
        b = zeros(5)
        assert b.any() == False
        c = array([])
        assert c.any() == False

    def test_dtype_guessing(self):
        from _numpypy import array, dtype, float64, int8, bool_

        assert array([True]).dtype is dtype(bool)
        assert array([True, False]).dtype is dtype(bool)
        assert array([True, 1]).dtype is dtype(int)
        assert array([1, 2, 3]).dtype is dtype(int)
        #assert array([1L, 2, 3]).dtype is dtype(long)
        assert array([1.2, True]).dtype is dtype(float)
        assert array([1.2, 5]).dtype is dtype(float)
        assert array([]).dtype is dtype(float)
        assert array([float64(2)]).dtype is dtype(float)
        assert array([int8(3)]).dtype is dtype("int8")
        assert array([bool_(True)]).dtype is dtype(bool)
        assert array([bool_(True), 3.0]).dtype is dtype(float)

    def test_comparison(self):
        import operator
        from _numpypy import array, dtype

        a = array(range(5))
        b = array(range(5), float)
        for func in [
            operator.eq, operator.ne, operator.lt, operator.le, operator.gt,
            operator.ge
        ]:
            c = func(a, 3)
            assert c.dtype is dtype(bool)
            for i in xrange(5):
                assert c[i] == func(a[i], 3)

            c = func(b, 3)
            assert c.dtype is dtype(bool)
            for i in xrange(5):
                assert c[i] == func(b[i], 3)

    def test_nonzero(self):
        from _numpypy import array
        a = array([1, 2])
        raises(ValueError, bool, a)
        raises(ValueError, bool, a == a)
        assert bool(array(1))
        assert not bool(array(0))
        assert bool(array([1]))
        assert not bool(array([0]))

    def test_slice_assignment(self):
        from _numpypy import array
        a = array(range(5))
        a[::-1] = a
        assert (a == [4, 3, 2, 1, 0]).all()
        # but we force intermediates
        a = array(range(5))
        a[::-1] = a + a
        assert (a == [8, 6, 4, 2, 0]).all()

    def test_virtual_views(self):
        from _numpypy import arange
        a = arange(15)
        c = (a + a)
        d = c[::2]
        assert d[3] == 12
        c[6] = 5
        assert d[3] == 5
        a = arange(15)
        c = (a + a)
        d = c[::2][::2]
        assert d[1] == 8
        b = a + a
        c = b[::2]
        c[:] = 3
        assert b[0] == 3
        assert b[1] == 2

    def test_realimag_views(self):
        from _numpypy import arange, array
        a = arange(15)
        b = a.real
        b[5]=50
        assert a[5] == 50
        b = a.imag
        assert b[7] == 0
        raises(RuntimeError, 'b[7] = -2')
        raises(TypeError, 'a.imag = -2')
        a = array(['abc','def'],dtype='S3')
        b = a.real
        assert a[0] == b[0]
        assert a[1] == b[1]
        b[1] = 'xyz'
        assert a[1] == 'xyz'
        assert a.imag[0] == 'abc'
        raises(TypeError, 'a.imag = "qop"')
        a=array([[1+1j, 2-3j, 4+5j],[-6+7j, 8-9j, -2-1j]]) 
        assert a.real[0,1] == 2
        a.real[0,1] = -20
        assert a[0,1].real == -20
        b = a.imag
        assert b[1,2] == -1
        b[1,2] = 30
        assert a[1,2].imag == 30
        a.real = 13
        assert a[1,1].real == 13
        a=array([1+1j, 2-3j, 4+5j, -6+7j, 8-9j, -2-1j]) 
        a.real = 13
        assert a[3].real == 13
        a.imag = -5
        a.imag[3] = -10
        assert a[3].imag == -10
        assert a[2].imag == -5

    def test_tolist_scalar(self):
        from _numpypy import int32, bool_
        x = int32(23)
        assert x.tolist() == 23
        assert type(x.tolist()) is int
        y = bool_(True)
        assert y.tolist() is True

    def test_tolist_zerodim(self):
        from _numpypy import array
        x = array(3)
        assert x.tolist() == 3
        assert type(x.tolist()) is int

    def test_tolist_singledim(self):
        from _numpypy import array
        a = array(range(5))
        assert a.tolist() == [0, 1, 2, 3, 4]
        assert type(a.tolist()[0]) is int
        b = array([0.2, 0.4, 0.6])
        assert b.tolist() == [0.2, 0.4, 0.6]

    def test_tolist_multidim(self):
        from _numpypy import array
        a = array([[1, 2], [3, 4]])
        assert a.tolist() == [[1, 2], [3, 4]]

    def test_tolist_view(self):
        from _numpypy import array
        a = array([[1, 2], [3, 4]])
        assert (a + a).tolist() == [[2, 4], [6, 8]]

    def test_tolist_slice(self):
        from _numpypy import array
        a = array([[17.1, 27.2], [40.3, 50.3]])
        assert a[:, 0].tolist() == [17.1, 40.3]
        assert a[0].tolist() == [17.1, 27.2]

    def test_var(self):
        from _numpypy import array, arange
        a = array(range(10))
        assert a.var() == 8.25
        a = array([5.0])
        assert a.var() == 0.0
        a = arange(10).reshape(5, 2)
        assert a.var() == 8.25
        assert (a.var(0) == [8, 8]).all()
        assert (a.var(1) == [.25] * 5).all()

    def test_concatenate(self):
        from numpypy import array, concatenate, dtype
        a1 = array([0,1,2])
        a2 = array([3,4,5])
        a = concatenate((a1, a2))
        assert len(a) == 6
        assert (a == [0,1,2,3,4,5]).all()
        assert a.dtype is dtype(int)
        b1 = array([[1, 2], [3, 4]])
        b2 = array([[5, 6]])
        b = concatenate((b1, b2), axis=0)
        assert (b == [[1, 2],[3, 4],[5, 6]]).all()
        c = concatenate((b1, b2.T), axis=1)
        assert (c == [[1, 2, 5],[3, 4, 6]]).all()
        d = concatenate(([0],[1]))
        assert (d == [0,1]).all()
        e1 = array([[0,1],[2,3]])
        e = concatenate(e1)
        assert (e == [0,1,2,3]).all()
        f1 = array([0,1])
        f = concatenate((f1, [2], f1, [7]))
        assert (f == [0,1,2,0,1,7]).all()

        bad_axis = raises(IndexError, concatenate, (a1,a2), axis=1)
        assert str(bad_axis.value) == "axis 1 out of bounds [0, 1)"

        concat_zero = raises(ValueError, concatenate, ())
        assert str(concat_zero.value) == \
            "need at least one array to concatenate"

        dims_disagree = raises(ValueError, concatenate, (a1, b1), axis=0)
        assert str(dims_disagree.value) == \
            "all the input arrays must have same number of dimensions"
        a = array([1, 2, 3, 4, 5, 6])
        a = (a + a)[::2]
        b = concatenate((a[:3], a[-3:]))
        assert (b == [2, 6, 10, 2, 6, 10]).all()

    def test_std(self):
        from _numpypy import array
        a = array(range(10))
        assert a.std() == 2.8722813232690143
        a = array([5.0])
        assert a.std() == 0.0

    def test_flatten(self):
        from _numpypy import array

        assert array(3).flatten().shape == (1,)
        a = array([[1, 2], [3, 4]])
        b = a.flatten()
        c = a.ravel()
        a[0, 0] = 15
        assert b[0] == 1
        assert c[0] == 15
        a = array([[1, 2, 3], [4, 5, 6]])
        assert (a.flatten() == [1, 2, 3, 4, 5, 6]).all()
        a = array([[[1, 2], [3, 4]], [[5, 6], [7, 8]]])
        assert (a.flatten() == [1, 2, 3, 4, 5, 6, 7, 8]).all()
        a = array([1, 2, 3, 4, 5, 6, 7, 8])
        assert (a[::2].flatten() == [1, 3, 5, 7]).all()
        a = array([1, 2, 3])
        assert ((a + a).flatten() == [2, 4, 6]).all()
        a = array(2)
        assert (a.flatten() == [2]).all()
        a = array([[1, 2], [3, 4]])
        assert (a.T.flatten() == [1, 3, 2, 4]).all()

    def test_itemsize(self):
        from _numpypy import ones, dtype, array

        for obj in [float, bool, int]:
            assert ones(1, dtype=obj).itemsize == dtype(obj).itemsize
        assert (ones(1) + ones(1)).itemsize == 8
        assert array(1.0).itemsize == 8
        assert ones(1)[:].itemsize == 8

    def test_nbytes(self):
        from _numpypy import array, ones

        assert ones(1).nbytes == 8
        assert ones((2, 2)).nbytes == 32
        assert ones((2, 2))[1:,].nbytes == 16
        assert (ones(1) + ones(1)).nbytes == 8
        assert array(3.0).nbytes == 8

    def test_repeat(self):
        from _numpypy import repeat, array
        assert (repeat([[1, 2], [3, 4]], 3) == [1, 1, 1, 2, 2, 2,
                                                3, 3, 3, 4, 4, 4]).all()
        assert (repeat([[1, 2], [3, 4]], 2, axis=0) == [[1, 2], [1, 2], [3, 4],
                                                        [3, 4]]).all()
        assert (repeat([[1, 2], [3, 4]], 2, axis=1) == [[1, 1, 2, 2], [3, 3,
                                                        4, 4]]).all()
        assert (array([1, 2]).repeat(2) == array([1, 1, 2, 2])).all()


    def test_swapaxes(self):
        from _numpypy import array
        # testcases from numpy docstring
        x = array([[1, 2, 3]])
        assert (x.swapaxes(0, 1) == array([[1], [2], [3]])).all() 
        x = array([[[0,1],[2,3]],[[4,5],[6,7]]]) # shape = (2, 2, 2)
        assert (x.swapaxes(0, 2) == array([[[0, 4], [2, 6]], 
                                           [[1, 5], [3, 7]]])).all() 
        assert (x.swapaxes(0, 1) == array([[[0, 1], [4, 5]], 
                                           [[2, 3], [6, 7]]])).all()
        assert (x.swapaxes(1, 2) == array([[[0, 2], [1, 3]], 
                                           [[4, 6],[5, 7]]])).all()

        # more complex shape i.e. (2, 2, 3)
        x = array([[[1, 2, 3], [4, 5, 6]], [[7, 8, 9], [10, 11, 12]]]) 
        assert (x.swapaxes(0, 1) == array([[[1, 2, 3], [7, 8, 9]], 
                                           [[4, 5, 6], [10, 11, 12]]])).all() 
        assert (x.swapaxes(0, 2) == array([[[1, 7], [4, 10]], [[2, 8], [5, 11]], 
                                           [[3, 9], [6, 12]]])).all() 
        assert (x.swapaxes(1, 2) == array([[[1, 4], [2, 5], [3, 6]], 
                                           [[7, 10], [8, 11],[9, 12]]])).all() 
        
        # test slice
        assert (x[0:1,0:2].swapaxes(0,2) == array([[[1], [4]], [[2], [5]], 
                                                   [[3], [6]]])).all()
        # test virtual
        assert ((x + x).swapaxes(0,1) == array([[[ 2,  4,  6], [14, 16, 18]], 
                                         [[ 8, 10, 12], [20, 22, 24]]])).all()
        assert array(1).swapaxes(10, 12) == 1

    def test_filter_bug(self):
        from numpypy import array
        a = array([1.0,-1.0])
        a[a<0] = -a[a<0]
        assert (a == [1, 1]).all()

    def test_int_array_index(self):
        from numpypy import array, arange, zeros
        b = arange(10)[array([3, 2, 1, 5])]
        assert (b == [3, 2, 1, 5]).all()
        raises(IndexError, "arange(10)[array([10])]")
        assert (arange(10)[[-5, -3]] == [5, 7]).all()
        raises(IndexError, "arange(10)[[-11]]")
        a = arange(1)
        a[[0, 0]] += 1
        assert a[0] == 1
        assert (zeros(1)[[]] == []).all()

    def test_int_array_index_setitem(self):
        from numpypy import array, arange, zeros
        a = arange(10)
        a[[3, 2, 1, 5]] = zeros(4, dtype=int)
        assert (a == [0, 0, 0, 0, 4, 0, 6, 7, 8, 9]).all()
        a[[-9, -8]] = [1, 1]
        assert (a == [0, 1, 1, 0, 4, 0, 6, 7, 8, 9]).all()
        raises(IndexError, "arange(10)[array([10])] = 3")
        raises(IndexError, "arange(10)[[-11]] = 3")

    def test_bool_array_index(self):
        from numpypy import arange, array
        b = arange(10)
        assert (b[array([True, False, True])] == [0, 2]).all()
        raises(ValueError, "array([1, 2])[array([True, True, True])]")
        raises(ValueError, "b[array([[True, False], [True, False]])]")

    def test_bool_array_index_setitem(self):
        from numpypy import arange, array
        b = arange(5)
        b[array([True, False, True])] = [20, 21, 0, 0, 0, 0, 0]
        assert (b == [20, 1, 21, 3, 4]).all() 
        raises(ValueError, "array([1, 2])[array([True, False, True])] = [1, 2, 3]")

    def test_weakref(self):
        import _weakref
        from numpypy import array
        a = array([1, 2, 3])
        assert _weakref.ref(a)
        a = array(42)
        assert _weakref.ref(a)

class AppTestMultiDim(BaseNumpyAppTest):
    def test_init(self):
        import _numpypy
        a = _numpypy.zeros((2, 2))
        assert len(a) == 2

    def test_shape(self):
        import _numpypy
        assert _numpypy.zeros(1).shape == (1,)
        assert _numpypy.zeros((2, 2)).shape == (2, 2)
        assert _numpypy.zeros((3, 1, 2)).shape == (3, 1, 2)
        assert _numpypy.array([[1], [2], [3]]).shape == (3, 1)
        assert len(_numpypy.zeros((3, 1, 2))) == 3
        raises(TypeError, len, _numpypy.zeros(()))
        raises(ValueError, _numpypy.array, [[1, 2], 3], dtype=float)

    def test_getsetitem(self):
        import _numpypy
        a = _numpypy.zeros((2, 3, 1))
        raises(IndexError, a.__getitem__, (2, 0, 0))
        raises(IndexError, a.__getitem__, (0, 3, 0))
        raises(IndexError, a.__getitem__, (0, 0, 1))
        assert a[1, 1, 0] == 0
        a[1, 2, 0] = 3
        assert a[1, 2, 0] == 3
        assert a[1, 1, 0] == 0
        assert a[1, -1, 0] == 3

    def test_slices(self):
        import _numpypy
        a = _numpypy.zeros((4, 3, 2))
        raises(IndexError, a.__getitem__, (4,))
        raises(IndexError, a.__getitem__, (3, 3))
        raises(IndexError, a.__getitem__, (slice(None), 3))
        a[0, 1, 1] = 13
        a[1, 2, 1] = 15
        b = a[0]
        assert len(b) == 3
        assert b.shape == (3, 2)
        assert b[1, 1] == 13
        b = a[1]
        assert b.shape == (3, 2)
        assert b[2, 1] == 15
        b = a[:, 1]
        assert b.shape == (4, 2)
        assert b[0, 1] == 13
        b = a[:, 1, :]
        assert b.shape == (4, 2)
        assert b[0, 1] == 13
        b = a[1, 2]
        assert b[1] == 15
        b = a[:]
        assert b.shape == (4, 3, 2)
        assert b[1, 2, 1] == 15
        assert b[0, 1, 1] == 13
        b = a[:][:, 1][:]
        assert b[2, 1] == 0.0
        assert b[0, 1] == 13
        raises(IndexError, b.__getitem__, (4, 1))
        assert a[0][1][1] == 13
        assert a[1][2][1] == 15

    def test_setitem_slice(self):
        import _numpypy
        a = _numpypy.zeros((3, 4))
        a[1] = [1, 2, 3, 4]
        assert a[1, 2] == 3
        raises(TypeError, a[1].__setitem__, [1, 2, 3])
        a = _numpypy.array([[1, 2], [3, 4]])
        assert (a == [[1, 2], [3, 4]]).all()
        a[1] = _numpypy.array([5, 6])
        assert (a == [[1, 2], [5, 6]]).all()
        a[:, 1] = _numpypy.array([8, 10])
        assert (a == [[1, 8], [5, 10]]).all()
        a[0, :: -1] = _numpypy.array([11, 12])
        assert (a == [[12, 11], [5, 10]]).all()

    def test_ufunc(self):
        from _numpypy import array
        a = array([[1, 2], [3, 4], [5, 6]])
        assert ((a + a) == \
            array([[1 + 1, 2 + 2], [3 + 3, 4 + 4], [5 + 5, 6 + 6]])).all()

    def test_getitem_add(self):
        from _numpypy import array
        a = array([[1, 2], [3, 4], [5, 6], [7, 8], [9, 10]])
        assert (a + a)[1, 1] == 8

    def test_ufunc_negative(self):
        from _numpypy import array, negative
        a = array([[1, 2], [3, 4]])
        b = negative(a + a)
        assert (b == [[-2, -4], [-6, -8]]).all()

    def test_getitem_3(self):
        from _numpypy import array
        a = array([[1, 2], [3, 4], [5, 6], [7, 8],
                   [9, 10], [11, 12], [13, 14]])
        b = a[::2]
        assert (b == [[1, 2], [5, 6], [9, 10], [13, 14]]).all()
        c = b + b
        assert c[1][1] == 12

    def test_multidim_ones(self):
        from _numpypy import ones
        a = ones((1, 2, 3))
        assert a[0, 1, 2] == 1.0

    def test_multidim_setslice(self):
        from _numpypy import zeros, ones
        a = zeros((3, 3))
        b = ones((3, 3))
        a[:, 1:3] = b[:, 1:3]
        assert (a == [[0, 1, 1], [0, 1, 1], [0, 1, 1]]).all()
        a = zeros((3, 3))
        b = ones((3, 3))
        a[:, ::2] = b[:, ::2]
        assert (a == [[1, 0, 1], [1, 0, 1], [1, 0, 1]]).all()

    def test_broadcast_ufunc(self):
        from _numpypy import array
        a = array([[1, 2], [3, 4], [5, 6]])
        b = array([5, 6])
        c = ((a + b) == [[1 + 5, 2 + 6], [3 + 5, 4 + 6], [5 + 5, 6 + 6]])
        assert c.all()

    def test_broadcast_setslice(self):
        from _numpypy import zeros, ones
        a = zeros((10, 10))
        b = ones(10)
        a[:, :] = b
        assert a[3, 5] == 1

    def test_broadcast_shape_agreement(self):
        from _numpypy import zeros, array
        a = zeros((3, 1, 3))
        b = array(((10, 11, 12), (20, 21, 22), (30, 31, 32)))
        c = ((a + b) == [b, b, b])
        assert c.all()
        a = array((((10, 11, 12), ), ((20, 21, 22), ), ((30, 31, 32), )))
        assert(a.shape == (3, 1, 3))
        d = zeros((3, 3))
        c = ((a + d) == [b, b, b])
        c = ((a + d) == array([[[10., 11., 12.]] * 3,
                               [[20., 21., 22.]] * 3, [[30., 31., 32.]] * 3]))
        assert c.all()

    def test_broadcast_scalar(self):
        from _numpypy import zeros
        a = zeros((4, 5), 'd')
        a[:, 1] = 3
        assert a[2, 1] == 3
        assert a[0, 2] == 0
        a[0, :] = 5
        assert a[0, 3] == 5
        assert a[2, 1] == 3
        assert a[3, 2] == 0

    def test_broadcast_call2(self):
        from _numpypy import zeros, ones
        a = zeros((4, 1, 5))
        b = ones((4, 3, 5))
        b[:] = (a + a)
        assert (b == zeros((4, 3, 5))).all()

    def test_broadcast_virtualview(self):
        from _numpypy import arange, zeros
        a = arange(8).reshape([2, 2, 2])
        b = (a + a)[1, 1]
        c = zeros((2, 2, 2))
        c[:] = b
        assert (c == [[[12, 14], [12, 14]], [[12, 14], [12, 14]]]).all()

    def test_argmax(self):
        from _numpypy import array
        a = array([[1, 2], [3, 4], [5, 6]])
        assert a.argmax() == 5
        assert a[:2, ].argmax() == 3

    def test_broadcast_wrong_shapes(self):
        from _numpypy import zeros
        a = zeros((4, 3, 2))
        b = zeros((4, 2))
        exc = raises(ValueError, lambda: a + b)
        assert str(exc.value).startswith("operands could not be broadcast")

    def test_reduce(self):
        from _numpypy import array
        a = array([[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]])
        assert a.sum() == (13 * 12) / 2
        b = a[1:, 1::2]
        c = b + b
        assert c.sum() == (6 + 8 + 10 + 12) * 2
        assert isinstance(c.sum(dtype='f8'), float)

    def test_transpose(self):
        from _numpypy import array
        a = array(((range(3), range(3, 6)),
                   (range(6, 9), range(9, 12)),
                   (range(12, 15), range(15, 18)),
                   (range(18, 21), range(21, 24))))
        assert a.shape == (4, 2, 3)
        b = a.T
        assert b.shape == (3, 2, 4)
        assert(b[0, :, 0] == [0, 3]).all()
        b[:, 0, 0] = 1000
        assert(a[0, 0, :] == [1000, 1000, 1000]).all()
        a = array(range(5))
        b = a.T
        assert(b == range(5)).all()
        a = array((range(10), range(20, 30)))
        b = a.T
        assert(b[:, 0] == a[0, :]).all()
        assert (a.transpose() == b).all()

    def test_flatiter(self):
        from _numpypy import array, flatiter, arange
        a = array([[10, 30], [40, 60]])
        f_iter = a.flat
        assert f_iter.next() == 10
        assert f_iter.next() == 30
        assert f_iter.next() == 40
        assert f_iter.next() == 60
        raises(StopIteration, "f_iter.next()")
        raises(TypeError, "flatiter()")
        s = 0
        for k in a.flat:
            s += k
        assert s == 140
        a = arange(10).reshape(5, 2)
        raises(IndexError, 'a.flat[(1, 2)]')
        assert a.flat.base is a

    def test_flatiter_array_conv(self):
        from _numpypy import array, dot
        a = array([1, 2, 3])
        assert dot(a.flat, a.flat) == 14

    def test_flatiter_varray(self):
        from _numpypy import ones
        a = ones((2, 2))
        assert list(((a + a).flat)) == [2, 2, 2, 2]

    def test_flatiter_getitem(self):
        from _numpypy import arange
        a = arange(10)
        assert a.flat[3] == 3
        assert a[2:].flat[3] == 5
        assert (a + a).flat[3] == 6
        assert a[::2].flat[3] == 6
        assert a.reshape(2,5).flat[3] == 3
        b = a.reshape(2,5).flat
        b.next()
        b.next()
        b.next()
        assert b.index == 3
        assert b.coords == (0, 3)
        assert b[3] == 3
        assert (b[::3] == [0, 3, 6, 9]).all()
        assert (b[2::5] == [2, 7]).all()
        assert b[-2] == 8
        raises(IndexError, "b[11]")
        raises(IndexError, "b[-11]")
        raises(IndexError, 'b[0, 1]')
        assert b.index == 0
        assert b.coords == (0, 0)

    def test_flatiter_setitem(self):
        from _numpypy import arange, array
        a = arange(12).reshape(3,4)
        b = a.T.flat
        b[6::2] = [-1, -2]
        assert (a == [[0, 1, -1, 3], [4, 5, 6, -1], [8, 9, -2, 11]]).all()
        b[0:2] = [[[100]]]
        assert(a[0,0] == 100)
        assert(a[1,0] == 100)

    def test_flatiter_ops(self):
        from _numpypy import arange, array
        a = arange(12).reshape(3,4)
        b = a.T.flat
        assert (b == [0,  4, 8, 1, 5, 9, 2, 6, 10, 3, 7, 11]).all()
        assert not (b != [0,  4, 8, 1, 5, 9, 2, 6, 10, 3, 7, 11]).any()
        assert ((b >= range(12)) == [True, True, True,False, True, True,
                             False, False, True, False, False, True]).all()
        assert ((b < range(12)) != [True, True, True,False, True, True,
                             False, False, True, False, False, True]).all()
        assert ((b <= range(12)) != [False, True, True,False, True, True,
                            False, False, True, False, False, False]).all()
        assert ((b > range(12)) == [False, True, True,False, True, True,
                            False, False, True, False, False, False]).all()
    def test_flatiter_view(self):
        from _numpypy import arange
        a = arange(10).reshape(5, 2)
        assert (a[::2].flat == [0, 1, 4, 5, 8, 9]).all()

    def test_flatiter_transpose(self):
        from _numpypy import arange
        a = arange(10).reshape(2, 5).T
        b = a.flat
        assert (b[:5] == [0, 5, 1, 6, 2]).all()
        b.next()
        b.next()
        b.next()
        assert b.index == 3
        assert b.coords == (1, 1)

    def test_flatiter_len(self):
        from _numpypy import arange

        assert len(arange(10).flat) == 10
        assert len(arange(10).reshape(2, 5).flat) == 10
        assert len(arange(10)[:2].flat) == 2
        assert len((arange(2) + arange(2)).flat) == 2

    def test_slice_copy(self):
        from _numpypy import zeros
        a = zeros((10, 10))
        b = a[0].copy()
        assert (b == zeros(10)).all()

    def test_array_interface(self):
        from _numpypy import array
        a = array([1, 2, 3])
        i = a.__array_interface__
        assert isinstance(i['data'][0], int)
        a = a[::2]
        i = a.__array_interface__
        assert isinstance(i['data'][0], int)

    def test_array_indexing_one_elem(self):
        skip("not yet")
        from _numpypy import array, arange
        raises(IndexError, 'arange(3)[array([3.5])]')
        a = arange(3)[array([1])]
        assert a == 1
        assert a[0] == 1
        raises(IndexError,'arange(3)[array([15])]')
        assert arange(3)[array([-3])] == 0
        raises(IndexError,'arange(3)[array([-15])]')
        assert arange(3)[array(1)] == 1

    def test_fill(self):
        from _numpypy import array
        a = array([1, 2, 3])
        a.fill(10)
        assert (a == [10, 10, 10]).all()
        a.fill(False)
        assert (a == [0, 0, 0]).all()
        b = a[:1]
        b.fill(4)
        assert (b == [4]).all()
        assert (a == [4, 0, 0]).all()

        c = b + b
        c.fill(27)
        assert (c == [27]).all()

        d = array(10)
        d.fill(100)
        assert d == 100

    def test_array_indexing_bool(self):
        from _numpypy import arange
        a = arange(10)
        assert (a[a > 3] == [4, 5, 6, 7, 8, 9]).all()
        a = arange(10).reshape(5, 2)
        assert (a[a > 3] == [4, 5, 6, 7, 8, 9]).all()
        assert (a[a & 1 == 1] == [1, 3, 5, 7, 9]).all()

    def test_array_indexing_bool_setitem(self):
        from _numpypy import arange, array
        a = arange(6)
        a[a > 3] = 15
        assert (a == [0, 1, 2, 3, 15, 15]).all()
        a = arange(6).reshape(3, 2)
        a[a & 1 == 1] = array([8, 9, 10])
        assert (a == [[0, 8], [2, 9], [4, 10]]).all()

    def test_array_indexing_bool_setitem_multidim(self):
        from _numpypy import arange
        a = arange(10).reshape(5, 2)
        a[a & 1 == 0] = 15
        assert (a == [[15, 1], [15, 3], [15, 5], [15, 7], [15, 9]]).all()

    def test_array_indexing_bool_setitem_2(self):
        from _numpypy import arange
        a = arange(10).reshape(5, 2)
        a = a[::2]
        a[a & 1 == 0] = 15
        assert (a == [[15, 1], [15, 5], [15, 9]]).all()

    def test_copy_kwarg(self):
        from _numpypy import array
        x = array([1, 2, 3])
        assert (array(x) == x).all()
        assert array(x) is not x
        assert array(x, copy=False) is x
        assert array(x, copy=True) is not x

    def test_ravel(self):
        from _numpypy import arange
        assert (arange(3).ravel() == arange(3)).all()
        assert (arange(6).reshape(2, 3).ravel() == arange(6)).all()
        assert (arange(6).reshape(2, 3).T.ravel() == [0, 3, 1, 4, 2, 5]).all()

    def test_take(self):
        from _numpypy import arange
        try:
            arange(10).take([0])
        except NotImplementedError:
            skip("we wait for int-based indexing")
        assert (arange(10).take([1, 2, 1, 1]) == [1, 2, 1, 1]).all()
        raises(IndexError, "arange(3).take([15])")
        a = arange(6).reshape(2, 3)
        assert (a.take([1, 0, 3]) == [1, 0, 3]).all()
        assert ((a + a).take([3]) == [6]).all()
        a = arange(12).reshape(2, 6)
        assert (a[:,::2].take([3, 2, 1]) == [6, 4, 2]).all()

    def test_compress(self):
        from _numpypy import arange
        a = arange(10)
        assert (a.compress([True, False, True]) == [0, 2]).all()
        assert (a.compress([1, 0, 13]) == [0, 2]).all()
        assert (a.compress([1, 0, 13.5]) == [0, 2]).all()
        a = arange(10).reshape(2, 5)
        assert (a.compress([True, False, True]) == [0, 2]).all()
        raises((IndexError, ValueError), "a.compress([1] * 100)")

    def test_item(self):
        from _numpypy import array
        assert array(3).item() == 3
        assert type(array(3).item()) is int
        assert type(array(True).item()) is bool
        assert type(array(3.5).item()) is float
        raises(IndexError, "array(3).item(15)")
        raises(IndexError, "array([1, 2, 3]).item()")
        assert array([3]).item(0) == 3
        assert type(array([3]).item(0)) is int
        assert array([1, 2, 3]).item(-1) == 3
        a = array([1, 2, 3])
        assert a[::2].item(1) == 3
        assert (a + a).item(1) == 4
        raises(IndexError, "array(5).item(1)")
        assert array([1]).item() == 1

    def test_int_array_index(self):
        from _numpypy import array
        assert (array([])[[]] == []).all()
        a = array([[1, 2], [3, 4], [5, 6]])
        assert (a[slice(0, 3), [0, 0]] == [[1, 1], [3, 3], [5, 5]]).all()
        assert (a[array([0, 2]), slice(0, 2)] == [[1, 2], [5, 6]]).all()
        b = a[array([0, 0])]
        assert (b == [[1, 2], [1, 2]]).all()
        assert (a[[[0, 1], [0, 0]]] == array([1, 3])).all()
        assert (a[array([0, 2])] == [[1, 2], [5, 6]]).all()
        assert (a[array([0, 2]), 1] == [2, 6]).all()
        assert (a[array([0, 2]), array([1])] == [2, 6]).all()

    def test_int_array_index_setitem(self):
        from _numpypy import array
        a = array([[1, 2], [3, 4], [5, 6]])
        a[slice(0, 3), [0, 0]] = [[0, 0], [0, 0], [0, 0]]
        assert (a == [[0, 2], [0, 4], [0, 6]]).all()
        a = array([[1, 2], [3, 4], [5, 6]])
        a[array([0, 2]), slice(0, 2)] = [[10, 11], [12, 13]]
        assert (a == [[10, 11], [3, 4], [12, 13]]).all()

class AppTestSupport(BaseNumpyAppTest):
    def setup_class(cls):
        import struct
        BaseNumpyAppTest.setup_class.im_func(cls)
        cls.w_data = cls.space.wrap(struct.pack('dddd', 1, 2, 3, 4))
        cls.w_fdata = cls.space.wrap(struct.pack('f', 2.3))
        cls.w_float16val = cls.space.wrap('\x00E') # 5.0 in float16 
        cls.w_float32val = cls.space.wrap(struct.pack('f', 5.2))
        cls.w_float64val = cls.space.wrap(struct.pack('d', 300.4))
        cls.w_ulongval = cls.space.wrap(struct.pack('L', 12))

    def test_fromstring(self):
        import sys
        from _numpypy import fromstring, array, uint8, float32, int32

        a = fromstring(self.data)
        for i in range(4):
            assert a[i] == i + 1
        b = fromstring('\x01\x02', dtype=uint8)
        assert a[0] == 1
        assert a[1] == 2
        c = fromstring(self.fdata, dtype=float32)
        assert c[0] == float32(2.3)
        d = fromstring("1 2", sep=' ', count=2, dtype=uint8)
        assert len(d) == 2
        assert d[0] == 1
        assert d[1] == 2
        e = fromstring('3, 4,5', dtype=uint8, sep=',')
        assert len(e) == 3
        assert e[0] == 3
        assert e[1] == 4
        assert e[2] == 5
        f = fromstring('\x01\x02\x03\x04\x05', dtype=uint8, count=3)
        assert len(f) == 3
        assert f[0] == 1
        assert f[1] == 2
        assert f[2] == 3
        g = fromstring("1  2    3 ", dtype=uint8, sep=" ")
        assert len(g) == 3
        assert g[0] == 1
        assert g[1] == 2
        assert g[2] == 3
        h = fromstring("1, , 2, 3", dtype=uint8, sep=",")
        assert (h == [1, 0, 2, 3]).all()
        i = fromstring("1    2 3", dtype=uint8, sep=" ")
        assert (i == [1, 2, 3]).all()
        j = fromstring("1\t\t\t\t2\t3", dtype=uint8, sep="\t")
        assert (j == [1, 2, 3]).all()
        k = fromstring("1,x,2,3", dtype=uint8, sep=",")
        assert (k == [1, 0]).all()
        l = fromstring("1,x,2,3", dtype='float32', sep=",")
        assert (l == [1.0, -1.0]).all()
        m = fromstring("1,,2,3", sep=",")
        assert (m == [1.0, -1.0, 2.0, 3.0]).all()
        n = fromstring("3.4 2.0 3.8 2.2", dtype=int32, sep=" ")
        assert (n == [3]).all()
        o = fromstring("1.0 2f.0f 3.8 2.2", dtype=float32, sep=" ")
        assert len(o) == 2
        assert o[0] == 1.0
        assert o[1] == 2.0
        p = fromstring("1.0,,2.0,3.0", sep=",")
        assert (p == [1.0, -1.0, 2.0, 3.0]).all()
        q = fromstring("1.0,,2.0,3.0", sep=" ")
        assert (q == [1.0]).all()
        r = fromstring("\x01\x00\x02", dtype='bool')
        assert (r == [True, False, True]).all()
        s = fromstring("1,2,3,,5", dtype=bool, sep=",")
        assert (s == [True, True, True, True, True]).all()
        t = fromstring("", bool)
        assert (t == []).all()
        u = fromstring("\x01\x00\x00\x00\x00\x00\x00\x00", dtype=int)
        if sys.maxint > 2 ** 31 - 1:
            assert (u == [1]).all()
        else:
            assert (u == [1, 0]).all()

    def test_fromstring_types(self):
        from _numpypy import (fromstring, int8, int16, int32, int64, uint8,
            uint16, uint32, float16, float32, float64, longfloat, array)
        a = fromstring('\xFF', dtype=int8)
        assert a[0] == -1
        b = fromstring('\xFF', dtype=uint8)
        assert b[0] == 255
        c = fromstring('\xFF\xFF', dtype=int16)
        assert c[0] == -1
        d = fromstring('\xFF\xFF', dtype=uint16)
        assert d[0] == 65535
        e = fromstring('\xFF\xFF\xFF\xFF', dtype=int32)
        assert e[0] == -1
        f = fromstring('\xFF\xFF\xFF\xFF', dtype=uint32)
        assert repr(f[0]) == '4294967295'
        g = fromstring('\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF', dtype=int64)
        assert g[0] == -1
        h = fromstring(self.float32val, dtype=float32)
        assert h[0] == float32(5.2)
        i = fromstring(self.float64val, dtype=float64)
        assert i[0] == float64(300.4)
        j = fromstring(self.ulongval, dtype='L')
        assert j[0] == 12
        k = fromstring(self.float16val, dtype=float16)
        assert k[0] == float16(5.)
        dt =  array([5],dtype=longfloat).dtype
        if dt.itemsize == 12:
            from _numpypy import float96
            m = fromstring('\x00\x00\x00\x00\x00\x00\x00\xa0\x01@\x00\x00', dtype=float96)
        elif dt.itemsize==16:
            from _numpypy import float128
            m = fromstring('\x00\x00\x00\x00\x00\x00\x00\xa0\x01@\x00\x00\x00\x00\x00\x00', dtype=float128)
        elif dt.itemsize == 8:
            skip('longfloat is float64')
        else:
            skip('unknown itemsize for longfloat')
        assert m[0] == longfloat(5.)

    def test_fromstring_invalid(self):
        from _numpypy import fromstring, uint16, uint8
        #default dtype is 64-bit float, so 3 bytes should fail
        raises(ValueError, fromstring, "\x01\x02\x03")
        #3 bytes is not modulo 2 bytes (int16)
        raises(ValueError, fromstring, "\x01\x03\x03", dtype=uint16)
        #5 bytes is larger than 3 bytes
        raises(ValueError, fromstring, "\x01\x02\x03", count=5, dtype=uint8)

    def test_tostring(self):
        from _numpypy import array
        assert array([1, 2, 3], 'i2').tostring() == '\x01\x00\x02\x00\x03\x00'
        assert array([1, 2, 3], 'i2')[::2].tostring() == '\x01\x00\x03\x00'
        assert array([1, 2, 3], '<i2')[::2].tostring() == '\x01\x00\x03\x00'
        assert array([1, 2, 3], '>i2')[::2].tostring() == '\x00\x01\x00\x03'

class AppTestRanges(BaseNumpyAppTest):
    def test_arange(self):
        from _numpypy import arange, array, dtype
        a = arange(3)
        assert (a == [0, 1, 2]).all()
        assert a.dtype is dtype(int)
        a = arange(3.0)
        assert (a == [0., 1., 2.]).all()
        assert a.dtype is dtype(float)
        a = arange(3, 7)
        assert (a == [3, 4, 5, 6]).all()
        assert a.dtype is dtype(int)
        a = arange(3, 7, 2)
        assert (a == [3, 5]).all()
        a = arange(3, dtype=float)
        assert (a == [0., 1., 2.]).all()
        assert a.dtype is dtype(float)
        a = arange(0, 0.8, 0.1)
        assert len(a) == 8
        assert arange(False, True, True).dtype is dtype(int)


class AppTestRepr(BaseNumpyAppTest):
    def setup_class(cls):
        if option.runappdirect:
            py.test.skip("Can't be run directly.")
        BaseNumpyAppTest.setup_class.im_func(cls)
        cache = get_appbridge_cache(cls.space)
        cls.old_array_repr = cache.w_array_repr
        cls.old_array_str = cache.w_array_str
        cache.w_array_str = None
        cache.w_array_repr = None

    def test_repr_str(self):
        from _numpypy import array
        assert repr(array([1, 2, 3])) == 'array([1, 2, 3])'
        assert str(array([1, 2, 3])) == 'array([1, 2, 3])'

    def teardown_class(cls):
        if option.runappdirect:
            return
        cache = get_appbridge_cache(cls.space)
        cache.w_array_repr = cls.old_array_repr
        cache.w_array_str = cls.old_array_str

class AppTestRecordDtype(BaseNumpyAppTest):
    def test_zeros(self):
        from _numpypy import zeros
        a = zeros(2, dtype=[('x', int), ('y', float)])
        raises(IndexError, 'a[0]["xyz"]')
        assert a[0]['x'] == 0
        assert a[0]['y'] == 0
        raises(ValueError, "a[0] = (1, 2, 3)")
        a[0]['x'] = 13
        assert a[0]['x'] == 13
        a[1] = (1, 2)
        assert a[1]['y'] == 2
        b = zeros(2, dtype=[('x', int), ('y', float)])
        b[1] = a[1]
        assert a[1]['y'] == 2

    def test_views(self):
        from _numpypy import array
        a = array([(1, 2), (3, 4)], dtype=[('x', int), ('y', float)])
        raises((IndexError, ValueError), 'array([1])["x"]')
        raises((IndexError, ValueError), 'a["z"]')
        assert a['x'][1] == 3
        assert a['y'][1] == 4
        a['x'][0] = 15
        assert a['x'][0] == 15
        b = a['x'] + a['y']
        assert (b == [15+2, 3+4]).all()
        assert b.dtype == float

    def test_assign_tuple(self):
        from _numpypy import zeros
        a = zeros((2, 3), dtype=[('x', int), ('y', float)])
        a[1, 2] = (1, 2)
        assert a['x'][1, 2] == 1
        assert a['y'][1, 2] == 2

    def test_creation_and_repr(self):
        from _numpypy import array
        a = array([(1, 2), (3, 4)], dtype=[('x', int), ('y', float)])
        assert repr(a[0]) == '(1, 2.0)'

    def test_nested_dtype(self):
        from _numpypy import zeros
        a = [('x', int), ('y', float)]
        b = [('x', int), ('y', a)]
        arr = zeros(3, dtype=b)
        arr[1]['x'] = 15
        assert arr[1]['x'] == 15
        arr[1]['y']['y'] = 3.5
        assert arr[1]['y']['y'] == 3.5
        assert arr[1]['y']['x'] == 0.0
        assert arr[1]['x'] == 15

    def test_string_record(self):
        from _numpypy import dtype, array
        d = dtype([('x', str), ('y', 'int32')])
        assert d.fields['x'] == (dtype(str), 0)
        assert d.fields['y'] == (dtype('int32'), 1)
        d = dtype([('x', 'S1'), ('y', 'int32')])
        assert d.fields['x'] == (dtype(str), 0)
        assert d.fields['y'] == (dtype('int32'), 1)
        a = array([('a', 2), ('c', 1)], dtype=d)
        assert a[1]['y'] == 1
        assert a[0]['x'] == 'a'

    def test_stringarray(self):
        from _numpypy import array
        a = array(['abc'],'S3')
        assert str(a.dtype) == '|S3'
        a = array(['abc'])
        assert str(a.dtype) == '|S3'
        a = array(['abc','defg','ab'])
        assert str(a.dtype) == '|S4'
        assert a[0] == 'abc'
        assert a[1] == 'defg'
        assert a[2] == 'ab'
        raises(TypeError, a, 'sum')
        raises(TypeError, 'a+a')

    def test_string_scalar(self):
        from _numpypy import array
        a = array('ffff')
        assert a.shape == ()

    def test_flexible_repr(self):
        # import overrides str(), repr() for array
        from _numpypy import array
        a = array(['abc'],'S3')
        s = repr(a)
        # simplify test for \n in repr
        assert s.replace('\n', '') == "array(['abc'],       dtype='|S3')"
        # but make sure it exists
        assert s.find('\n') == 15
        a = array(['abc','defg','ab'])
        s = repr(a)
        assert s.replace('\n', '') == \
                      "array(['abc', 'defg', 'ab'],       dtype='|S4')"
        
       
class AppTestPyPy(BaseNumpyAppTest):
    def setup_class(cls):
        if option.runappdirect and '__pypy__' not in sys.builtin_module_names:
            py.test.skip("pypy only test")
        BaseNumpyAppTest.setup_class.im_func(cls)
    
    def test_init_2(self):
        # this test is pypy only since in numpy it becomes an object dtype
        import _numpypy
        raises(ValueError, _numpypy.array, [[1], 2])
        raises(ValueError, _numpypy.array, [[1, 2], [3]])
        raises(ValueError, _numpypy.array, [[[1, 2], [3, 4], 5]])
        raises(ValueError, _numpypy.array, [[[1, 2], [3, 4], [5]]])
        a = _numpypy.array([[1, 2], [4, 5]])
        assert a[0, 1] == 2
        assert a[0][1] == 2
        a = _numpypy.array(([[[1, 2], [3, 4], [5, 6]]]))
        assert (a[0, 1] == [3, 4]).all()

    def test_from_shape_and_storage(self):
        from _numpypy import array, ndarray
        x = array([1, 2, 3, 4])
        addr, _ = x.__array_interface__['data']
        y = ndarray._from_shape_and_storage([2, 2], addr, x.dtype)
        assert y[0, 1] == 2
        y[0, 1] = 42
        assert x[1] == 42

    def test___pypy_data__(self):
        from _numpypy import array
        x = array([1, 2, 3, 4])
        x.__pypy_data__ is None
        obj = object()
        x.__pypy_data__ = obj
        assert x.__pypy_data__ is obj
        del x.__pypy_data__
        assert x.__pypy_data__ is None
    
