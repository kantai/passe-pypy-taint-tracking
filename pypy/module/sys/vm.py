"""
Implementation of interpreter-level 'sys' routines.
"""
import sys

from pypy.interpreter import gateway
from pypy.interpreter.error import OperationError
from pypy.interpreter.gateway import unwrap_spec, WrappedDefault
from rpython.rlib import jit
from rpython.rlib.runicode import MAXUNICODE

# ____________________________________________________________

def setbuiltinmodule(w_module, name):
    """ put a module into the modules builtin_modules dicts """
    if builtin_modules[name] is None:
        builtin_modules[name] = space.unwrap(w_module)
    else:
        assert builtin_modules[name] is space.unwrap(w_module), (
            "trying to change the builtin-in module %r" % (name,))
    space.setitem(w_modules, space.wrap(name), w_module)

@unwrap_spec(w_depth = WrappedDefault(0))
def _getframe(space, w_depth):
    """Return a frame object from the call stack.  If optional integer depth is
given, return the frame object that many calls below the top of the stack.
If that is deeper than the call stack, ValueError is raised.  The default
for depth is zero, returning the frame at the top of the call stack.

This function should be used for internal and specialized
purposes only."""
    depth = space.int_w(w_depth)
    if depth < 0:
        raise OperationError(space.w_ValueError,
                             space.wrap("frame index must not be negative"))
    ec = space.getexecutioncontext()
    f = ec.gettopframe_nohidden()
    while True:
        if f is None:
            raise OperationError(space.w_ValueError,
                                 space.wrap("call stack is not deep enough"))
        if depth == 0:
            break
        depth -= 1
        f = ec.getnextframe_nohidden(f)
    f.mark_as_escaped()
    return space.wrap(f)

@unwrap_spec(new_limit="c_int")
def setrecursionlimit(space, new_limit):
    """setrecursionlimit() sets the maximum number of nested calls that
can occur before a RuntimeError is raised.  On PyPy the limit is
approximative and checked at a lower level.  The default 1000
reserves 768KB of stack space, which should suffice (on Linux,
depending on the compiler settings) for ~1400 calls.  Setting the
value to N reserves N/1000 times 768KB of stack space.
"""
    from rpython.rlib.rstack import _stack_set_length_fraction
    if new_limit <= 0:
        raise OperationError(space.w_ValueError,
                             space.wrap("recursion limit must be positive"))
    space.sys.recursionlimit = new_limit
    if space.config.translation.type_system == 'lltype':
        _stack_set_length_fraction(new_limit * 0.001)

def getrecursionlimit(space):
    """Return the last value set by setrecursionlimit().
    """
    return space.wrap(space.sys.recursionlimit)

@unwrap_spec(interval=int)
def setcheckinterval(space, interval):
    """Tell the Python interpreter to check for asynchronous events every
    n instructions.  This also affects how often thread switches occur."""
    space.actionflag.setcheckinterval(interval)

def getcheckinterval(space):
    """Return the current check interval; see setcheckinterval()."""
    # xxx to make tests and possibly some obscure apps happy, if the
    # checkinterval is set to the minimum possible value (which is 1) we
    # return 0.  The idea is that according to the CPython docs, <= 0
    # means "check every virtual instruction, maximizing responsiveness
    # as well as overhead".
    result = space.actionflag.getcheckinterval()
    if result <= 1:
        result = 0
    return space.wrap(result)

def exc_info(space):
    """Return the (type, value, traceback) of the most recent exception
caught by an except clause in the current stack frame or in an older stack
frame."""
    return exc_info_with_tb(space)    # indirection for the tests

def exc_info_with_tb(space):
    operror = space.getexecutioncontext().sys_exc_info()
    if operror is None:
        return space.newtuple([space.w_None, space.w_None, space.w_None])
    else:
        return space.newtuple([operror.w_type, operror.get_w_value(space),
                               space.wrap(operror.get_traceback())])

def exc_info_without_tb(space, frame):
    operror = frame.last_exception
    return space.newtuple([operror.w_type, operror.get_w_value(space),
                           space.w_None])

