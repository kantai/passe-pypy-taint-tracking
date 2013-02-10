
""" Register allocation scheme.
"""

import os
from rpython.jit.metainterp.history import (Box, Const, ConstInt, ConstPtr,
                                         ResOperation, BoxPtr, ConstFloat,
                                         BoxFloat, INT, REF, FLOAT,
                                         TargetToken, JitCellToken)
from rpython.jit.backend.x86.regloc import *
from rpython.rtyper.lltypesystem import lltype, rffi, rstr
from rpython.rlib.objectmodel import we_are_translated
from rpython.rlib import rgc
from rpython.jit.backend.llsupport import symbolic
from rpython.jit.backend.x86.jump import remap_frame_layout_mixed
from rpython.jit.codewriter import heaptracker, longlong
from rpython.jit.codewriter.effectinfo import EffectInfo
from rpython.jit.metainterp.resoperation import rop
from rpython.jit.backend.llsupport.descr import FieldDescr, ArrayDescr
from rpython.jit.backend.llsupport.descr import CallDescr, SizeDescr
from rpython.jit.backend.llsupport.descr import InteriorFieldDescr
from rpython.jit.backend.llsupport.descr import unpack_arraydescr
from rpython.jit.backend.llsupport.descr import unpack_fielddescr
from rpython.jit.backend.llsupport.descr import unpack_interiorfielddescr
from rpython.jit.backend.llsupport.regalloc import FrameManager, RegisterManager,\
     TempBox, compute_vars_longevity, is_comparison_or_ovf_op
from rpython.jit.backend.x86.arch import WORD, FRAME_FIXED_SIZE
from rpython.jit.backend.x86.arch import IS_X86_32, IS_X86_64, MY_COPY_OF_REGS
from rpython.jit.backend.x86 import rx86
from rpython.rlib.rarithmetic import r_longlong

class X86RegisterManager(RegisterManager):

    box_types = [INT, REF]
    all_regs = [ecx, eax, edx, ebx, esi, edi]
    no_lower_byte_regs = [esi, edi]
    save_around_call_regs = [eax, edx, ecx]
    frame_reg = ebp

    REGLOC_TO_GCROOTMAP_REG_INDEX = {
        ebx: 1,
        esi: 2,
        edi: 3,
    }
    REGLOC_TO_COPY_AREA_OFS = {
        ecx: MY_COPY_OF_REGS + 0 * WORD,
        ebx: MY_COPY_OF_REGS + 1 * WORD,
        esi: MY_COPY_OF_REGS + 2 * WORD,
        edi: MY_COPY_OF_REGS + 3 * WORD,
    }

    def call_result_location(self, v):
        return eax

    def convert_to_imm(self, c):
        if isinstance(c, ConstInt):
            return imm(c.value)
        elif isinstance(c, ConstPtr):
            if we_are_translated() and c.value and rgc.can_move(c.value):
                not_implemented("convert_to_imm: ConstPtr needs special care")
            return imm(rffi.cast(lltype.Signed, c.value))
        else:
            not_implemented("convert_to_imm: got a %s" % c)

class X86_64_RegisterManager(X86RegisterManager):
    # r11 omitted because it's used as scratch
    all_regs = [ecx, eax, edx, ebx, esi, edi, r8, r9, r10, r12, r13, r14, r15]
    no_lower_byte_regs = []
    save_around_call_regs = [eax, ecx, edx, esi, edi, r8, r9, r10]

    REGLOC_TO_GCROOTMAP_REG_INDEX = {
        ebx: 1,
        r12: 2,
        r13: 3,
        r14: 4,
        r15: 5,
    }
    REGLOC_TO_COPY_AREA_OFS = {
        ecx: MY_COPY_OF_REGS + 0 * WORD,
        ebx: MY_COPY_OF_REGS + 1 * WORD,
        esi: MY_COPY_OF_REGS + 2 * WORD,
        edi: MY_COPY_OF_REGS + 3 * WORD,
        r8:  MY_COPY_OF_REGS + 4 * WORD,
        r9:  MY_COPY_OF_REGS + 5 * WORD,
        r10: MY_COPY_OF_REGS + 6 * WORD,
        r12: MY_COPY_OF_REGS + 7 * WORD,
        r13: MY_COPY_OF_REGS + 8 * WORD,
        r14: MY_COPY_OF_REGS + 9 * WORD,
        r15: MY_COPY_OF_REGS + 10 * WORD,
    }

class X86XMMRegisterManager(RegisterManager):

    box_types = [FLOAT]
    all_regs = [xmm0, xmm1, xmm2, xmm3, xmm4, xmm5, xmm6, xmm7]
    # we never need lower byte I hope
    save_around_call_regs = all_regs

    def convert_to_imm(self, c):
        adr = self.assembler.datablockwrapper.malloc_aligned(8, 8)
        x = c.getfloatstorage()
        rffi.cast(rffi.CArrayPtr(longlong.FLOATSTORAGE), adr)[0] = x
        return ConstFloatLoc(adr)

    def convert_to_imm_16bytes_align(self, c):
        adr = self.assembler.datablockwrapper.malloc_aligned(16, 16)
        x = c.getfloatstorage()
        y = longlong.ZEROF
        rffi.cast(rffi.CArrayPtr(longlong.FLOATSTORAGE), adr)[0] = x
        rffi.cast(rffi.CArrayPtr(longlong.FLOATSTORAGE), adr)[1] = y
        return ConstFloatLoc(adr)

    def after_call(self, v):
        # the result is stored in st0, but we don't have this around,
        # so genop_call will move it to some frame location immediately
        # after the call
        return self.frame_manager.loc(v)

class X86_64_XMMRegisterManager(X86XMMRegisterManager):
    # xmm15 reserved for scratch use
    all_regs = [xmm0, xmm1, xmm2, xmm3, xmm4, xmm5, xmm6, xmm7, xmm8, xmm9, xmm10, xmm11, xmm12, xmm13, xmm14]
    save_around_call_regs = all_regs

    def call_result_location(self, v):
        return xmm0

    def after_call(self, v):
        # We use RegisterManager's implementation, since X86XMMRegisterManager
        # places the result on the stack, which we don't need to do when the
        # calling convention places the result in xmm0
        return RegisterManager.after_call(self, v)

class X86FrameManager(FrameManager):
    @staticmethod
    def frame_pos(i, box_type):
        if IS_X86_32 and box_type == FLOAT:
            return StackLoc(i, get_ebp_ofs(i+1), box_type)
        else:
            return StackLoc(i, get_ebp_ofs(i), box_type)
    @staticmethod
    def frame_size(box_type):
        if IS_X86_32 and box_type == FLOAT:
            return 2
        else:
            return 1
    @staticmethod
    def get_loc_index(loc):
        assert isinstance(loc, StackLoc)
        return loc.position

if WORD == 4:
    gpr_reg_mgr_cls = X86RegisterManager
    xmm_reg_mgr_cls = X86XMMRegisterManager
elif WORD == 8:
    gpr_reg_mgr_cls = X86_64_RegisterManager
    xmm_reg_mgr_cls = X86_64_XMMRegisterManager
else:
    raise AssertionError("Word size should be 4 or 8")


