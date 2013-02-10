from pypy.conftest import option
from rpython.rtyper.lltypesystem import lltype
from rpython.jit.metainterp import warmspot
from pypy.module.pypyjit.policy import PyPyJitPolicy


def run_child(glob, loc):
    import sys, pdb
    interp = loc['interp']
    graph = loc['graph']
    interp.malloc_check = False

    def returns_null(T, *args, **kwds):
        return lltype.nullptr(T)
    interp.heap.malloc_nonmovable = returns_null     # XXX

    from rpython.jit.backend.llgraph.runner import LLtypeCPU
    #LLtypeCPU.supports_floats = False     # for now
    apply_jit(interp, graph, LLtypeCPU)


def run_child_ootype(glob, loc):
    import sys, pdb
    interp = loc['interp']
    graph = loc['graph']
    from rpython.jit.backend.llgraph.runner import OOtypeCPU
    apply_jit(interp, graph, OOtypeCPU)


def apply_jit(interp, graph, CPUClass):
    print 'warmspot.jittify_and_run() started...'
    policy = PyPyJitPolicy()
    option.view = True
    warmspot.jittify_and_run(interp, graph, [], policy=policy,
                             listops=True, CPUClass=CPUClass,
                             backendopt=True, inline=True)