def exc_info_direct(space, frame):
    from pypy.tool import stdlib_opcode
    # In order to make the JIT happy, we try to return (exc, val, None)
    # instead of (exc, val, tb).  We can do that only if we recognize
    # the following pattern in the bytecode:
    #       CALL_FUNCTION/CALL_METHOD         <-- invoking me
    #       LOAD_CONST 0, 1, -2 or -3
    #       BINARY_SUBSCR
    # or:
    #       CALL_FUNCTION/CALL_METHOD
    #       LOAD_CONST <=2
    #       SLICE_2
    # or:
    #       CALL_FUNCTION/CALL_METHOD
    #       LOAD_CONST any integer
    #       LOAD_CONST <=2
    #       SLICE_3
    need_all_three_args = True
    co = frame.getcode().co_code
    p = frame.last_instr
    if (ord(co[p]) == stdlib_opcode.CALL_FUNCTION or
        ord(co[p]) == stdlib_opcode.CALL_METHOD):
        if ord(co[p+3]) == stdlib_opcode.LOAD_CONST:
            lo = ord(co[p+4])
            hi = ord(co[p+5])
            w_constant = frame.getconstant_w((hi * 256) | lo)
            if space.isinstance_w(w_constant, space.w_int):
                constant = space.int_w(w_constant)
                if ord(co[p+6]) == stdlib_opcode.BINARY_SUBSCR:
                    if -3 <= constant <= 1 and constant != -1:
                        need_all_three_args = False
                elif ord(co[p+6]) == stdlib_opcode.SLICE+2:
                    if constant <= 2:
                        need_all_three_args = False
                elif (ord(co[p+6]) == stdlib_opcode.LOAD_CONST and
                      ord(co[p+9]) == stdlib_opcode.SLICE+3):
                    lo = ord(co[p+7])
                    hi = ord(co[p+8])
                    w_constant = frame.getconstant_w((hi * 256) | lo)
                    if space.isinstance_w(w_constant, space.w_int):
                        if space.int_w(w_constant) <= 2:
                            need_all_three_args = False
    #
    if need_all_three_args or frame.last_exception is None or frame.hide():
        return exc_info_with_tb(space)
    else:
        return exc_info_without_tb(space, frame)

def exc_clear(space):
    """Clear global information on the current exception.  Subsequent calls
to exc_info() will return (None,None,None) until another exception is
raised and caught in the current thread or the execution stack returns to a
frame where another exception is being handled."""
    operror = space.getexecutioncontext().sys_exc_info()
    if operror is not None:
        operror.clear(space)

def settrace(space, w_func):
    """Set the global debug tracing function.  It will be called on each
function call.  See the debugger chapter in the library manual."""
    space.getexecutioncontext().settrace(w_func)

def gettrace(space):
    """Return the global debug tracing function set with sys.settrace.
See the debugger chapter in the library manual."""
    return space.getexecutioncontext().gettrace()

def setprofile(space, w_func):
    """Set the profiling function.  It will be called on each function call
and return.  See the profiler chapter in the library manual."""
    space.getexecutioncontext().setprofile(w_func)

def getprofile(space):
    """Return the profiling function set with sys.setprofile.
See the profiler chapter in the library manual."""
    w_func = space.getexecutioncontext().getprofile()
    if w_func is not None:
        return w_func
    else:
        return space.w_None

def call_tracing(space, w_func, w_args):
    """Call func(*args), while tracing is enabled.  The tracing state is
saved, and restored afterwards.  This is intended to be called from
a debugger from a checkpoint, to recursively debug some other code."""
    return space.getexecutioncontext().call_tracing(w_func, w_args)


app = gateway.applevel('''
"NOT_RPYTHON"
from _structseq import structseqtype, structseqfield

class windows_version_info:
    __metaclass__ = structseqtype

    name = "sys.getwindowsversion"

    major = structseqfield(0, "Major version number")
    minor = structseqfield(1, "Minor version number")
    build = structseqfield(2, "Build number")
    platform = structseqfield(3, "Operating system platform")
    service_pack = structseqfield(4, "Latest Service Pack installed on the system")

    # Because the indices aren't consecutive, they aren't included when
    # unpacking and other such operations.
    service_pack_major = structseqfield(10, "Service Pack major version number")
    service_pack_minor = structseqfield(11, "Service Pack minor version number")
    suite_mask = structseqfield(12, "Bit mask identifying available product suites")
    product_type = structseqfield(13, "System product type")
''')


def getwindowsversion(space):
    from rpython.rlib import rwin32
    info = rwin32.GetVersionEx()
    w_windows_version_info = app.wget(space, "windows_version_info")
    raw_version = space.newtuple([
        space.wrap(info[0]),
        space.wrap(info[1]),
        space.wrap(info[2]),
        space.wrap(info[3]),
        space.wrap(info[4]),
        space.wrap(info[5]),
        space.wrap(info[6]),
        space.wrap(info[7]),
        space.wrap(info[8]),
    ])
    return space.call_function(w_windows_version_info, raw_version)

@jit.dont_look_inside
def get_dllhandle(space):
    if not space.config.objspace.usemodules.cpyext:
        return space.wrap(0)
    if not space.config.objspace.usemodules._rawffi:
        return space.wrap(0)

    return _get_dllhandle(space)

def _get_dllhandle(space):
    # Retrieve cpyext api handle
    from pypy.module.cpyext.api import State
    handle = space.fromcache(State).get_pythonapi_handle()

    # Make a dll object with it
    from pypy.module._rawffi.interp_rawffi import W_CDLL, RawCDLL
    cdll = RawCDLL(handle)
    return space.wrap(W_CDLL(space, "python api", cdll))

def getsizeof(space, w_object, w_default=None):
    """Not implemented on PyPy."""
    if w_default is None:
        raise OperationError(space.w_TypeError,
            space.wrap("sys.getsizeof() not implemented on PyPy"))
    return w_default