class RegAlloc(object):

    def __init__(self, assembler, translate_support_code=False):
        assert isinstance(translate_support_code, bool)
        # variables that have place in register
        self.assembler = assembler
        self.translate_support_code = translate_support_code
        # to be read/used by the assembler too
        self.jump_target_descr = None
        self.close_stack_struct = 0
        self.final_jump_op = None

    def _prepare(self, inputargs, operations, allgcrefs):
        self.fm = X86FrameManager()
        self.min_frame_depth = 0
        cpu = self.assembler.cpu
        operations = cpu.gc_ll_descr.rewrite_assembler(cpu, operations,
                                                       allgcrefs)
        # compute longevity of variables
        longevity, last_real_usage = compute_vars_longevity(
                                                    inputargs, operations)
        self.longevity = longevity
        self.last_real_usage = last_real_usage
        self.rm = gpr_reg_mgr_cls(self.longevity,
                                  frame_manager = self.fm,
                                  assembler = self.assembler)
        self.xrm = xmm_reg_mgr_cls(self.longevity, frame_manager = self.fm,
                                   assembler = self.assembler)
        return operations

    def prepare_loop(self, inputargs, operations, looptoken, allgcrefs):
        operations = self._prepare(inputargs, operations, allgcrefs)
        self._set_initial_bindings(inputargs)
        # note: we need to make a copy of inputargs because possibly_free_vars
        # is also used on op args, which is a non-resizable list
        self.possibly_free_vars(list(inputargs))
        if WORD == 4:       # see redirect_call_assembler()
            self.min_bytes_before_label = 5
        else:
            self.min_bytes_before_label = 13
        return operations

    def prepare_bridge(self, inputargs, arglocs, operations, allgcrefs):
        operations = self._prepare(inputargs, operations, allgcrefs)
        self._update_bindings(arglocs, inputargs)
        self.min_bytes_before_label = 0
        return operations

    def ensure_next_label_is_at_least_at_position(self, at_least_position):
        self.min_bytes_before_label = max(self.min_bytes_before_label,
                                          at_least_position)

    def needed_extra_stack_locations(self, n):
        # call *after* you needed extra stack locations: (%esp), (%esp+4)...
        min_frame_depth = self.fm.get_frame_depth() + n
        if min_frame_depth > self.min_frame_depth:
            self.min_frame_depth = min_frame_depth

    def get_final_frame_depth(self):
        self.needed_extra_stack_locations(0)  # update min_frame_depth
        return self.min_frame_depth

    def _set_initial_bindings(self, inputargs):
        if IS_X86_64:
            inputargs = self._set_initial_bindings_regs_64(inputargs)
        #                   ...
        # stack layout:     arg2
        #                   arg1
        #                   arg0
        #                   return address
        #                   saved ebp        <-- ebp points here
        #                   ...
        cur_frame_pos = - 1 - FRAME_FIXED_SIZE
        assert get_ebp_ofs(cur_frame_pos-1) == 2*WORD
        assert get_ebp_ofs(cur_frame_pos-2) == 3*WORD
        #
        for box in inputargs:
            assert isinstance(box, Box)
            #
            if IS_X86_32 and box.type == FLOAT:
                cur_frame_pos -= 2
            else:
                cur_frame_pos -= 1
            loc = self.fm.frame_pos(cur_frame_pos, box.type)
            self.fm.set_binding(box, loc)

    def _set_initial_bindings_regs_64(self, inputargs):
        # In reverse order for use with pop()
        unused_gpr = [r9, r8, ecx, edx, esi, edi]
        unused_xmm = [xmm7, xmm6, xmm5, xmm4, xmm3, xmm2, xmm1, xmm0]
        #
        pass_on_stack = []
        #
        for box in inputargs:
            assert isinstance(box, Box)
            #
            if box.type == FLOAT:
                if len(unused_xmm) > 0:
                    ask = unused_xmm.pop()
                    got = self.xrm.try_allocate_reg(box, selected_reg=ask)
                    assert ask == got
                else:
                    pass_on_stack.append(box)
            else:
                if len(unused_gpr) > 0:
                    ask = unused_gpr.pop()
                    got = self.rm.try_allocate_reg(box, selected_reg=ask)
                    assert ask == got
                else:
                    pass_on_stack.append(box)
        #
        return pass_on_stack

    def possibly_free_var(self, var):
        if var.type == FLOAT:
            self.xrm.possibly_free_var(var)
        else:
            self.rm.possibly_free_var(var)

    def possibly_free_vars_for_op(self, op):
        for i in range(op.numargs()):
            var = op.getarg(i)
            if var is not None: # xxx kludgy
                self.possibly_free_var(var)

    def possibly_free_vars(self, vars):
        for var in vars:
            if var is not None: # xxx kludgy
                self.possibly_free_var(var)

    def make_sure_var_in_reg(self, var, forbidden_vars=[],
                             selected_reg=None, need_lower_byte=False):
        if var.type == FLOAT:
            if isinstance(var, ConstFloat):
                return FloatImmedLoc(var.getfloatstorage())
            return self.xrm.make_sure_var_in_reg(var, forbidden_vars,
                                                 selected_reg, need_lower_byte)
        else:
            return self.rm.make_sure_var_in_reg(var, forbidden_vars,
                                                selected_reg, need_lower_byte)

    def force_allocate_reg(self, var, forbidden_vars=[], selected_reg=None,
                           need_lower_byte=False):
        if var.type == FLOAT:
            return self.xrm.force_allocate_reg(var, forbidden_vars,
                                               selected_reg, need_lower_byte)
        else:
            return self.rm.force_allocate_reg(var, forbidden_vars,
                                              selected_reg, need_lower_byte)

    def force_spill_var(self, var):
        if var.type == FLOAT:
            return self.xrm.force_spill_var(var)
        else:
            return self.rm.force_spill_var(var)

    def load_xmm_aligned_16_bytes(self, var, forbidden_vars=[]):
        # Load 'var' in a register; but if it is a constant, we can return
        # a 16-bytes-aligned ConstFloatLoc.
        if isinstance(var, Const):
            return self.xrm.convert_to_imm_16bytes_align(var)
        else:
            return self.xrm.make_sure_var_in_reg(var, forbidden_vars)

    def _update_bindings(self, locs, inputargs):
        # XXX this should probably go to llsupport/regalloc.py
        used = {}
        i = 0
        for loc in locs:
            if loc is None: # xxx bit kludgy
                continue
            arg = inputargs[i]
            i += 1
            if arg.type == FLOAT:
                if isinstance(loc, RegLoc):
                    self.xrm.reg_bindings[arg] = loc
                    used[loc] = None
                else:
                    self.fm.set_binding(arg, loc)
            else:
                if isinstance(loc, RegLoc):
                    if loc is ebp:
                        self.rm.bindings_to_frame_reg[arg] = None
                    else:
                        self.rm.reg_bindings[arg] = loc
                        used[loc] = None
                else:
                    self.fm.set_binding(arg, loc)
        self.rm.free_regs = []
        for reg in self.rm.all_regs:
            if reg not in used:
                self.rm.free_regs.append(reg)
        self.xrm.free_regs = []
        for reg in self.xrm.all_regs:
            if reg not in used:
                self.xrm.free_regs.append(reg)
        # note: we need to make a copy of inputargs because possibly_free_vars
        # is also used on op args, which is a non-resizable list
        self.possibly_free_vars(list(inputargs))
        self.rm._check_invariants()
        self.xrm._check_invariants()

    def Perform(self, op, arglocs, result_loc):
        if not we_are_translated():
            self.assembler.dump('%s <- %s(%s)' % (result_loc, op, arglocs))
        self.assembler.regalloc_perform(op, arglocs, result_loc)

    def PerformLLong(self, op, arglocs, result_loc):
        if not we_are_translated():
            self.assembler.dump('%s <- %s(%s)' % (result_loc, op, arglocs))
        self.assembler.regalloc_perform_llong(op, arglocs, result_loc)

    def PerformMath(self, op, arglocs, result_loc):
        if not we_are_translated():
            self.assembler.dump('%s <- %s(%s)' % (result_loc, op, arglocs))
        self.assembler.regalloc_perform_math(op, arglocs, result_loc)

    def locs_for_fail(self, guard_op):
        return [self.loc(v) for v in guard_op.getfailargs()]

    def perform_with_guard(self, op, guard_op, arglocs, result_loc):
        faillocs = self.locs_for_fail(guard_op)
        self.rm.position += 1
        self.xrm.position += 1
        self.assembler.regalloc_perform_with_guard(op, guard_op, faillocs,
                                                   arglocs, result_loc)
        if op.result is not None:
            self.possibly_free_var(op.result)
        self.possibly_free_vars(guard_op.getfailargs())

    def perform_guard(self, guard_op, arglocs, result_loc):
        faillocs = self.locs_for_fail(guard_op)
        if not we_are_translated():
            if result_loc is not None:
                self.assembler.dump('%s <- %s(%s)' % (result_loc, guard_op,
                                                      arglocs))
            else:
                self.assembler.dump('%s(%s)' % (guard_op, arglocs))
        self.assembler.regalloc_perform_guard(guard_op, faillocs, arglocs,
                                              result_loc)
        self.possibly_free_vars(guard_op.getfailargs())

    def PerformDiscard(self, op, arglocs):
        if not we_are_translated():
            self.assembler.dump('%s(%s)' % (op, arglocs))
        self.assembler.regalloc_perform_discard(op, arglocs)

    def can_merge_with_next_guard(self, op, i, operations):
        if (op.getopnum() == rop.CALL_MAY_FORCE or
            op.getopnum() == rop.CALL_ASSEMBLER or
            op.getopnum() == rop.CALL_RELEASE_GIL):
            assert operations[i + 1].getopnum() == rop.GUARD_NOT_FORCED
            return True
        if not op.is_comparison():
            if op.is_ovf():
                if (operations[i + 1].getopnum() != rop.GUARD_NO_OVERFLOW and
                    operations[i + 1].getopnum() != rop.GUARD_OVERFLOW):
                    not_implemented("int_xxx_ovf not followed by "
                                    "guard_(no)_overflow")
                return True
            return False
        if (operations[i + 1].getopnum() != rop.GUARD_TRUE and
            operations[i + 1].getopnum() != rop.GUARD_FALSE):
            return False
        if operations[i + 1].getarg(0) is not op.result:
            return False
        if (self.longevity[op.result][1] > i + 1 or
            op.result in operations[i + 1].getfailargs()):
            return False
        return True

    def walk_operations(self, operations):
        i = 0
        #self.operations = operations
        while i < len(operations):
            op = operations[i]
            self.assembler.mc.mark_op(op)
            self.rm.position = i
            self.xrm.position = i
            if op.has_no_side_effect() and op.result not in self.longevity:
                i += 1
                self.possibly_free_vars_for_op(op)
                continue
            if self.can_merge_with_next_guard(op, i, operations):
                oplist_with_guard[op.getopnum()](self, op, operations[i + 1])
                i += 1
            elif not we_are_translated() and op.getopnum() == -124:
                self._consider_force_spill(op)
            else:
                oplist[op.getopnum()](self, op)
            if op.result is not None:
                self.possibly_free_var(op.result)
            self.rm._check_invariants()
            self.xrm._check_invariants()
            i += 1
        assert not self.rm.reg_bindings
        assert not self.xrm.reg_bindings
        self.flush_loop()
        self.assembler.mc.mark_op(None) # end of the loop

    def flush_loop(self):
        # rare case: if the loop is too short, or if we are just after
        # a GUARD_NOT_INVALIDATED, pad with NOPs.  Important!  This must
        # be called to ensure that there are enough bytes produced,
        # because GUARD_NOT_INVALIDATED or redirect_call_assembler()
        # will maybe overwrite them.
        mc = self.assembler.mc
        while mc.get_relative_pos() < self.min_bytes_before_label:
            mc.NOP()

    def loc(self, v):
        if v is None: # xxx kludgy
            return None
        if v.type == FLOAT:
            return self.xrm.loc(v)
        return self.rm.loc(v)

    def _consider_guard(self, op):
        loc = self.rm.make_sure_var_in_reg(op.getarg(0))
        self.perform_guard(op, [loc], None)
        self.rm.possibly_free_var(op.getarg(0))

    consider_guard_true = _consider_guard
    consider_guard_false = _consider_guard
    consider_guard_nonnull = _consider_guard
    consider_guard_isnull = _consider_guard

    def consider_finish(self, op):
        loc = self.loc(op.getarg(0))
        self.Perform(op, [loc], None)
        self.possibly_free_var(op.getarg(0))

    def consider_guard_no_exception(self, op):
        self.perform_guard(op, [], None)

    def consider_guard_not_invalidated(self, op):
        mc = self.assembler.mc
        n = mc.get_relative_pos()
        self.perform_guard(op, [], None)
        assert n == mc.get_relative_pos()
        # ensure that the next label is at least 5 bytes farther than
        # the current position.  Otherwise, when invalidating the guard,
        # we would overwrite randomly the next label's position.
        self.ensure_next_label_is_at_least_at_position(n + 5)

    def consider_guard_exception(self, op):
        loc = self.rm.make_sure_var_in_reg(op.getarg(0))
        box = TempBox()
        args = op.getarglist()
        loc1 = self.rm.force_allocate_reg(box, args)
        if op.result in self.longevity:
            # this means, is it ever used
            resloc = self.rm.force_allocate_reg(op.result, args + [box])
        else:
            resloc = None
        self.perform_guard(op, [loc, loc1], resloc)
        self.rm.possibly_free_vars_for_op(op)
        self.rm.possibly_free_var(box)

    consider_guard_no_overflow = consider_guard_no_exception
    consider_guard_overflow    = consider_guard_no_exception

    def consider_guard_value(self, op):
        x = self.make_sure_var_in_reg(op.getarg(0))
        y = self.loc(op.getarg(1))
        self.perform_guard(op, [x, y], None)
        self.possibly_free_vars_for_op(op)

    def consider_guard_class(self, op):
        assert isinstance(op.getarg(0), Box)
        x = self.rm.make_sure_var_in_reg(op.getarg(0))
        y = self.loc(op.getarg(1))
        self.perform_guard(op, [x, y], None)
        self.rm.possibly_free_vars_for_op(op)

    consider_guard_nonnull_class = consider_guard_class

    def _consider_binop_part(self, op):
        x = op.getarg(0)
        argloc = self.loc(op.getarg(1))
        args = op.getarglist()
        loc = self.rm.force_result_in_reg(op.result, x, args)
        self.rm.possibly_free_var(op.getarg(1))
        return loc, argloc

    def _consider_binop(self, op):
        loc, argloc = self._consider_binop_part(op)
        self.Perform(op, [loc, argloc], loc)

    def _consider_lea(self, op, loc):
        argloc = self.loc(op.getarg(1))
        self.rm.possibly_free_var(op.getarg(0))
        resloc = self.force_allocate_reg(op.result)
        self.Perform(op, [loc, argloc], resloc)

    def consider_int_add(self, op):
        loc = self.loc(op.getarg(0))
        y = op.getarg(1)
        if (isinstance(loc, RegLoc) and
            isinstance(y, ConstInt) and rx86.fits_in_32bits(y.value)):
            self._consider_lea(op, loc)
        else:
            self._consider_binop(op)

    def consider_int_sub(self, op):
        loc = self.loc(op.getarg(0))
        y = op.getarg(1)
        if (isinstance(loc, RegLoc) and
            isinstance(y, ConstInt) and rx86.fits_in_32bits(-y.value)):
            self._consider_lea(op, loc)
        else:
            self._consider_binop(op)

    consider_int_mul = _consider_binop
    consider_int_and = _consider_binop
    consider_int_or  = _consider_binop
    consider_int_xor = _consider_binop

    def _consider_binop_with_guard(self, op, guard_op):
        loc, argloc = self._consider_binop_part(op)
        self.perform_with_guard(op, guard_op, [loc, argloc], loc)

    consider_int_mul_ovf = _consider_binop_with_guard
    consider_int_sub_ovf = _consider_binop_with_guard
    consider_int_add_ovf = _consider_binop_with_guard

    def consider_int_neg(self, op):
        res = self.rm.force_result_in_reg(op.result, op.getarg(0))
        self.Perform(op, [res], res)

    consider_int_invert = consider_int_neg

    def consider_int_lshift(self, op):
        if isinstance(op.getarg(1), Const):
            loc2 = self.rm.convert_to_imm(op.getarg(1))
        else:
            loc2 = self.rm.make_sure_var_in_reg(op.getarg(1), selected_reg=ecx)
        args = op.getarglist()
        loc1 = self.rm.force_result_in_reg(op.result, op.getarg(0), args)
        self.Perform(op, [loc1, loc2], loc1)
        self.rm.possibly_free_vars_for_op(op)

    consider_int_rshift  = consider_int_lshift
    consider_uint_rshift = consider_int_lshift

    def _consider_int_div_or_mod(self, op, resultreg, trashreg):
        l0 = self.rm.make_sure_var_in_reg(op.getarg(0), selected_reg=eax)
        l1 = self.rm.make_sure_var_in_reg(op.getarg(1), selected_reg=ecx)
        l2 = self.rm.force_allocate_reg(op.result, selected_reg=resultreg)
        # the register (eax or edx) not holding what we are looking for
        # will be just trash after that operation
        tmpvar = TempBox()
        self.rm.force_allocate_reg(tmpvar, selected_reg=trashreg)
        assert l0 is eax
        assert l1 is ecx
        assert l2 is resultreg
        self.rm.possibly_free_vars_for_op(op)
        self.rm.possibly_free_var(tmpvar)

    def consider_int_mod(self, op):
        self._consider_int_div_or_mod(op, edx, eax)
        self.Perform(op, [eax, ecx], edx)

    def consider_int_floordiv(self, op):
        self._consider_int_div_or_mod(op, eax, edx)
        self.Perform(op, [eax, ecx], eax)

    consider_uint_floordiv = consider_int_floordiv

    def _consider_compop(self, op, guard_op):
        vx = op.getarg(0)
        vy = op.getarg(1)
        arglocs = [self.loc(vx), self.loc(vy)]
        if (vx in self.rm.reg_bindings or vy in self.rm.reg_bindings or
            isinstance(vx, Const) or isinstance(vy, Const)):
            pass
        else:
            arglocs[0] = self.rm.make_sure_var_in_reg(vx)
        args = op.getarglist()
        self.rm.possibly_free_vars(args)
        if guard_op is None:
            loc = self.rm.force_allocate_reg(op.result, args,
                                             need_lower_byte=True)
            self.Perform(op, arglocs, loc)
        else:
            self.perform_with_guard(op, guard_op, arglocs, None)

    consider_int_lt = _consider_compop
    consider_int_gt = _consider_compop
    consider_int_ge = _consider_compop
    consider_int_le = _consider_compop
    consider_int_ne = _consider_compop
    consider_int_eq = _consider_compop
    consider_uint_gt = _consider_compop
    consider_uint_lt = _consider_compop
    consider_uint_le = _consider_compop
    consider_uint_ge = _consider_compop
    consider_ptr_eq = consider_instance_ptr_eq = _consider_compop
    consider_ptr_ne = consider_instance_ptr_ne = _consider_compop

    def _consider_float_op(self, op):
        loc1 = self.xrm.loc(op.getarg(1))
        args = op.getarglist()
        loc0 = self.xrm.force_result_in_reg(op.result, op.getarg(0), args)
        self.Perform(op, [loc0, loc1], loc0)
        self.xrm.possibly_free_vars_for_op(op)

    consider_float_add = _consider_float_op
    consider_float_sub = _consider_float_op
    consider_float_mul = _consider_float_op
    consider_float_truediv = _consider_float_op

    def _consider_float_cmp(self, op, guard_op):
        vx = op.getarg(0)
        vy = op.getarg(1)
        arglocs = [self.loc(vx), self.loc(vy)]
        if not (isinstance(arglocs[0], RegLoc) or
                isinstance(arglocs[1], RegLoc)):
            if isinstance(vx, Const):
                arglocs[1] = self.xrm.make_sure_var_in_reg(vy)
            else:
                arglocs[0] = self.xrm.make_sure_var_in_reg(vx)
        self.xrm.possibly_free_vars_for_op(op)
        if guard_op is None:
            res = self.rm.force_allocate_reg(op.result, need_lower_byte=True)
            self.Perform(op, arglocs, res)
        else:
            self.perform_with_guard(op, guard_op, arglocs, None)

    consider_float_lt = _consider_float_cmp
    consider_float_le = _consider_float_cmp
    consider_float_eq = _consider_float_cmp
    consider_float_ne = _consider_float_cmp
    consider_float_gt = _consider_float_cmp
    consider_float_ge = _consider_float_cmp

    def _consider_float_unary_op(self, op):
        loc0 = self.xrm.force_result_in_reg(op.result, op.getarg(0))
        self.Perform(op, [loc0], loc0)
        self.xrm.possibly_free_var(op.getarg(0))

    consider_float_neg = _consider_float_unary_op
    consider_float_abs = _consider_float_unary_op

    def consider_cast_float_to_int(self, op):
        loc0 = self.xrm.make_sure_var_in_reg(op.getarg(0))
        loc1 = self.rm.force_allocate_reg(op.result)
        self.Perform(op, [loc0], loc1)
        self.xrm.possibly_free_var(op.getarg(0))

    def consider_cast_int_to_float(self, op):
        loc0 = self.rm.make_sure_var_in_reg(op.getarg(0))
        loc1 = self.xrm.force_allocate_reg(op.result)
        self.Perform(op, [loc0], loc1)
        self.rm.possibly_free_var(op.getarg(0))

    def consider_cast_float_to_singlefloat(self, op):
        loc0 = self.xrm.make_sure_var_in_reg(op.getarg(0))
        loc1 = self.rm.force_allocate_reg(op.result)
        self.xrm.possibly_free_var(op.getarg(0))
        tmpxvar = TempBox()
        loctmp = self.xrm.force_allocate_reg(tmpxvar)   # may be equal to loc0
        self.xrm.possibly_free_var(tmpxvar)
        self.Perform(op, [loc0, loctmp], loc1)

    consider_cast_singlefloat_to_float = consider_cast_int_to_float

    def consider_convert_float_bytes_to_longlong(self, op):
        if longlong.is_64_bit:
            loc0 = self.xrm.make_sure_var_in_reg(op.getarg(0))
            loc1 = self.rm.force_allocate_reg(op.result)
            self.Perform(op, [loc0], loc1)
            self.xrm.possibly_free_var(op.getarg(0))
        else:
            arg0 = op.getarg(0)
            loc0 = self.xrm.loc(arg0)
            loc1 = self.xrm.force_allocate_reg(op.result, forbidden_vars=[arg0])
            self.Perform(op, [loc0], loc1)
            self.xrm.possibly_free_var(arg0)

    def consider_convert_longlong_bytes_to_float(self, op):
        if longlong.is_64_bit:
            loc0 = self.rm.make_sure_var_in_reg(op.getarg(0))
            loc1 = self.xrm.force_allocate_reg(op.result)
            self.Perform(op, [loc0], loc1)
            self.rm.possibly_free_var(op.getarg(0))
        else:
            arg0 = op.getarg(0)
            loc0 = self.xrm.make_sure_var_in_reg(arg0)
            loc1 = self.xrm.force_allocate_reg(op.result, forbidden_vars=[arg0])
            self.Perform(op, [loc0], loc1)
            self.xrm.possibly_free_var(arg0)

    def _consider_llong_binop_xx(self, op):
        # must force both arguments into xmm registers, because we don't
        # know if they will be suitably aligned.  Exception: if the second
        # argument is a constant, we can ask it to be aligned to 16 bytes.
        args = [op.getarg(1), op.getarg(2)]
        loc1 = self.load_xmm_aligned_16_bytes(args[1])
        loc0 = self.xrm.force_result_in_reg(op.result, args[0], args)
        self.PerformLLong(op, [loc0, loc1], loc0)
        self.xrm.possibly_free_vars(args)

    def _consider_llong_eq_ne_xx(self, op):
        # must force both arguments into xmm registers, because we don't
        # know if they will be suitably aligned.  Exception: if they are
        # constants, we can ask them to be aligned to 16 bytes.
        args = [op.getarg(1), op.getarg(2)]
        loc1 = self.load_xmm_aligned_16_bytes(args[0])
        loc2 = self.load_xmm_aligned_16_bytes(args[1], args)
        tmpxvar = TempBox()
        loc3 = self.xrm.force_allocate_reg(tmpxvar, args)
        self.xrm.possibly_free_var(tmpxvar)
        loc0 = self.rm.force_allocate_reg(op.result, need_lower_byte=True)
        self.PerformLLong(op, [loc1, loc2, loc3], loc0)
        self.xrm.possibly_free_vars(args)

    def _maybe_consider_llong_lt(self, op):
        # XXX just a special case for now
        box = op.getarg(2)
        if not isinstance(box, ConstFloat):
            return False
        if box.getlonglong() != 0:
            return False
        # "x < 0"
        box = op.getarg(1)
        assert isinstance(box, BoxFloat)
        loc1 = self.xrm.make_sure_var_in_reg(box)
        loc0 = self.rm.force_allocate_reg(op.result)
        self.PerformLLong(op, [loc1], loc0)
        self.xrm.possibly_free_var(box)
        return True

    def _consider_llong_to_int(self, op):
        # accept an argument in a xmm register or in the stack
        loc1 = self.xrm.loc(op.getarg(1))
        loc0 = self.rm.force_allocate_reg(op.result)
        self.PerformLLong(op, [loc1], loc0)
        self.xrm.possibly_free_var(op.getarg(1))

    def _loc_of_const_longlong(self, value64):
        c = ConstFloat(value64)
        return self.xrm.convert_to_imm(c)

    def _consider_llong_from_int(self, op):
        assert IS_X86_32
        loc0 = self.xrm.force_allocate_reg(op.result)
        box = op.getarg(1)
        if isinstance(box, ConstInt):
            loc1 = self._loc_of_const_longlong(r_longlong(box.value))
            loc2 = None    # unused
        else:
            loc1 = self.rm.make_sure_var_in_reg(box)
            tmpxvar = TempBox()
            loc2 = self.xrm.force_allocate_reg(tmpxvar, [op.result])
            self.xrm.possibly_free_var(tmpxvar)
        self.PerformLLong(op, [loc1, loc2], loc0)
        self.rm.possibly_free_var(box)

    def _consider_llong_from_uint(self, op):
        assert IS_X86_32
        loc0 = self.xrm.force_allocate_reg(op.result)
        loc1 = self.rm.make_sure_var_in_reg(op.getarg(1))
        self.PerformLLong(op, [loc1], loc0)
        self.rm.possibly_free_vars_for_op(op)

    def _consider_math_sqrt(self, op):
        loc0 = self.xrm.force_result_in_reg(op.result, op.getarg(1))
        self.PerformMath(op, [loc0], loc0)
        self.xrm.possibly_free_var(op.getarg(1))

    def _call(self, op, arglocs, force_store=[], guard_not_forced_op=None):
        # we need to save registers on the stack:
        #
        #  - at least the non-callee-saved registers
        #
        #  - for shadowstack, we assume that any call can collect, and we
        #    save also the callee-saved registers that contain GC pointers,
        #    so that they can be found by follow_stack_frame_of_assembler()
        #
        #  - for CALL_MAY_FORCE or CALL_ASSEMBLER, we have to save all regs
        #    anyway, in case we need to do cpu.force().  The issue is that
        #    grab_frame_values() would not be able to locate values in
        #    callee-saved registers.
        #
        save_all_regs = guard_not_forced_op is not None
        self.xrm.before_call(force_store, save_all_regs=save_all_regs)
        if not save_all_regs:
            gcrootmap = self.assembler.cpu.gc_ll_descr.gcrootmap
            if gcrootmap and gcrootmap.is_shadow_stack:
                save_all_regs = 2
        self.rm.before_call(force_store, save_all_regs=save_all_regs)
        if op.result is not None:
            if op.result.type == FLOAT:
                resloc = self.xrm.after_call(op.result)
            else:
                resloc = self.rm.after_call(op.result)
        else:
            resloc = None
        if guard_not_forced_op is not None:
            self.perform_with_guard(op, guard_not_forced_op, arglocs, resloc)
        else:
            self.Perform(op, arglocs, resloc)

    def _consider_call(self, op, guard_not_forced_op=None):
        calldescr = op.getdescr()
        assert isinstance(calldescr, CallDescr)
        assert len(calldescr.arg_classes) == op.numargs() - 1
        size = calldescr.get_result_size()
        sign = calldescr.is_result_signed()
        if sign:
            sign_loc = imm1
        else:
            sign_loc = imm0
        self._call(op, [imm(size), sign_loc] +
                       [self.loc(op.getarg(i)) for i in range(op.numargs())],
                   guard_not_forced_op=guard_not_forced_op)

    def consider_call(self, op):
        effectinfo = op.getdescr().get_extra_info()
        oopspecindex = effectinfo.oopspecindex
        if oopspecindex != EffectInfo.OS_NONE:
            if IS_X86_32:
                # support for some of the llong operations,
                # which only exist on x86-32
                if oopspecindex in (EffectInfo.OS_LLONG_ADD,
                                    EffectInfo.OS_LLONG_SUB,
                                    EffectInfo.OS_LLONG_AND,
                                    EffectInfo.OS_LLONG_OR,
                                    EffectInfo.OS_LLONG_XOR):
                    return self._consider_llong_binop_xx(op)
                if oopspecindex == EffectInfo.OS_LLONG_TO_INT:
                    return self._consider_llong_to_int(op)
                if oopspecindex == EffectInfo.OS_LLONG_FROM_INT:
                    return self._consider_llong_from_int(op)
                if oopspecindex == EffectInfo.OS_LLONG_FROM_UINT:
                    return self._consider_llong_from_uint(op)
                if (oopspecindex == EffectInfo.OS_LLONG_EQ or
                    oopspecindex == EffectInfo.OS_LLONG_NE):
                    return self._consider_llong_eq_ne_xx(op)
                if oopspecindex == EffectInfo.OS_LLONG_LT:
                    if self._maybe_consider_llong_lt(op):
                        return
            if oopspecindex == EffectInfo.OS_MATH_SQRT:
                return self._consider_math_sqrt(op)
        self._consider_call(op)

    def consider_call_may_force(self, op, guard_op):
        assert guard_op is not None
        self._consider_call(op, guard_op)

    consider_call_release_gil = consider_call_may_force

    def consider_call_malloc_gc(self, op):
        self._consider_call(op)

    def consider_call_assembler(self, op, guard_op):
        descr = op.getdescr()
        assert isinstance(descr, JitCellToken)
        jd = descr.outermost_jitdriver_sd
        assert jd is not None
        size = jd.portal_calldescr.get_result_size()
        vable_index = jd.index_of_virtualizable
        if vable_index >= 0:
            self.rm._sync_var(op.getarg(vable_index))
            vable = self.fm.loc(op.getarg(vable_index))
        else:
            vable = imm0
        self._call(op, [imm(size), vable] +
                   [self.loc(op.getarg(i)) for i in range(op.numargs())],
                   guard_not_forced_op=guard_op)

    def consider_cond_call_gc_wb(self, op):
        assert op.result is None
        args = op.getarglist()
        N = len(args)
        # we force all arguments in a reg (unless they are Consts),
        # because it will be needed anyway by the following setfield_gc
        # or setarrayitem_gc. It avoids loading it twice from the memory.
        arglocs = [self.rm.make_sure_var_in_reg(op.getarg(i), args)
                   for i in range(N)]
        self.PerformDiscard(op, arglocs)
        self.rm.possibly_free_vars_for_op(op)

    consider_cond_call_gc_wb_array = consider_cond_call_gc_wb

    def consider_call_malloc_nursery(self, op):
        size_box = op.getarg(0)
        assert isinstance(size_box, ConstInt)
        size = size_box.getint()
        self.rm.force_allocate_reg(op.result, selected_reg=eax)
        #
        # We need edx as a temporary, but otherwise don't save any more
        # register.  See comments in _build_malloc_slowpath().
        tmp_box = TempBox()
        self.rm.force_allocate_reg(tmp_box, selected_reg=edx)
        self.rm.possibly_free_var(tmp_box)
        #
        gc_ll_descr = self.assembler.cpu.gc_ll_descr
        self.assembler.malloc_cond(
            gc_ll_descr.get_nursery_free_addr(),
            gc_ll_descr.get_nursery_top_addr(),
            size)


    def consider_setfield_gc(self, op):
        ofs, size, _ = unpack_fielddescr(op.getdescr())
        ofs_loc = imm(ofs)
        size_loc = imm(size)
        assert isinstance(size_loc, ImmedLoc)
        if size_loc.value == 1:
            need_lower_byte = True
        else:
            need_lower_byte = False
        args = op.getarglist()
        base_loc = self.rm.make_sure_var_in_reg(op.getarg(0), args)
        value_loc = self.make_sure_var_in_reg(op.getarg(1), args,
                                              need_lower_byte=need_lower_byte)
        self.possibly_free_vars(args)
        self.PerformDiscard(op, [base_loc, ofs_loc, size_loc, value_loc])

    consider_setfield_raw = consider_setfield_gc

    def consider_setinteriorfield_gc(self, op):
        t = unpack_interiorfielddescr(op.getdescr())
        ofs, itemsize, fieldsize = imm(t[0]), imm(t[1]), imm(t[2])
        args = op.getarglist()
        if fieldsize.value == 1:
            need_lower_byte = True
        else:
            need_lower_byte = False
        box_base, box_index, box_value = args
        base_loc = self.rm.make_sure_var_in_reg(box_base, args)
        index_loc = self.rm.make_sure_var_in_reg(box_index, args)
        value_loc = self.make_sure_var_in_reg(box_value, args,
                                              need_lower_byte=need_lower_byte)
        # If 'index_loc' is not an immediate, then we need a 'temp_loc' that
        # is a register whose value will be destroyed.  It's fine to destroy
        # the same register as 'index_loc', but not the other ones.
        if not isinstance(index_loc, ImmedLoc):
            # ...that is, except in a corner case where 'index_loc' would be
            # in the same register as 'value_loc'...
            if index_loc is not value_loc:
                self.rm.possibly_free_var(box_index)
            tempvar = TempBox()
            temp_loc = self.rm.force_allocate_reg(tempvar, [box_base,
                                                            box_value])
            self.rm.possibly_free_var(tempvar)
        else:
            temp_loc = None
        self.rm.possibly_free_var(box_index)
        self.rm.possibly_free_var(box_base)
        self.possibly_free_var(box_value)
        self.PerformDiscard(op, [base_loc, ofs, itemsize, fieldsize,
                                 index_loc, temp_loc, value_loc])

    consider_setinteriorfield_raw = consider_setinteriorfield_gc

    def consider_strsetitem(self, op):
        args = op.getarglist()
        base_loc = self.rm.make_sure_var_in_reg(op.getarg(0), args)
        ofs_loc = self.rm.make_sure_var_in_reg(op.getarg(1), args)
        value_loc = self.rm.make_sure_var_in_reg(op.getarg(2), args,
                                                 need_lower_byte=True)
        self.rm.possibly_free_vars_for_op(op)
        self.PerformDiscard(op, [base_loc, ofs_loc, value_loc])

    consider_unicodesetitem = consider_strsetitem

    def consider_setarrayitem_gc(self, op):
        itemsize, ofs, _ = unpack_arraydescr(op.getdescr())
        args = op.getarglist()
        base_loc  = self.rm.make_sure_var_in_reg(op.getarg(0), args)
        if itemsize == 1:
            need_lower_byte = True
        else:
            need_lower_byte = False
        value_loc = self.make_sure_var_in_reg(op.getarg(2), args,
                                          need_lower_byte=need_lower_byte)
        ofs_loc = self.rm.make_sure_var_in_reg(op.getarg(1), args)
        self.possibly_free_vars(args)
        self.PerformDiscard(op, [base_loc, ofs_loc, value_loc,
                                 imm(itemsize), imm(ofs)])

    consider_setarrayitem_raw = consider_setarrayitem_gc
    consider_raw_store = consider_setarrayitem_gc

    def consider_getfield_gc(self, op):
        ofs, size, sign = unpack_fielddescr(op.getdescr())
        ofs_loc = imm(ofs)
        size_loc = imm(size)
        args = op.getarglist()
        base_loc = self.rm.make_sure_var_in_reg(op.getarg(0), args)
        self.rm.possibly_free_vars(args)
        result_loc = self.force_allocate_reg(op.result)
        if sign:
            sign_loc = imm1
        else:
            sign_loc = imm0
        self.Perform(op, [base_loc, ofs_loc, size_loc, sign_loc], result_loc)

    consider_getfield_raw = consider_getfield_gc
    consider_getfield_raw_pure = consider_getfield_gc
    consider_getfield_gc_pure = consider_getfield_gc

    def consider_getarrayitem_gc(self, op):
        itemsize, ofs, sign = unpack_arraydescr(op.getdescr())
        args = op.getarglist()
        base_loc = self.rm.make_sure_var_in_reg(op.getarg(0), args)
        ofs_loc = self.rm.make_sure_var_in_reg(op.getarg(1), args)
        self.rm.possibly_free_vars_for_op(op)
        result_loc = self.force_allocate_reg(op.result)
        if sign:
            sign_loc = imm1
        else:
            sign_loc = imm0
        self.Perform(op, [base_loc, ofs_loc, imm(itemsize), imm(ofs),
                          sign_loc], result_loc)

    consider_getarrayitem_raw = consider_getarrayitem_gc
    consider_getarrayitem_gc_pure = consider_getarrayitem_gc
    consider_getarrayitem_raw_pure = consider_getarrayitem_gc
    consider_raw_load = consider_getarrayitem_gc

    def consider_getinteriorfield_gc(self, op):
        t = unpack_interiorfielddescr(op.getdescr())
        ofs, itemsize, fieldsize, sign = imm(t[0]), imm(t[1]), imm(t[2]), t[3]
        if sign:
            sign_loc = imm1
        else:
            sign_loc = imm0
        args = op.getarglist()
        base_loc = self.rm.make_sure_var_in_reg(op.getarg(0), args)
        index_loc = self.rm.make_sure_var_in_reg(op.getarg(1), args)
        # 'base' and 'index' are put in two registers (or one if 'index'
        # is an immediate).  'result' can be in the same register as
        # 'index' but must be in a different register than 'base'.
        self.rm.possibly_free_var(op.getarg(1))
        result_loc = self.force_allocate_reg(op.result, [op.getarg(0)])
        assert isinstance(result_loc, RegLoc)
        # two cases: 1) if result_loc is a normal register, use it as temp_loc
        if not result_loc.is_xmm:
            temp_loc = result_loc
        else:
            # 2) if result_loc is an xmm register, we (likely) need another
            # temp_loc that is a normal register.  It can be in the same
            # register as 'index' but not 'base'.
            tempvar = TempBox()
            temp_loc = self.rm.force_allocate_reg(tempvar, [op.getarg(0)])
            self.rm.possibly_free_var(tempvar)
        self.rm.possibly_free_var(op.getarg(0))
        self.Perform(op, [base_loc, ofs, itemsize, fieldsize,
                          index_loc, temp_loc, sign_loc], result_loc)

    def consider_int_is_true(self, op, guard_op):
        # doesn't need arg to be in a register
        argloc = self.loc(op.getarg(0))
        self.rm.possibly_free_var(op.getarg(0))
        if guard_op is not None:
            self.perform_with_guard(op, guard_op, [argloc], None)
        else:
            resloc = self.rm.force_allocate_reg(op.result, need_lower_byte=True)
            self.Perform(op, [argloc], resloc)

    consider_int_is_zero = consider_int_is_true

    def consider_same_as(self, op):
        argloc = self.loc(op.getarg(0))
        self.possibly_free_var(op.getarg(0))
        resloc = self.force_allocate_reg(op.result)
        self.Perform(op, [argloc], resloc)
    consider_cast_ptr_to_int = consider_same_as
    consider_cast_int_to_ptr = consider_same_as

    def consider_int_force_ge_zero(self, op):
        argloc = self.make_sure_var_in_reg(op.getarg(0))
        resloc = self.force_allocate_reg(op.result, [op.getarg(0)])
        self.possibly_free_var(op.getarg(0))
        self.Perform(op, [argloc], resloc)

    def consider_strlen(self, op):
        args = op.getarglist()
        base_loc = self.rm.make_sure_var_in_reg(op.getarg(0), args)
        self.rm.possibly_free_vars_for_op(op)
        result_loc = self.rm.force_allocate_reg(op.result)
        self.Perform(op, [base_loc], result_loc)

    consider_unicodelen = consider_strlen

    def consider_arraylen_gc(self, op):
        arraydescr = op.getdescr()
        assert isinstance(arraydescr, ArrayDescr)
        ofs = arraydescr.lendescr.offset
        args = op.getarglist()
        base_loc = self.rm.make_sure_var_in_reg(op.getarg(0), args)
        self.rm.possibly_free_vars_for_op(op)
        result_loc = self.rm.force_allocate_reg(op.result)
        self.Perform(op, [base_loc, imm(ofs)], result_loc)

    def consider_strgetitem(self, op):
        args = op.getarglist()
        base_loc = self.rm.make_sure_var_in_reg(op.getarg(0), args)
        ofs_loc = self.rm.make_sure_var_in_reg(op.getarg(1), args)
        self.rm.possibly_free_vars_for_op(op)
        result_loc = self.rm.force_allocate_reg(op.result)
        self.Perform(op, [base_loc, ofs_loc], result_loc)

    consider_unicodegetitem = consider_strgetitem

    def consider_copystrcontent(self, op):
        self._consider_copystrcontent(op, is_unicode=False)

    def consider_copyunicodecontent(self, op):
        self._consider_copystrcontent(op, is_unicode=True)

    def _consider_copystrcontent(self, op, is_unicode):
        # compute the source address
        args = op.getarglist()
        base_loc = self.rm.make_sure_var_in_reg(args[0], args)
        ofs_loc = self.rm.make_sure_var_in_reg(args[2], args)
        assert args[0] is not args[1]    # forbidden case of aliasing
        self.rm.possibly_free_var(args[0])
        if args[3] is not args[2] is not args[4]:  # MESS MESS MESS: don't free
            self.rm.possibly_free_var(args[2])     # it if ==args[3] or args[4]
        srcaddr_box = TempBox()
        forbidden_vars = [args[1], args[3], args[4], srcaddr_box]
        srcaddr_loc = self.rm.force_allocate_reg(srcaddr_box, forbidden_vars)
        self._gen_address_inside_string(base_loc, ofs_loc, srcaddr_loc,
                                        is_unicode=is_unicode)
        # compute the destination address
        base_loc = self.rm.make_sure_var_in_reg(args[1], forbidden_vars)
        ofs_loc = self.rm.make_sure_var_in_reg(args[3], forbidden_vars)
        self.rm.possibly_free_var(args[1])
        if args[3] is not args[4]:     # more of the MESS described above
            self.rm.possibly_free_var(args[3])
        forbidden_vars = [args[4], srcaddr_box]
        dstaddr_box = TempBox()
        dstaddr_loc = self.rm.force_allocate_reg(dstaddr_box, forbidden_vars)
        self._gen_address_inside_string(base_loc, ofs_loc, dstaddr_loc,
                                        is_unicode=is_unicode)
        # compute the length in bytes
        length_box = args[4]
        length_loc = self.loc(length_box)
        if is_unicode:
            self.rm.possibly_free_var(length_box)
            forbidden_vars = [srcaddr_box, dstaddr_box]
            bytes_box = TempBox()
            bytes_loc = self.rm.force_allocate_reg(bytes_box, forbidden_vars)
            scale = self._get_unicode_item_scale()
            if not (isinstance(length_loc, ImmedLoc) or
                    isinstance(length_loc, RegLoc)):
                self.assembler.mov(length_loc, bytes_loc)
                length_loc = bytes_loc
            self.assembler.load_effective_addr(length_loc, 0, scale, bytes_loc)
            length_box = bytes_box
            length_loc = bytes_loc
        # call memcpy()
        self.rm.before_call()
        self.xrm.before_call()
        self.assembler._emit_call(-1, imm(self.assembler.memcpy_addr),
                                  [dstaddr_loc, srcaddr_loc, length_loc])
        self.rm.possibly_free_var(length_box)
        self.rm.possibly_free_var(dstaddr_box)
        self.rm.possibly_free_var(srcaddr_box)

    def _gen_address_inside_string(self, baseloc, ofsloc, resloc, is_unicode):
        if is_unicode:
            ofs_items, _, _ = symbolic.get_array_token(rstr.UNICODE,
                                                  self.translate_support_code)
            scale = self._get_unicode_item_scale()
        else:
            ofs_items, itemsize, _ = symbolic.get_array_token(rstr.STR,
                                                  self.translate_support_code)
            assert itemsize == 1
            scale = 0
        self.assembler.load_effective_addr(ofsloc, ofs_items, scale,
                                           resloc, baseloc)

    def _get_unicode_item_scale(self):
        _, itemsize, _ = symbolic.get_array_token(rstr.UNICODE,
                                                  self.translate_support_code)
        if itemsize == 4:
            return 2
        elif itemsize == 2:
            return 1
        else:
            raise AssertionError("bad unicode item size")

    def consider_read_timestamp(self, op):
        tmpbox_high = TempBox()
        self.rm.force_allocate_reg(tmpbox_high, selected_reg=eax)
        if longlong.is_64_bit:
            # on 64-bit, use rax as temporary register and returns the
            # result in rdx
            result_loc = self.rm.force_allocate_reg(op.result,
                                                    selected_reg=edx)
            self.Perform(op, [], result_loc)
        else:
            # on 32-bit, use both eax and edx as temporary registers,
            # use a temporary xmm register, and returns the result in
            # another xmm register.
            tmpbox_low = TempBox()
            self.rm.force_allocate_reg(tmpbox_low, selected_reg=edx)
            xmmtmpbox = TempBox()
            xmmtmploc = self.xrm.force_allocate_reg(xmmtmpbox)
            result_loc = self.xrm.force_allocate_reg(op.result)
            self.Perform(op, [xmmtmploc], result_loc)
            self.xrm.possibly_free_var(xmmtmpbox)
            self.rm.possibly_free_var(tmpbox_low)
        self.rm.possibly_free_var(tmpbox_high)

    def compute_hint_frame_locations(self, operations):
        # optimization only: fill in the 'hint_frame_locations' dictionary
        # of 'fm' based on the JUMP at the end of the loop, by looking
        # at where we would like the boxes to be after the jump.
        op = operations[-1]
        if op.getopnum() != rop.JUMP:
            return
        self.final_jump_op = op
        descr = op.getdescr()
        assert isinstance(descr, TargetToken)
        if descr._x86_loop_code != 0:
            # if the target LABEL was already compiled, i.e. if it belongs
            # to some already-compiled piece of code
            self._compute_hint_frame_locations_from_descr(descr)
        #else:
        #   The loop ends in a JUMP going back to a LABEL in the same loop.
        #   We cannot fill 'hint_frame_locations' immediately, but we can
        #   wait until the corresponding consider_label() to know where the
        #   we would like the boxes to be after the jump.

    def _compute_hint_frame_locations_from_descr(self, descr):
        arglocs = descr._x86_arglocs
        jump_op = self.final_jump_op
        assert len(arglocs) == jump_op.numargs()
        for i in range(jump_op.numargs()):
            box = jump_op.getarg(i)
            if isinstance(box, Box):
                loc = arglocs[i]
                if isinstance(loc, StackLoc):
                    self.fm.hint_frame_locations[box] = loc

    def consider_jump(self, op):
        assembler = self.assembler
        assert self.jump_target_descr is None
        descr = op.getdescr()
        assert isinstance(descr, TargetToken)
        arglocs = descr._x86_arglocs
        self.jump_target_descr = descr
        # Part about non-floats
        src_locations1 = []
        dst_locations1 = []
        # Part about floats
        src_locations2 = []
        dst_locations2 = []
        # Build the four lists
        for i in range(op.numargs()):
            box = op.getarg(i)
            src_loc = self.loc(box)
            dst_loc = arglocs[i]
            if box.type != FLOAT:
                src_locations1.append(src_loc)
                dst_locations1.append(dst_loc)
            else:
                src_locations2.append(src_loc)
                dst_locations2.append(dst_loc)
        # Do we have a temp var?
        if IS_X86_64:
            tmpreg = X86_64_SCRATCH_REG
            xmmtmp = X86_64_XMM_SCRATCH_REG
        else:
            tmpreg = None
            xmmtmp = None
        # Do the remapping
        remap_frame_layout_mixed(assembler,
                                 src_locations1, dst_locations1, tmpreg,
                                 src_locations2, dst_locations2, xmmtmp)
        self.possibly_free_vars_for_op(op)
        assembler.closing_jump(self.jump_target_descr)

    def consider_debug_merge_point(self, op):
        pass

    def consider_jit_debug(self, op):
        pass

    def _consider_force_spill(self, op):
        # This operation is used only for testing
        self.force_spill_var(op.getarg(0))

    def get_mark_gc_roots(self, gcrootmap, use_copy_area=False):
        shape = gcrootmap.get_basic_shape()
        for v, val in self.fm.bindings.items():
            if (isinstance(v, BoxPtr) and self.rm.stays_alive(v)):
                assert isinstance(val, StackLoc)
                gcrootmap.add_frame_offset(shape, get_ebp_ofs(val.position))
        for v, reg in self.rm.reg_bindings.items():
            if reg is eax:
                continue      # ok to ignore this one
            if (isinstance(v, BoxPtr) and self.rm.stays_alive(v)):
                #
                # The register 'reg' is alive across this call.
                gcrootmap = self.assembler.cpu.gc_ll_descr.gcrootmap
                if gcrootmap is None or not gcrootmap.is_shadow_stack:
                    #
                    # Asmgcc: if reg is a callee-save register, we can
                    # explicitly mark it as containing a BoxPtr.
                    if reg in self.rm.REGLOC_TO_GCROOTMAP_REG_INDEX:
                        gcrootmap.add_callee_save_reg(
                            shape, self.rm.REGLOC_TO_GCROOTMAP_REG_INDEX[reg])
                        continue
                #
                # Else, 'use_copy_area' must be True (otherwise this BoxPtr
                # should not be in a register).  The copy area contains the
                # real value of the register.
                assert use_copy_area
                assert reg in self.rm.REGLOC_TO_COPY_AREA_OFS
                area_offset = self.rm.REGLOC_TO_COPY_AREA_OFS[reg]
                gcrootmap.add_frame_offset(shape, area_offset)
        #
        return gcrootmap.compress_callshape(shape,
                                            self.assembler.datablockwrapper)

    def consider_force_token(self, op):
        # the FORCE_TOKEN operation returns directly 'ebp'
        self.rm.force_allocate_frame_reg(op.result)

    def consider_label(self, op):
        descr = op.getdescr()
        assert isinstance(descr, TargetToken)
        inputargs = op.getarglist()
        arglocs = [None] * len(inputargs)
        #
        # we use force_spill() on the boxes that are not going to be really
        # used any more in the loop, but that are kept alive anyway
        # by being in a next LABEL's or a JUMP's argument or fail_args
        # of some guard
        position = self.rm.position
        for arg in inputargs:
            assert isinstance(arg, Box)
            if self.last_real_usage.get(arg, -1) <= position:
                self.force_spill_var(arg)
        #
        # we need to make sure that no variable is stored in ebp
        for arg in inputargs:
            if self.loc(arg) is ebp:
                loc2 = self.fm.loc(arg)
                self.assembler.mc.MOV(loc2, ebp)
        self.rm.bindings_to_frame_reg.clear()
        #
        for i in range(len(inputargs)):
            arg = inputargs[i]
            assert isinstance(arg, Box)
            loc = self.loc(arg)
            assert loc is not ebp
            arglocs[i] = loc
            if isinstance(loc, RegLoc):
                self.fm.mark_as_free(arg)
        #
        # if we are too close to the start of the loop, the label's target may
        # get overridden by redirect_call_assembler().  (rare case)
        self.flush_loop()
        #
        descr._x86_arglocs = arglocs
        descr._x86_loop_code = self.assembler.mc.get_relative_pos()
        descr._x86_clt = self.assembler.current_clt
        self.assembler.target_tokens_currently_compiling[descr] = None
        self.possibly_free_vars_for_op(op)
        #
        # if the LABEL's descr is precisely the target of the JUMP at the
        # end of the same loop, i.e. if what we are compiling is a single
        # loop that ends up jumping to this LABEL, then we can now provide
        # the hints about the expected position of the spilled variables.
        jump_op = self.final_jump_op
        if jump_op is not None and jump_op.getdescr() is descr:
            self._compute_hint_frame_locations_from_descr(descr)

    def consider_keepalive(self, op):
        pass

    def not_implemented_op(self, op):
        not_implemented("not implemented operation: %s" % op.getopname())

    def not_implemented_op_with_guard(self, op, guard_op):
        not_implemented("not implemented operation with guard: %s" % (
            op.getopname(),))

