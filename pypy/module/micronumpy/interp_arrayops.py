
from pypy.module.micronumpy.base import convert_to_array, W_NDimArray
from pypy.module.micronumpy import loop, interp_ufuncs
from pypy.module.micronumpy.iter import Chunk, Chunks
from pypy.module.micronumpy.strides import shape_agreement
from pypy.interpreter.error import OperationError, operationerrfmt
from pypy.interpreter.gateway import unwrap_spec

def where(space, w_arr, w_x=None, w_y=None):
    """where(condition, [x, y])

    Return elements, either from `x` or `y`, depending on `condition`.

    If only `condition` is given, return ``condition.nonzero()``.

    Parameters
    ----------
    condition : array_like, bool
        When True, yield `x`, otherwise yield `y`.
    x, y : array_like, optional
        Values from which to choose. `x` and `y` need to have the same
        shape as `condition`.

    Returns
    -------
    out : ndarray or tuple of ndarrays
        If both `x` and `y` are specified, the output array contains
        elements of `x` where `condition` is True, and elements from
        `y` elsewhere.

        If only `condition` is given, return the tuple
        ``condition.nonzero()``, the indices where `condition` is True.

    See Also
    --------
    nonzero, choose

    Notes
    -----
    If `x` and `y` are given and input arrays are 1-D, `where` is
    equivalent to::

        [xv if c else yv for (c,xv,yv) in zip(condition,x,y)]

    Examples
    --------
    >>> np.where([[True, False], [True, True]],
    ...          [[1, 2], [3, 4]],
    ...          [[9, 8], [7, 6]])
    array([[1, 8],
           [3, 4]])

    >>> np.where([[0, 1], [1, 0]])
    (array([0, 1]), array([1, 0]))

    >>> x = np.arange(9.).reshape(3, 3)
    >>> np.where( x > 5 )
    (array([2, 2, 2]), array([0, 1, 2]))
    >>> x[np.where( x > 3.0 )]               # Note: result is 1D.
    array([ 4.,  5.,  6.,  7.,  8.])
    >>> np.where(x < 5, x, -1)               # Note: broadcasting.
    array([[ 0.,  1.,  2.],
           [ 3.,  4., -1.],
           [-1., -1., -1.]])

    
    NOTE: support for not passing x and y is unsupported
    """
    if space.is_none(w_y):
        if space.is_none(w_x):
            raise OperationError(space.w_NotImplementedError, space.wrap(
                "1-arg where unsupported right now"))
        raise OperationError(space.w_ValueError, space.wrap(
            "Where should be called with either 1 or 3 arguments"))
    if space.is_none(w_x):
        raise OperationError(space.w_ValueError, space.wrap(
            "Where should be called with either 1 or 3 arguments"))
    arr = convert_to_array(space, w_arr)
    x = convert_to_array(space, w_x)
    y = convert_to_array(space, w_y)
    if x.is_scalar() and y.is_scalar() and arr.is_scalar():
        if arr.get_dtype().itemtype.bool(arr.get_scalar_value()):
            return x
        return y
    dtype = interp_ufuncs.find_binop_result_dtype(space, x.get_dtype(),
                                                  y.get_dtype())
    shape = shape_agreement(space, arr.get_shape(), x)
    shape = shape_agreement(space, shape, y)
    out = W_NDimArray.from_shape(shape, dtype)
    return loop.where(out, shape, arr, x, y, dtype)

def dot(space, w_obj1, w_obj2):
    w_arr = convert_to_array(space, w_obj1)
    if w_arr.is_scalar():
        return convert_to_array(space, w_obj2).descr_dot(space, w_arr)
    return w_arr.descr_dot(space, w_obj2)


@unwrap_spec(axis=int)
def concatenate(space, w_args, axis=0):
    args_w = space.listview(w_args)
    if len(args_w) == 0:
        raise OperationError(space.w_ValueError, space.wrap("need at least one array to concatenate"))
    args_w = [convert_to_array(space, w_arg) for w_arg in args_w]
    dtype = args_w[0].get_dtype()
    shape = args_w[0].get_shape()[:]
    if len(shape) <= axis:
        raise operationerrfmt(space.w_IndexError, "axis %d out of bounds [0, %d)", axis, len(shape))
    for arr in args_w[1:]:
        dtype = interp_ufuncs.find_binop_result_dtype(space, dtype,
                                                      arr.get_dtype())
        if len(arr.get_shape()) <= axis:
            raise operationerrfmt(space.w_IndexError, "axis %d out of bounds [0, %d)", axis, len(shape))
        for i, axis_size in enumerate(arr.get_shape()):
            if len(arr.get_shape()) != len(shape) or (i != axis and axis_size != shape[i]):
                raise OperationError(space.w_ValueError, space.wrap(
                    "all the input arrays must have same number of dimensions"))
            elif i == axis:
                shape[i] += axis_size
    res = W_NDimArray.from_shape(shape, dtype, 'C')
    chunks = [Chunk(0, i, 1, i) for i in shape]
    axis_start = 0
    for arr in args_w:
        chunks[axis] = Chunk(axis_start, axis_start + arr.get_shape()[axis], 1,
                             arr.get_shape()[axis])
        Chunks(chunks).apply(res.implementation).implementation.setslice(space, arr)
        axis_start += arr.get_shape()[axis]
    return res

@unwrap_spec(repeats=int)
def repeat(space, w_arr, repeats, w_axis=None):
    arr = convert_to_array(space, w_arr)
    if space.is_none(w_axis):
        arr = arr.descr_flatten(space)
        orig_size = arr.get_shape()[0]
        shape = [arr.get_shape()[0] * repeats]
        res = W_NDimArray.from_shape(shape, arr.get_dtype())
        for i in range(repeats):
            Chunks([Chunk(i, shape[0] - repeats + i, repeats,
                          orig_size)]).apply(res.implementation).implementation.setslice(space, arr)
    else:
        axis = space.int_w(w_axis)
        shape = arr.get_shape()[:]
        chunks = [Chunk(0, i, 1, i) for i in shape]
        orig_size = shape[axis]
        shape[axis] *= repeats
        res = W_NDimArray.from_shape(shape, arr.get_dtype())
        for i in range(repeats):
            chunks[axis] = Chunk(i, shape[axis] - repeats + i, repeats,
                                 orig_size)
            Chunks(chunks).apply(res.implementation).implementation.setslice(space, arr)
    return res

def count_nonzero(space, w_obj):
    return space.wrap(loop.count_all_true(convert_to_array(space, w_obj)))
