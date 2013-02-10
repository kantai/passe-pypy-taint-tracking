from __future__ import with_statement

import signal as cpy_signal
import sys

from pypy.interpreter.error import OperationError, exception_from_errno
from pypy.interpreter.executioncontext import (AsyncAction, AbstractActionFlag,
    PeriodicAsyncAction)
from pypy.interpreter.gateway import unwrap_spec

from rpython.rlib import jit, rposix, rgc
from rpython.rlib.objectmodel import we_are_translated
from rpython.rlib.rarithmetic import intmask
from rpython.rlib.rsignal import *
from rpython.rtyper.lltypesystem import lltype, rffi


WIN32 = sys.platform == 'win32'


class SignalActionFlag(AbstractActionFlag):
    # This class uses the C-level pypysig_counter variable as the tick
    # counter.  The C-level signal handler will reset it to -1 whenever
    # a signal is received.  This causes CheckSignalAction.perform() to
    # be called.

    def get_ticker(self):
        p = pypysig_getaddr_occurred()
        return p.c_value

    def reset_ticker(self, value):
        p = pypysig_getaddr_occurred()
        p.c_value = value

    @staticmethod
    def rearm_ticker():
        p = pypysig_getaddr_occurred()
        p.c_value = -1

    def decrement_ticker(self, by):
        p = pypysig_getaddr_occurred()
        value = p.c_value
        if self.has_bytecode_counter:    # this 'if' is constant-folded
            if jit.isconstant(by) and by == 0:
                pass     # normally constant-folded too
            else:
                value -= by
                p.c_value = value
        return value


class CheckSignalAction(PeriodicAsyncAction):
    """An action that is automatically invoked when a signal is received."""

    # Note that this is a PeriodicAsyncAction: it means more precisely
    # that it is called whenever the C-level ticker becomes < 0.
    # Without threads, it is only ever set to -1 when we receive a
    # signal.  With threads, it also decrements steadily (but slowly).

    def __init__(self, space):
        "NOT_RPYTHON"
        AsyncAction.__init__(self, space)
        self.pending_signal = -1
        self.fire_in_main_thread = False
        if self.space.config.objspace.usemodules.thread:
            from pypy.module.thread import gil
            gil.after_thread_switch = self._after_thread_switch

    @rgc.no_collect
    def _after_thread_switch(self):
        if self.fire_in_main_thread:
            if self.space.threadlocals.ismainthread():
                self.fire_in_main_thread = False
                SignalActionFlag.rearm_ticker()
                # this occurs when we just switched to the main thread
                # and there is a signal pending: we force the ticker to
                # -1, which should ensure perform() is called quickly.

    @jit.dont_look_inside
    def perform(self, executioncontext, frame):
        # Poll for the next signal, if any
        n = self.pending_signal
        if n < 0: n = pypysig_poll()
        while n >= 0:
            if self.space.config.objspace.usemodules.thread:
                in_main = self.space.threadlocals.ismainthread()
            else:
                in_main = True
            if in_main:
                # If we are in the main thread, report the signal now,
                # and poll more
                self.pending_signal = -1
                report_signal(self.space, n)
                n = self.pending_signal
                if n < 0: n = pypysig_poll()
            else:
                # Otherwise, arrange for perform() to be called again
                # after we switch to the main thread.
                self.pending_signal = n
                self.fire_in_main_thread = True
                break

    def set_interrupt(self):
        "Simulates the effect of a SIGINT signal arriving"
        if not we_are_translated():
            self.pending_signal = cpy_signal.SIGINT
            # ^^^ may override another signal, but it's just for testing
        else:
            pypysig_pushback(cpy_signal.SIGINT)
        self.fire_in_main_thread = True

# ____________________________________________________________


class Handlers:
    def __init__(self, space):
        self.handlers_w = {}

def _get_handlers(space):
    return space.fromcache(Handlers).handlers_w


def report_signal(space, n):
    handlers_w = _get_handlers(space)
    try:
        w_handler = handlers_w[n]
    except KeyError:
        return    # no handler, ignore signal
    if not space.is_true(space.callable(w_handler)):
        return    # w_handler is SIG_IGN or SIG_DFL?
    # re-install signal handler, for OSes that clear it
    pypysig_reinstall(n)
    # invoke the app-level handler
    ec = space.getexecutioncontext()
    w_frame = space.wrap(ec.gettopframe_nohidden())
    space.call_function(w_handler, space.wrap(n), w_frame)


@unwrap_spec(signum=int)
def getsignal(space, signum):
    """
    getsignal(sig) -> action

    Return the current action for the given signal.  The return value can be:
    SIG_IGN -- if the signal is being ignored
    SIG_DFL -- if the default action for the signal is in effect
    None -- if an unknown handler is in effect (XXX UNIMPLEMENTED)
    anything else -- the callable Python object used as a handler
    """
    if WIN32:
        check_signum_exists(space, signum)
    else:
        check_signum_in_range(space, signum)
    handlers_w = _get_handlers(space)
    if signum in handlers_w:
        return handlers_w[signum]
    return space.wrap(SIG_DFL)


