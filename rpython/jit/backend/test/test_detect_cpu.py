from rpython.jit.backend.detect_cpu import *


def test_autodetect():
    try:
        name = autodetect()
    except ProcessorAutodetectError:
        pass
    else:
        assert isinstance(name, str)

def test_getcpuclassname():
    try:
        modname, clsname = getcpuclassname()
    except ProcessorAutodetectError:
        pass
    else:
        assert isinstance(modname, str)
        assert isinstance(clsname, str)

def test_getcpuclass():
    try:
        cpu = getcpuclass()
    except ProcessorAutodetectError:
        pass
    else:
        from rpython.jit.backend.model import AbstractCPU
        assert issubclass(cpu, AbstractCPU)
