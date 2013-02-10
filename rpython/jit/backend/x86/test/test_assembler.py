from rpython.jit.backend.x86.regloc import *
from rpython.jit.backend.x86.assembler import Assembler386
from rpython.jit.backend.x86.regalloc import X86FrameManager, get_ebp_ofs
from rpython.jit.metainterp.history import BoxInt, BoxPtr, BoxFloat, ConstFloat
from rpython.jit.metainterp.history import INT, REF, FLOAT
from rpython.rlib.rarithmetic import intmask
from rpython.rtyper.lltypesystem import lltype, llmemory, rffi
from rpython.jit.backend.x86.arch import WORD, IS_X86_32, IS_X86_64
from rpython.jit.backend.detect_cpu import getcpuclass 
from rpython.jit.backend.x86.regalloc import X86RegisterManager, X86_64_RegisterManager, X86XMMRegisterManager, X86_64_XMMRegisterManager
from rpython.jit.backend.llsupport import jitframe
from rpython.jit.codewriter import longlong
import ctypes
import py

ACTUAL_CPU = getcpuclass()
if not hasattr(ACTUAL_CPU, 'NUM_REGS'):
    py.test.skip('unsupported CPU')

class FakeCPU:
    rtyper = None
    supports_floats = True
    NUM_REGS = ACTUAL_CPU.NUM_REGS

    class gc_ll_descr:
        kind = "boehm"

    def fielddescrof(self, STRUCT, name):
        return 42

    def get_fail_descr_from_number(self, num):
        assert num == 0x1C3
        return FakeFailDescr()

    def gc_clear_extra_threshold(self):
        pass

    def get_failargs_limit(self):
        return 1000

class FakeMC:
    def __init__(self):
        self.content = []
    def writechar(self, char):
        self.content.append(ord(char))

class FakeFailDescr:
    def hide(self, cpu):
        return rffi.cast(llmemory.GCREF, 123)

def test_write_failure_recovery_description():
    assembler = Assembler386(FakeCPU())
    mc = FakeMC()
    failargs = [BoxInt(), BoxPtr(), BoxFloat()] * 3
    failargs.insert(6, None)
    failargs.insert(7, None)
    locs = [X86FrameManager.frame_pos(0, INT),
            X86FrameManager.frame_pos(1, REF),
            X86FrameManager.frame_pos(10, FLOAT),
            X86FrameManager.frame_pos(100, INT),
            X86FrameManager.frame_pos(101, REF),
            X86FrameManager.frame_pos(110, FLOAT),
            None,
            None,
            ebx,
            esi,
            xmm2]
    assert len(failargs) == len(locs)
    assembler.write_failure_recovery_description(mc, failargs, locs)
    base = 8 + 8*IS_X86_64
    nums = [Assembler386.DESCR_INT   + 4*(base+0),
            Assembler386.DESCR_REF   + 4*(base+1),
            Assembler386.DESCR_FLOAT + 4*(base+10),
            Assembler386.DESCR_INT   + 4*(base+100),
            Assembler386.DESCR_REF   + 4*(base+101),
            Assembler386.DESCR_FLOAT + 4*(base+110),
            Assembler386.CODE_HOLE,
            Assembler386.CODE_HOLE,
            Assembler386.DESCR_INT   + 4*ebx.value,
            Assembler386.DESCR_REF   + 4*esi.value,
            Assembler386.DESCR_FLOAT + 4*xmm2.value]
    double_byte_nums = []
    for num in nums[3:6]:
        double_byte_nums.append((num & 0x7F) | 0x80)
        double_byte_nums.append(num >> 7)
    assert mc.content == (nums[:3] + double_byte_nums + nums[6:] +
                          [assembler.CODE_STOP])

    # also test rebuild_faillocs_from_descr(), which should not
    # reproduce the holes at all
    bytecode = lltype.malloc(rffi.UCHARP.TO, len(mc.content), flavor='raw',
                             immortal=True)
    for i in range(len(mc.content)):
        assert 0 <= mc.content[i] <= 255
        bytecode[i] = rffi.cast(rffi.UCHAR, mc.content[i])
    bytecode_addr = rffi.cast(lltype.Signed, bytecode)
    newlocs = assembler.rebuild_faillocs_from_descr(bytecode_addr)
    assert ([loc.assembler() for loc in newlocs] ==
            [loc.assembler() for loc in locs if loc is not None])

# ____________________________________________________________

def test_failure_recovery_func_no_floats():
    do_failure_recovery_func(withfloats=False)

def test_failure_recovery_func_with_floats():
    do_failure_recovery_func(withfloats=True)

