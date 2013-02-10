from pypy.interpreter.error import OperationError
from rpython.rtyper.lltypesystem import rffi, lltype
from pypy.module.cpyext.api import (
    cpython_api, CANNOT_FAIL, Py_buffer)
from pypy.module.cpyext.pyobject import PyObject

@cpython_api([PyObject], rffi.INT_real, error=CANNOT_FAIL)
def PyObject_CheckBuffer(space, w_obj):
    """Return 1 if obj supports the buffer interface otherwise 0."""
    return 0  # the bf_getbuffer field is never filled by cpyext

@cpython_api([PyObject, lltype.Ptr(Py_buffer), rffi.INT_real],
             rffi.INT_real, error=-1)
def PyObject_GetBuffer(space, w_obj, view, flags):
    """Export obj into a Py_buffer, view.  These arguments must
    never be NULL.  The flags argument is a bit field indicating what
    kind of buffer the caller is prepared to deal with and therefore what
    kind of buffer the exporter is allowed to return.  The buffer interface
    allows for complicated memory sharing possibilities, but some caller may
    not be able to handle all the complexity but may want to see if the
    exporter will let them take a simpler view to its memory.

    Some exporters may not be able to share memory in every possible way and
    may need to raise errors to signal to some consumers that something is
    just not possible. These errors should be a BufferError unless
    there is another error that is actually causing the problem. The
    exporter can use flags information to simplify how much of the
    Py_buffer structure is filled in with non-default values and/or
    raise an error if the object can't support a simpler view of its memory.

    0 is returned on success and -1 on error."""
    raise OperationError(space.w_TypeError, space.wrap(
            'PyPy does not yet implement the new buffer interface'))

@cpython_api([lltype.Ptr(Py_buffer), lltype.Char], rffi.INT_real, error=CANNOT_FAIL)
def PyBuffer_IsContiguous(space, view, fortran):
    """Return 1 if the memory defined by the view is C-style (fortran is
    'C') or Fortran-style (fortran is 'F') contiguous or either one
    (fortran is 'A').  Return 0 otherwise."""
    # PyPy only supports contiguous Py_buffers for now.
    return space.wrap(1)
