JIT hooks in PyPy
=================

There are several hooks in the `pypyjit` module that may help you with
understanding what's pypy's JIT doing while running your program. There
are three functions related to that coming from the `pypyjit` module:

* `set_optimize_hook(callable)`::

    Set a compiling hook that will be called each time a loop is optimized,
    but before assembler compilation. This allows adding additional
    optimizations on Python level.

    The callable will be called with the pypyjit.JitLoopInfo object.
    Refer to it's documentation for details.

    Result value will be the resulting list of operations, or None


* `set_compile_hook(callable)`::

    Set a compiling hook that will be called each time a loop is compiled.

    The callable will be called with the pypyjit.JitLoopInfo object.
    Refer to it's documentation for details.

    Note that jit hook is not reentrant. It means that if the code
    inside the jit hook is itself jitted, it will get compiled, but the
    jit hook won't be called for that.

* `set_abort_hook(hook)`::

    Set a hook (callable) that will be called each time there is tracing
    aborted due to some reason.

    The hook will be called as in: hook(jitdriver_name, greenkey, reason)

    Reason is a string, the meaning of other arguments is the same
    as attributes on JitLoopInfo object