def do_failure_recovery_func(withfloats):
    import random
    S = lltype.GcStruct('S')

    def get_random_int():
        return random.randrange(-10000, 10000)

    def get_random_ptr():
        return lltype.cast_opaque_ptr(llmemory.GCREF, lltype.malloc(S))

    def get_random_float():
        # Returns <float>, <low word>, <high word>
        # NB: on 64-bit, <low word> will be the entire float and <high word>
        # will be random garbage from malloc!
        assert withfloats
        value = random.random() - 0.5
        # make sure it fits into 64 bits
        tmp = lltype.malloc(rffi.LONGP.TO, 2, flavor='raw',
                            track_allocation=False)
        rffi.cast(rffi.DOUBLEP, tmp)[0] = value
        return rffi.cast(rffi.DOUBLEP, tmp)[0], tmp[0], tmp[1]

    if IS_X86_32:
        main_registers = X86RegisterManager.all_regs
        xmm_registers = X86XMMRegisterManager.all_regs
    elif IS_X86_64:
        main_registers = X86_64_RegisterManager.all_regs
        xmm_registers = X86_64_XMMRegisterManager.all_regs

    # memory locations: 26 integers, 26 pointers, 26 floats
    # main registers: half of them as signed and the other half as ptrs
    # xmm registers: all floats, from xmm0 to xmm(7|15)
    # holes: 8
    locations = []
    baseloc = 4
    for i in range(26+26+26):
        if baseloc < 128:
            baseloc += random.randrange(2, 20)
        else:
            baseloc += random.randrange(2, 1000)
        locations.append(baseloc)
    random.shuffle(locations)
    content = ([('int', locations.pop()) for _ in range(26)] +
               [('ptr', locations.pop()) for _ in range(26)] +
               [(['int', 'ptr'][random.randrange(0, 2)], reg)
                         for reg in main_registers])
    if withfloats:
        content += ([('float', locations.pop()) for _ in range(26)] +
                    [('float', reg) for reg in xmm_registers])
    for i in range(8):
        content.append(('hole', None))
    random.shuffle(content)

    # prepare the expected target arrays, the descr_bytecode,
    # the 'registers' and the 'stack' arrays according to 'content'
    xmmregisters = lltype.malloc(rffi.LONGP.TO, 16+ACTUAL_CPU.NUM_REGS+1,
                                 flavor='raw', immortal=True)
    registers = rffi.ptradd(xmmregisters, 16)
    stacklen = baseloc + 30
    stack = lltype.malloc(rffi.LONGP.TO, stacklen, flavor='raw',
                          immortal=True)
    expected_ints = [None] * len(content)
    expected_ptrs = [None] * len(content)
    expected_floats = [None] * len(content)

    def write_in_stack(loc, value):
        assert loc >= 0
        ofs = get_ebp_ofs(loc)
        assert ofs < 0
        assert (ofs % WORD) == 0
        stack[stacklen + ofs//WORD] = value

    descr_bytecode = []
    for i, (kind, loc) in enumerate(content):
        if kind == 'hole':
            num = Assembler386.CODE_HOLE
        else:
            if kind == 'float':
                value, lo, hi = get_random_float()
                expected_floats[i] = longlong.getfloatstorage(value)
                kind = Assembler386.DESCR_FLOAT
                if isinstance(loc, RegLoc):
                    if WORD == 4:
                        xmmregisters[2*loc.value] = lo
                        xmmregisters[2*loc.value+1] = hi
                    elif WORD == 8:
                        xmmregisters[loc.value] = lo
                else:
                    if WORD == 4:
                        write_in_stack(loc, hi)
                        write_in_stack(loc+1, lo)
                    elif WORD == 8:
                        write_in_stack(loc, lo)
            else:
                if kind == 'int':
                    value = get_random_int()
                    expected_ints[i] = value
                    kind = Assembler386.DESCR_INT
                elif kind == 'ptr':
                    value = get_random_ptr()
                    expected_ptrs[i] = value
                    kind = Assembler386.DESCR_REF
                    value = rffi.cast(rffi.LONG, value)
                else:
                    assert 0, kind
                if isinstance(loc, RegLoc):
                    registers[loc.value] = value
                else:
                    write_in_stack(loc, value)

            if isinstance(loc, RegLoc):
                num = kind + 4*loc.value
            else:
                num = kind + Assembler386.CODE_FROMSTACK + (4*loc)
            while num >= 0x80:
                descr_bytecode.append((num & 0x7F) | 0x80)
                num >>= 7
        descr_bytecode.append(num)

    descr_bytecode.append(Assembler386.CODE_STOP)
    descr_bytecode.append(0xC3)   # fail_index = 0x1C3
    descr_bytecode.append(0x01)
    descr_bytecode.append(0x00)
    descr_bytecode.append(0x00)
    descr_bytecode.append(0xCC)   # end marker
    descr_bytes = lltype.malloc(rffi.UCHARP.TO, len(descr_bytecode),
                                flavor='raw', immortal=True)
    for i in range(len(descr_bytecode)):
        assert 0 <= descr_bytecode[i] <= 255
        descr_bytes[i] = rffi.cast(rffi.UCHAR, descr_bytecode[i])
    registers[ACTUAL_CPU.NUM_REGS] = rffi.cast(rffi.LONG, descr_bytes)
    registers[ebp.value] = rffi.cast(rffi.LONG, stack) + WORD*stacklen

    # run!
    assembler = Assembler386(FakeCPU())
    deadframe = assembler.failure_recovery_func(registers)
    deadframe = lltype.cast_opaque_ptr(jitframe.DEADFRAMEPTR, deadframe)
    assert deadframe.jf_descr == rffi.cast(llmemory.GCREF, 123)

    # check the fail_boxes
    for i in range(len(content)):
        if expected_ints[i] is not None:
            assert deadframe.jf_values[i].int == expected_ints[i]
        if expected_ptrs[i] is not None:
            assert deadframe.jf_values[i].ref == expected_ptrs[i]
        # note: we expect *exact* results below.  If you have only
        # an approximate result, it might mean that only the first 32
        # bits of the float were correctly saved and restored.
        if expected_floats[i] is not None:
            assert deadframe.jf_values[i].float == expected_floats[i]

# ____________________________________________________________

class TestRegallocPushPop(object):

    def do_test(self, callback):
        from rpython.jit.backend.x86.regalloc import X86FrameManager
        from rpython.jit.backend.x86.regalloc import X86XMMRegisterManager
        class FakeToken:
            class compiled_loop_token:
                asmmemmgr_blocks = None
        cpu = ACTUAL_CPU(None, None)
        cpu.setup()
        looptoken = FakeToken()
        asm = cpu.assembler
        asm.setup_once()
        asm.setup(looptoken)
        self.fm = X86FrameManager()
        self.xrm = X86XMMRegisterManager(None, frame_manager=self.fm,
                                         assembler=asm)
        callback(asm)
        asm.mc.RET()
        rawstart = asm.materialize_loop(looptoken)
        #
        F = ctypes.CFUNCTYPE(ctypes.c_long)
        fn = ctypes.cast(rawstart, F)
        res = fn()
        return res

    def test_simple(self):
        def callback(asm):
            asm.mov(imm(42), edx)
            asm.regalloc_push(edx)
            asm.regalloc_pop(eax)
        res = self.do_test(callback)
        assert res == 42

    def test_push_stack(self):
        def callback(asm):
            loc = self.fm.frame_pos(5, INT)
            asm.mc.SUB_ri(esp.value, 64)
            asm.mov(imm(42), loc)
            asm.regalloc_push(loc)
            asm.regalloc_pop(eax)
            asm.mc.ADD_ri(esp.value, 64)
        res = self.do_test(callback)
        assert res == 42

    def test_pop_stack(self):
        def callback(asm):
            loc = self.fm.frame_pos(5, INT)
            asm.mc.SUB_ri(esp.value, 64)
            asm.mov(imm(42), edx)
            asm.regalloc_push(edx)
            asm.regalloc_pop(loc)
            asm.mov(loc, eax)
            asm.mc.ADD_ri(esp.value, 64)
        res = self.do_test(callback)
        assert res == 42

    def test_simple_xmm(self):
        def callback(asm):
            c = ConstFloat(longlong.getfloatstorage(-42.5))
            loc = self.xrm.convert_to_imm(c)
            asm.mov(loc, xmm5)
            asm.regalloc_push(xmm5)
            asm.regalloc_pop(xmm0)
            asm.mc.CVTTSD2SI(eax, xmm0)
        res = self.do_test(callback)
        assert res == -42

    def test_push_stack_xmm(self):
        def callback(asm):
            c = ConstFloat(longlong.getfloatstorage(-42.5))
            loc = self.xrm.convert_to_imm(c)
            loc2 = self.fm.frame_pos(4, FLOAT)
            asm.mc.SUB_ri(esp.value, 64)
            asm.mov(loc, xmm5)
            asm.mov(xmm5, loc2)
            asm.regalloc_push(loc2)
            asm.regalloc_pop(xmm0)
            asm.mc.ADD_ri(esp.value, 64)
            asm.mc.CVTTSD2SI(eax, xmm0)
        res = self.do_test(callback)
        assert res == -42

    def test_pop_stack_xmm(self):
        def callback(asm):
            c = ConstFloat(longlong.getfloatstorage(-42.5))
            loc = self.xrm.convert_to_imm(c)
            loc2 = self.fm.frame_pos(4, FLOAT)
            asm.mc.SUB_ri(esp.value, 64)
            asm.mov(loc, xmm5)
            asm.regalloc_push(xmm5)
            asm.regalloc_pop(loc2)
            asm.mov(loc2, xmm0)
            asm.mc.ADD_ri(esp.value, 64)
            asm.mc.CVTTSD2SI(eax, xmm0)
        res = self.do_test(callback)
        assert res == -42
