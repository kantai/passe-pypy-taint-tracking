
from pypy.interpreter.gateway import unwrap_spec
from pypy.interpreter.error import OperationError
from pypy.module._minimal_curses import _curses

class ModuleInfo:
    def __init__(self):
        self.setupterm_called = False

module_info = ModuleInfo()

class curses_error(Exception):
    def __init__(self, msg):
        self.msg = msg

from rpython.annotator.classdef import FORCE_ATTRIBUTES_INTO_CLASSES
from rpython.annotator.model import SomeString

# this is necessary due to annmixlevel
FORCE_ATTRIBUTES_INTO_CLASSES[curses_error] = {'msg': SomeString()}

def convert_error(space, error):
    msg = error.msg
    w_module = space.getbuiltinmodule('_minimal_curses')
    w_exception_class = space.getattr(w_module, space.wrap('error'))
    w_exception = space.call_function(w_exception_class, space.wrap(msg))
    return OperationError(w_exception_class, w_exception)

def _curses_setupterm_null(fd):
    # NOT_RPYTHON
    try:
        _curses.setupterm(None, fd)
    except _curses.error, e:
        raise curses_error(e.args[0])

def _curses_setupterm(termname, fd):
    # NOT_RPYTHON
    try:
        _curses.setupterm(termname, fd)
    except _curses.error, e:
        raise curses_error(e.args[0])

@unwrap_spec(fd=int)
def setupterm(space, w_termname=None, fd=-1):
    if fd == -1:
        w_stdout = space.getattr(space.getbuiltinmodule('sys'),
                                 space.wrap('stdout'))
        fd = space.int_w(space.call_function(space.getattr(w_stdout,
                                             space.wrap('fileno'))))
    try:
        if space.is_none(w_termname):
            _curses_setupterm_null(fd)
        else:
            _curses_setupterm(space.str_w(w_termname), fd)
    except curses_error, e:
        raise convert_error(space, e)

class TermError(Exception):
    pass

def _curses_tigetstr(capname):
    # NOT_RPYTHON
    try:
        res = _curses.tigetstr(capname)
    except _curses.error, e:
        raise curses_error(e.args[0])
    if res is None:
        raise TermError
    return res

def _curses_tparm(s, args):
    # NOT_RPYTHON
    try:
        return _curses.tparm(s, *args)
    except _curses.error, e:
        raise curses_error(e.args[0])

@unwrap_spec(capname=str)
def tigetstr(space, capname):
    try:
        result = _curses_tigetstr(capname)
    except TermError:
        return space.w_None
    except curses_error, e:
        raise convert_error(space, e)
    return space.wrap(result)

@unwrap_spec(s=str)
def tparm(space, s, args_w):
    args = [space.int_w(a) for a in args_w]
    try:
        return space.wrap(_curses_tparm(s, args))
    except curses_error, e:
        raise convert_error(space, e)