oplist = [RegAlloc.not_implemented_op] * rop._LAST
oplist_with_guard = [RegAlloc.not_implemented_op_with_guard] * rop._LAST

def add_none_argument(fn):
    return lambda self, op: fn(self, op, None)

for name, value in RegAlloc.__dict__.iteritems():
    if name.startswith('consider_'):
        name = name[len('consider_'):]
        num = getattr(rop, name.upper())
        if (is_comparison_or_ovf_op(num)
            or num == rop.CALL_MAY_FORCE
            or num == rop.CALL_ASSEMBLER
            or num == rop.CALL_RELEASE_GIL):
            oplist_with_guard[num] = value
            oplist[num] = add_none_argument(value)
        else:
            oplist[num] = value

def get_ebp_ofs(position):
    # Argument is a frame position (0, 1, 2...).
    # Returns (ebp-20), (ebp-24), (ebp-28)...
    # i.e. the n'th word beyond the fixed frame size.
    return -WORD * (FRAME_FIXED_SIZE + position)

def _valid_addressing_size(size):
    return size == 1 or size == 2 or size == 4 or size == 8

def _get_scale(size):
    assert _valid_addressing_size(size)
    if size < 4:
        return size - 1         # 1, 2 => 0, 1
    else:
        return (size >> 2) + 1  # 4, 8 => 2, 3

def not_implemented(msg):
    os.write(2, '[x86/regalloc] %s\n' % msg)
    raise NotImplementedError(msg)

# xxx hack: set a default value for TargetToken._x86_loop_code.
# If 0, we know that it is a LABEL that was not compiled yet.
TargetToken._x86_loop_code = 0
