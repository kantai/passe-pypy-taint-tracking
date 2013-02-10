"""
A file that invokes translation of PyPy with the JIT enabled.

Run it with py.test -s --pdb pypyjit.py [--ootype]

"""

import py, os

from pypy.objspace.std import Space
from rpython.config.translationoption import set_opt_level
from pypy.config.pypyoption import get_pypy_config, set_pypy_opt_level
from pypy.objspace.std import multimethod
from rpython.rtyper.annlowlevel import llhelper, llstr, oostr, hlstr
from rpython.rtyper.lltypesystem.rstr import STR
from rpython.rtyper.lltypesystem import lltype
from rpython.rtyper.ootypesystem import ootype
from pypy.interpreter.pycode import PyCode
from rpython.translator.goal import unixcheckpoint

if not hasattr(py.test.config.option, 'ootype'):
    import sys
    print >> sys.stderr, __doc__
    sys.exit(2)

if py.test.config.option.ootype:
    BACKEND = 'cli'
else:
    BACKEND = 'c'

config = get_pypy_config(translating=True)
config.translation.backendopt.inline_threshold = 0.1
config.translation.gc = 'boehm'
config.translating = True
set_opt_level(config, level='jit')
config.objspace.allworkingmodules = False
config.objspace.usemodules.pypyjit = True
config.objspace.usemodules.array = False
config.objspace.usemodules._weakref = True
config.objspace.usemodules._sre = False
config.objspace.usemodules._lsprof = False
#
config.objspace.usemodules._ffi = True
#config.objspace.usemodules.cppyy = True
config.objspace.usemodules.micronumpy = False
#
set_pypy_opt_level(config, level='jit')

if BACKEND == 'c':
    config.objspace.std.multimethods = 'mrd'
    multimethod.Installer = multimethod.InstallerVersion2
elif BACKEND == 'cli':
    config.objspace.std.multimethods = 'doubledispatch'
    multimethod.Installer = multimethod.InstallerVersion1
    config.translation.backend = 'cli'
else:
    assert False
print config

import sys, pdb

space = Space(config)
w_dict = space.newdict(module=True)


def readfile(filename):
    fd = os.open(filename, os.O_RDONLY, 0)
    blocks = []
    while True:
        data = os.read(fd, 4096)
        if not data:
            break
        blocks.append(data)
    os.close(fd)
    return ''.join(blocks)

def read_code():
    from pypy.module.marshal.interp_marshal import dumps

    filename = 'pypyjit_demo.py'
    source = readfile(filename)
    ec = space.getexecutioncontext()
    code = ec.compiler.compile(source, filename, 'exec', 0)
    return llstr(space.str_w(dumps(space, code, space.wrap(2))))

if BACKEND == 'c':
    FPTR = lltype.Ptr(lltype.FuncType([], lltype.Ptr(STR)))
    read_code_ptr = llhelper(FPTR, read_code)
else:
    llstr = oostr
    FUNC = ootype.StaticMethod([], ootype.String)
    read_code_ptr = llhelper(FUNC, read_code)

def entry_point():
    from pypy.module.marshal.interp_marshal import loads
    code = loads(space, space.wrap(hlstr(read_code_ptr())))
    assert isinstance(code, PyCode)
    code.exec_code(space, w_dict, w_dict)

def test_run_translation():
    from pypy.tool.ann_override import PyPyAnnotatorPolicy
    from rpython.rtyper.test.test_llinterp import get_interpreter

    # first annotate and rtype
    try:
        interp, graph = get_interpreter(entry_point, [], backendopt=False,
                                        config=config,
                                        type_system=config.translation.type_system,
                                        policy=PyPyAnnotatorPolicy(space))
    except Exception, e:
        print '%s: %s' % (e.__class__, e)
        pdb.post_mortem(sys.exc_info()[2])
        raise

    # parent process loop: spawn a child, wait for the child to finish,
    # print a message, and restart
    unixcheckpoint.restartable_point(auto='run')

    from rpython.jit.codewriter.codewriter import CodeWriter
    CodeWriter.debug = True
    from rpython.jit.tl.pypyjit_child import run_child, run_child_ootype
    if BACKEND == 'c':
        run_child(globals(), locals())
    elif BACKEND == 'cli':
        run_child_ootype(globals(), locals())
    else:
        assert False


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        # debugging: run the code directly
        entry_point()
    else:
        test_run_translation()