def default_int_handler(space, w_signum, w_frame):
    """
    default_int_handler(...)

    The default handler for SIGINT installed by Python.
    It raises KeyboardInterrupt.
    """
    raise OperationError(space.w_KeyboardInterrupt,
                         space.w_None)


@jit.dont_look_inside
@unwrap_spec(timeout=int)
def alarm(space, timeout):
    return space.wrap(c_alarm(timeout))


@jit.dont_look_inside
def pause(space):
    c_pause()
    return space.w_None


def check_signum_exists(space, signum):
    if signum in signal_values:
        return
    raise OperationError(space.w_ValueError,
                         space.wrap("invalid signal value"))


def check_signum_in_range(space, signum):
    if 1 <= signum < NSIG:
        return
    raise OperationError(space.w_ValueError,
                         space.wrap("signal number out of range"))


@jit.dont_look_inside
@unwrap_spec(signum=int)
def signal(space, signum, w_handler):
    """
    signal(sig, action) -> action

    Set the action for the given signal.  The action can be SIG_DFL,
    SIG_IGN, or a callable Python object.  The previous action is
    returned.  See getsignal() for possible return values.

    *** IMPORTANT NOTICE ***
    A signal handler function is called with two arguments:
    the first is the signal number, the second is the interrupted stack frame.
    """
    if not space.threadlocals.ismainthread():
        raise OperationError(space.w_ValueError,
                             space.wrap("signal() must be called from the "
                                        "main thread"))
    old_handler = getsignal(space, signum)

    if space.eq_w(w_handler, space.wrap(SIG_DFL)):
        pypysig_default(signum)
    elif space.eq_w(w_handler, space.wrap(SIG_IGN)):
        pypysig_ignore(signum)
    else:
        if not space.is_true(space.callable(w_handler)):
            raise OperationError(space.w_TypeError,
                                 space.wrap("'handler' must be a callable "
                                            "or SIG_DFL or SIG_IGN"))
        pypysig_setflag(signum)
    handlers_w = _get_handlers(space)
    handlers_w[signum] = w_handler
    return old_handler


@jit.dont_look_inside
@unwrap_spec(fd=int)
def set_wakeup_fd(space, fd):
    """Sets the fd to be written to (with '\0') when a signal
    comes in.  Returns the old fd.  A library can use this to
    wakeup select or poll.  The previous fd is returned.

    The fd must be non-blocking.
    """
    if not space.threadlocals.ismainthread():
        raise OperationError(
            space.w_ValueError,
            space.wrap("set_wakeup_fd only works in main thread"))
    old_fd = pypysig_set_wakeup_fd(fd)
    return space.wrap(intmask(old_fd))


@jit.dont_look_inside
@unwrap_spec(signum=int, flag=int)
def siginterrupt(space, signum, flag):
    check_signum_exists(space, signum)
    if rffi.cast(lltype.Signed, c_siginterrupt(signum, flag)) < 0:
        errno = rposix.get_errno()
        raise OperationError(space.w_RuntimeError, space.wrap(errno))


#__________________________________________________________

def timeval_from_double(d, timeval):
    rffi.setintfield(timeval, 'c_tv_sec', int(d))
    rffi.setintfield(timeval, 'c_tv_usec', int((d - int(d)) * 1000000))


def double_from_timeval(tv):
    return rffi.getintfield(tv, 'c_tv_sec') + (
        rffi.getintfield(tv, 'c_tv_usec') / 1000000.0)


def itimer_retval(space, val):
    w_value = space.wrap(double_from_timeval(val.c_it_value))
    w_interval = space.wrap(double_from_timeval(val.c_it_interval))
    return space.newtuple([w_value, w_interval])


class Cache:
    def __init__(self, space):
        self.w_itimererror = space.new_exception_class("signal.ItimerError",
                                                       space.w_IOError)


def get_itimer_error(space):
    return space.fromcache(Cache).w_itimererror


@jit.dont_look_inside
@unwrap_spec(which=int, first=float, interval=float)
def setitimer(space, which, first, interval=0):
    """setitimer(which, seconds[, interval])
    Sets given itimer (one of ITIMER_REAL, ITIMER_VIRTUAL

    or ITIMER_PROF) to fire after value seconds and after
    that every interval seconds.
    The itimer can be cleared by setting seconds to zero.

    Returns old values as a tuple: (delay, interval).
    """
    with lltype.scoped_alloc(itimervalP.TO, 1) as new:

        timeval_from_double(first, new[0].c_it_value)
        timeval_from_double(interval, new[0].c_it_interval)

        with lltype.scoped_alloc(itimervalP.TO, 1) as old:

            ret = c_setitimer(which, new, old)
            if ret != 0:
                raise exception_from_errno(space, get_itimer_error(space))

            return itimer_retval(space, old[0])


@jit.dont_look_inside
@unwrap_spec(which=int)
def getitimer(space, which):
    """getitimer(which)

    Returns current value of given itimer.
    """
    with lltype.scoped_alloc(itimervalP.TO, 1) as old:

        c_getitimer(which, old)

        return itimer_retval(space, old[0])
