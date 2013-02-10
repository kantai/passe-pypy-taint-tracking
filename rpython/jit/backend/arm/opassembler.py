from __future__ import with_statement
from rpython.jit.backend.arm import conditions as c
from rpython.jit.backend.arm import registers as r
from rpython.jit.backend.arm import shift
from rpython.jit.backend.arm.arch import WORD, DOUBLE_WORD

from rpython.jit.backend.arm.helper.assembler import (gen_emit_op_by_helper_call,
                                                gen_emit_op_unary_cmp,
                                                gen_emit_guard_unary_cmp,
                                                gen_emit_op_ri,
                                                gen_emit_cmp_op,
                                                gen_emit_cmp_op_guard,
                                                gen_emit_float_op,
                                                gen_emit_float_cmp_op,
                                                gen_emit_float_cmp_op_guard,
                                                gen_emit_unary_float_op,
                                                saved_registers,
                                                count_reg_args)
from rpython.jit.backend.arm.helper.regalloc import check_imm_arg
from rpython.jit.backend.arm.codebuilder import ARMv7Builder, OverwritingBuilder
from rpython.jit.backend.arm.jump import remap_frame_layout
from rpython.jit.backend.arm.regalloc import TempInt, TempPtr
from rpython.jit.backend.arm.locations import imm
from rpython.jit.backend.llsupport import symbolic
from rpython.jit.backend.llsupport.descr import InteriorFieldDescr
from rpython.jit.metainterp.history import (Box, AbstractFailDescr,
                                            INT, FLOAT, REF)
from rpython.jit.metainterp.history import JitCellToken, TargetToken
from rpython.jit.metainterp.resoperation import rop
from rpython.rlib.objectmodel import we_are_translated
from rpython.rlib import rgc
from rpython.rtyper.lltypesystem import rstr, rffi, lltype, llmemory

NO_FORCE_INDEX = -1


class GuardToken(object):
    def __init__(self, descr, failargs, faillocs, offset, save_exc, fcond=c.AL,
                 is_guard_not_invalidated=False, is_guard_not_forced=False):
        assert isinstance(save_exc, bool)
        self.descr = descr
        self.offset = offset
        self.is_guard_not_invalidated = is_guard_not_invalidated
        self.is_guard_not_forced = is_guard_not_forced
        self.failargs = failargs
        self.faillocs = faillocs
        self.save_exc = save_exc
        self.fcond = fcond


class ResOpAssembler(object):

    def emit_op_int_add(self, op, arglocs, regalloc, fcond):
        return self.int_add_impl(op, arglocs, regalloc, fcond)

    def int_add_impl(self, op, arglocs, regalloc, fcond, flags=False):
        l0, l1, res = arglocs
        if flags:
            s = 1
        else:
            s = 0
        if l0.is_imm():
            self.mc.ADD_ri(res.value, l1.value, imm=l0.value, s=s)
        elif l1.is_imm():
            self.mc.ADD_ri(res.value, l0.value, imm=l1.value, s=s)
        else:
            self.mc.ADD_rr(res.value, l0.value, l1.value, s=1)

        return fcond

    def emit_op_int_sub(self, op, arglocs, regalloc, fcond, flags=False):
        return self.int_sub_impl(op, arglocs, regalloc, fcond)

    def int_sub_impl(self, op, arglocs, regalloc, fcond, flags=False):
        l0, l1, res = arglocs
        if flags:
            s = 1
        else:
            s = 0
        if l0.is_imm():
            value = l0.getint()
            assert value >= 0
            # reverse substract ftw
            self.mc.RSB_ri(res.value, l1.value, value, s=s)
        elif l1.is_imm():
            value = l1.getint()
            assert value >= 0
            self.mc.SUB_ri(res.value, l0.value, value, s=s)
        else:
            self.mc.SUB_rr(res.value, l0.value, l1.value, s=s)

        return fcond

    def emit_op_int_mul(self, op, arglocs, regalloc, fcond):
        reg1, reg2, res = arglocs
        self.mc.MUL(res.value, reg1.value, reg2.value)
        return fcond

    def emit_op_int_force_ge_zero(self, op, arglocs, regalloc, fcond):
        arg, res = arglocs
        self.mc.CMP_ri(arg.value, 0)
        self.mc.MOV_ri(res.value, 0, cond=c.LT)
        self.mc.MOV_rr(res.value, arg.value, cond=c.GE)
        return fcond

    #ref: http://blogs.arm.com/software-enablement/detecting-overflow-from-mul/
    def emit_guard_int_mul_ovf(self, op, guard, arglocs, regalloc, fcond):
        reg1 = arglocs[0]
        reg2 = arglocs[1]
        res = arglocs[2]
        failargs = arglocs[3:]
        self.mc.SMULL(res.value, r.ip.value, reg1.value, reg2.value,
                                                                cond=fcond)
        self.mc.CMP_rr(r.ip.value, res.value, shifttype=shift.ASR,
                                                        imm=31, cond=fcond)

        if guard.getopnum() == rop.GUARD_OVERFLOW:
            fcond = self._emit_guard(guard, failargs, c.NE, save_exc=False)
        elif guard.getopnum() == rop.GUARD_NO_OVERFLOW:
            fcond = self._emit_guard(guard, failargs, c.EQ, save_exc=False)
        else:
            assert 0
        return fcond

    def emit_guard_int_add_ovf(self, op, guard, arglocs, regalloc, fcond):
        self.int_add_impl(op, arglocs[0:3], regalloc, fcond, flags=True)
        self._emit_guard_overflow(guard, arglocs[3:], fcond)
        return fcond

    def emit_guard_int_sub_ovf(self, op, guard, arglocs, regalloc, fcond):
        self.int_sub_impl(op, arglocs[0:3], regalloc, fcond, flags=True)
        self._emit_guard_overflow(guard, arglocs[3:], fcond)
        return fcond

    emit_op_int_floordiv = gen_emit_op_by_helper_call('int_floordiv', 'DIV')
    emit_op_int_mod = gen_emit_op_by_helper_call('int_mod', 'MOD')
    emit_op_uint_floordiv = gen_emit_op_by_helper_call('uint_floordiv', 'UDIV')

    emit_op_int_and = gen_emit_op_ri('int_and', 'AND')
    emit_op_int_or = gen_emit_op_ri('int_or', 'ORR')
    emit_op_int_xor = gen_emit_op_ri('int_xor', 'EOR')
    emit_op_int_lshift = gen_emit_op_ri('int_lshift', 'LSL')
    emit_op_int_rshift = gen_emit_op_ri('int_rshift', 'ASR')
    emit_op_uint_rshift = gen_emit_op_ri('uint_rshift', 'LSR')

    emit_op_int_lt = gen_emit_cmp_op('int_lt', c.LT)
    emit_op_int_le = gen_emit_cmp_op('int_le', c.LE)
    emit_op_int_eq = gen_emit_cmp_op('int_eq', c.EQ)
    emit_op_int_ne = gen_emit_cmp_op('int_ne', c.NE)
    emit_op_int_gt = gen_emit_cmp_op('int_gt', c.GT)
    emit_op_int_ge = gen_emit_cmp_op('int_ge', c.GE)

    emit_guard_int_lt = gen_emit_cmp_op_guard('int_lt', c.LT)
    emit_guard_int_le = gen_emit_cmp_op_guard('int_le', c.LE)
    emit_guard_int_eq = gen_emit_cmp_op_guard('int_eq', c.EQ)
    emit_guard_int_ne = gen_emit_cmp_op_guard('int_ne', c.NE)
    emit_guard_int_gt = gen_emit_cmp_op_guard('int_gt', c.GT)
    emit_guard_int_ge = gen_emit_cmp_op_guard('int_ge', c.GE)

    emit_op_uint_le = gen_emit_cmp_op('uint_le', c.LS)
    emit_op_uint_gt = gen_emit_cmp_op('uint_gt', c.HI)
    emit_op_uint_lt = gen_emit_cmp_op('uint_lt', c.LO)
    emit_op_uint_ge = gen_emit_cmp_op('uint_ge', c.HS)

    emit_guard_uint_le = gen_emit_cmp_op_guard('uint_le', c.LS)
    emit_guard_uint_gt = gen_emit_cmp_op_guard('uint_gt', c.HI)
    emit_guard_uint_lt = gen_emit_cmp_op_guard('uint_lt', c.LO)
    emit_guard_uint_ge = gen_emit_cmp_op_guard('uint_ge', c.HS)

    emit_op_ptr_eq = emit_op_instance_ptr_eq = emit_op_int_eq
    emit_op_ptr_ne = emit_op_instance_ptr_ne = emit_op_int_ne
    emit_guard_ptr_eq = emit_guard_instance_ptr_eq = emit_guard_int_eq
    emit_guard_ptr_ne = emit_guard_instance_ptr_ne = emit_guard_int_ne

    emit_op_int_add_ovf = emit_op_int_add
    emit_op_int_sub_ovf = emit_op_int_sub

    emit_op_int_is_true = gen_emit_op_unary_cmp('int_is_true', c.NE)
    emit_op_int_is_zero = gen_emit_op_unary_cmp('int_is_zero', c.EQ)

    emit_guard_int_is_true = gen_emit_guard_unary_cmp('int_is_true', c.NE)
    emit_guard_int_is_zero = gen_emit_guard_unary_cmp('int_is_zero', c.EQ)

    def emit_op_int_invert(self, op, arglocs, regalloc, fcond):
        reg, res = arglocs

        self.mc.MVN_rr(res.value, reg.value)
        return fcond

    def emit_op_int_neg(self, op, arglocs, regalloc, fcond):
        l0, resloc = arglocs
        self.mc.RSB_ri(resloc.value, l0.value, imm=0)
        return fcond

    def _emit_guard(self, op, arglocs, fcond, save_exc,
                                    is_guard_not_invalidated=False, 
                                    is_guard_not_forced=False):
        assert isinstance(save_exc, bool)
        assert isinstance(fcond, int)
        descr = op.getdescr()
        assert isinstance(descr, AbstractFailDescr)

        pos = self.mc.currpos()
        # For all guards that are not GUARD_NOT_INVALIDATED we emit a
        # breakpoint to ensure the location is patched correctly. In the case
        # of GUARD_NOT_INVALIDATED we use just a NOP, because it is only
        # eventually patched at a later point.
        if is_guard_not_invalidated:
            self.mc.NOP()
        else:
            self.mc.BKPT()
        self.pending_guards.append(GuardToken(descr,
                                    failargs=op.getfailargs(),
                                    faillocs=arglocs,
                                    offset=pos,
                                    save_exc=save_exc,
                                    is_guard_not_invalidated=is_guard_not_invalidated,
                                    is_guard_not_forced=is_guard_not_forced,
                                    fcond=fcond))
        return c.AL

    def _emit_guard_overflow(self, guard, failargs, fcond):
        if guard.getopnum() == rop.GUARD_OVERFLOW:
            fcond = self._emit_guard(guard, failargs, c.VS, save_exc=False)
        elif guard.getopnum() == rop.GUARD_NO_OVERFLOW:
            fcond = self._emit_guard(guard, failargs, c.VC, save_exc=False)
        else:
            assert 0
        return fcond

    def emit_op_guard_true(self, op, arglocs, regalloc, fcond):
        l0 = arglocs[0]
        failargs = arglocs[1:]
        self.mc.CMP_ri(l0.value, 0)
        fcond = self._emit_guard(op, failargs, c.NE, save_exc=False)
        return fcond

    def emit_op_guard_false(self, op, arglocs, regalloc, fcond):
        l0 = arglocs[0]
        failargs = arglocs[1:]
        self.mc.CMP_ri(l0.value, 0)
        fcond = self._emit_guard(op, failargs, c.EQ, save_exc=False)
        return fcond

    def emit_op_guard_value(self, op, arglocs, regalloc, fcond):
        l0 = arglocs[0]
        l1 = arglocs[1]
        failargs = arglocs[2:]

        if l0.is_reg():
            if l1.is_imm():
                self.mc.CMP_ri(l0.value, l1.getint())
            else:
                self.mc.CMP_rr(l0.value, l1.value)
        elif l0.is_vfp_reg():
            assert l1.is_vfp_reg()
            self.mc.VCMP(l0.value, l1.value)
            self.mc.VMRS(cond=fcond)
        fcond = self._emit_guard(op, failargs, c.EQ, save_exc=False)
        return fcond

    emit_op_guard_nonnull = emit_op_guard_true
    emit_op_guard_isnull = emit_op_guard_false

    def emit_op_guard_no_overflow(self, op, arglocs, regalloc, fcond):
        return self._emit_guard(op, arglocs, c.VC, save_exc=False)

    def emit_op_guard_overflow(self, op, arglocs, regalloc, fcond):
        return self._emit_guard(op, arglocs, c.VS, save_exc=False)

    def emit_op_guard_class(self, op, arglocs, regalloc, fcond):
        self._cmp_guard_class(op, arglocs, regalloc, fcond)
        self._emit_guard(op, arglocs[3:], c.EQ, save_exc=False)
        return fcond

    def emit_op_guard_nonnull_class(self, op, arglocs, regalloc, fcond):
        self.mc.CMP_ri(arglocs[0].value, 1)
        self._cmp_guard_class(op, arglocs, regalloc, c.HS)
        self._emit_guard(op, arglocs[3:], c.EQ, save_exc=False)
        return fcond

    def _cmp_guard_class(self, op, locs, regalloc, fcond):
        offset = locs[2]
        if offset is not None:
            self.mc.LDR_ri(r.ip.value, locs[0].value, offset.value, cond=fcond)
            self.mc.CMP_rr(r.ip.value, locs[1].value, cond=fcond)
        else:
            typeid = locs[1]
            self.mc.LDRH_ri(r.ip.value, locs[0].value, cond=fcond)
            if typeid.is_imm():
                self.mc.CMP_ri(r.ip.value, typeid.value, cond=fcond)
            else:
                self.mc.CMP_rr(r.ip.value, typeid.value, cond=fcond)

    def emit_op_guard_not_invalidated(self, op, locs, regalloc, fcond):
        return self._emit_guard(op, locs, fcond, save_exc=False,
                                            is_guard_not_invalidated=True)

    def emit_op_jump(self, op, arglocs, regalloc, fcond):
        # The backend's logic assumes that the target code is in a piece of
        # assembler that was also called with the same number of arguments,
        # so that the locations [ebp+8..] of the input arguments are valid
        # stack locations both before and after the jump.
        #
        descr = op.getdescr()
        assert isinstance(descr, TargetToken)
        assert fcond == c.AL
        my_nbargs = self.current_clt._debug_nbargs
        target_nbargs = descr._arm_clt._debug_nbargs
        assert my_nbargs == target_nbargs

        self._insert_checks()
        if descr in self.target_tokens_currently_compiling:
            self.mc.B_offs(descr._arm_loop_code, fcond)
        else:
            self.mc.B(descr._arm_loop_code, fcond)
        return fcond

    def emit_op_finish(self, op, arglocs, regalloc, fcond):
        [argloc] = arglocs
        if argloc is not r.r0: #XXX verify this
            self.mov_loc_loc(argloc, r.r0, fcond)
        # exit function
        self.gen_func_epilog()
        return fcond

    def emit_op_call(self, op, arglocs, regalloc, fcond,
                                        force_index=NO_FORCE_INDEX):
        if force_index == NO_FORCE_INDEX:
            force_index = self.write_new_force_index()
        resloc = arglocs[0]
        adr = arglocs[1]
        arglist = arglocs[2:]
        descr = op.getdescr()
        size = descr.get_result_size()
        signed = descr.is_result_signed()
        cond = self._emit_call(force_index, adr, arglist,
                                            fcond, resloc, (size, signed))
        return cond

    def _emit_call(self, force_index, adr, arglocs, fcond=c.AL,
                                         resloc=None, result_info=(-1, -1)):
        if self.cpu.use_hf_abi:
            stack_args, adr = self._setup_call_hf(force_index, adr,
                                        arglocs, fcond, resloc, result_info)
        else:
            stack_args, adr = self._setup_call_sf(force_index, adr,
                                        arglocs, fcond, resloc, result_info)

        #the actual call
        #self.mc.BKPT()
        if adr.is_imm():
            self.mc.BL(adr.value)
        elif adr.is_stack():
            self.mov_loc_loc(adr, r.ip)
            adr = r.ip
        else:
            assert adr.is_reg()
        if adr.is_reg():
            self.mc.BLX(adr.value)
        self.mark_gc_roots(force_index)
        self._restore_sp(stack_args, fcond)

        # ensure the result is wellformed and stored in the correct location
        if resloc is not None:
            if resloc.is_vfp_reg() and not self.cpu.use_hf_abi:
                # move result to the allocated register
                self.mov_to_vfp_loc(r.r0, r.r1, resloc)
            elif resloc.is_reg() and result_info != (-1, -1):
                self._ensure_result_bit_extension(resloc, result_info[0],
                                                          result_info[1])
        return fcond

    def _restore_sp(self, stack_args, fcond):
        # readjust the sp in case we passed some args on the stack
        if len(stack_args) > 0:
            n = 0
            for arg in stack_args:
                if arg is None or arg.type != FLOAT:
                    n += WORD
                else:
                    n += DOUBLE_WORD
            self._adjust_sp(-n, fcond=fcond)
            assert n % 8 == 0  # sanity check

    def _collect_stack_args_sf(self, arglocs):
        n_args = len(arglocs)
        reg_args = count_reg_args(arglocs)
        # all arguments past the 4th go on the stack
        # first we need to prepare the list so it stays aligned
        stack_args = []
        count = 0
        if n_args > reg_args:
            for i in range(reg_args, n_args):
                arg = arglocs[i]
                if arg.type != FLOAT:
                    count += 1
                else:
                    if count % 2 != 0:
                        stack_args.append(None)
                        count = 0
                stack_args.append(arg)
            if count % 2 != 0:
                stack_args.append(None)
        return stack_args

    def _push_stack_args(self, stack_args):
            #then we push every thing on the stack
            for i in range(len(stack_args) - 1, -1, -1):
                arg = stack_args[i]
                if arg is None:
                    self.mc.PUSH([r.ip.value])
                else:
                    self.regalloc_push(arg)

    def _setup_call_sf(self, force_index, adr, arglocs, fcond=c.AL,
                                         resloc=None, result_info=(-1, -1)):
        reg_args = count_reg_args(arglocs)
        stack_args = self._collect_stack_args_sf(arglocs)
        self._push_stack_args(stack_args)
        # collect variables that need to go in registers and the registers they
        # will be stored in
        num = 0
        count = 0
        non_float_locs = []
        non_float_regs = []
        float_locs = []
        for i in range(reg_args):
            arg = arglocs[i]
            if arg.type == FLOAT and count % 2 != 0:
                    num += 1
                    count = 0
            reg = r.caller_resp[num]

            if arg.type == FLOAT:
                float_locs.append((arg, reg))
            else:
                non_float_locs.append(arg)
                non_float_regs.append(reg)

            if arg.type == FLOAT:
                num += 2
            else:
                num += 1
                count += 1
        # Check that the address of the function we want to call is not
        # currently stored in one of the registers used to pass the arguments.
        # If this happens to be the case we remap the register to r4 and use r4
        # to call the function
        if adr in non_float_regs:
            non_float_locs.append(adr)
            non_float_regs.append(r.r4)
            adr = r.r4
        # remap values stored in core registers
        remap_frame_layout(self, non_float_locs, non_float_regs, r.ip)

        for loc, reg in float_locs:
            self.mov_from_vfp_loc(loc, reg, r.all_regs[reg.value + 1])
        return stack_args, adr

    def _setup_call_hf(self, force_index, adr, arglocs, fcond=c.AL,
                                         resloc=None, result_info=(-1, -1)):
        non_float_locs = []
        non_float_regs = []
        float_locs = []
        float_regs = []
        stack_args = []
        count = 0                      # stack alignment counter
        for arg in arglocs:
            if arg.type != FLOAT:
                if len(non_float_regs) < len(r.argument_regs):
                    reg = r.argument_regs[len(non_float_regs)]
                    non_float_locs.append(arg)
                    non_float_regs.append(reg)
                else:  # non-float argument that needs to go on the stack
                    count += 1
                    stack_args.append(arg)
            else:
                if len(float_regs) < len(r.vfp_argument_regs):
                    reg = r.vfp_argument_regs[len(float_regs)]
                    float_locs.append(arg)
                    float_regs.append(reg)
                else:  # float argument that needs to go on the stack
                    if count % 2 != 0:
                        stack_args.append(None)
                        count = 0
                    stack_args.append(arg)
        # align the stack
        if count % 2 != 0:
            stack_args.append(None)
        self._push_stack_args(stack_args)
        # Check that the address of the function we want to call is not
        # currently stored in one of the registers used to pass the arguments.
        # If this happens to be the case we remap the register to r4 and use r4
        # to call the function
        if adr in non_float_regs:
            non_float_locs.append(adr)
            non_float_regs.append(r.r4)
            adr = r.r4
        # remap values stored in core registers
        remap_frame_layout(self, non_float_locs, non_float_regs, r.ip)
        # remap values stored in vfp registers
        remap_frame_layout(self, float_locs, float_regs, r.vfp_ip)

        return stack_args, adr

    def emit_op_same_as(self, op, arglocs, regalloc, fcond):
        argloc, resloc = arglocs
        self.mov_loc_loc(argloc, resloc)
        return fcond

    emit_op_cast_ptr_to_int = emit_op_same_as
    emit_op_cast_int_to_ptr = emit_op_same_as

    def emit_op_guard_no_exception(self, op, arglocs, regalloc, fcond):
        loc = arglocs[0]
        failargs = arglocs[1:]
        self.mc.LDR_ri(loc.value, loc.value)
        self.mc.CMP_ri(loc.value, 0)
        cond = self._emit_guard(op, failargs, c.EQ, save_exc=True)
        return cond

    def emit_op_guard_exception(self, op, arglocs, regalloc, fcond):
        loc, loc1, resloc, pos_exc_value, pos_exception = arglocs[:5]
        failargs = arglocs[5:]
        self.mc.gen_load_int(loc1.value, pos_exception.value)
        self.mc.LDR_ri(r.ip.value, loc1.value)

        self.mc.CMP_rr(r.ip.value, loc.value)
        self._emit_guard(op, failargs, c.EQ, save_exc=True)
        self.mc.gen_load_int(loc.value, pos_exc_value.value)
        if resloc:
            self.mc.LDR_ri(resloc.value, loc.value)
        self.mc.MOV_ri(r.ip.value, 0)
        self.mc.STR_ri(r.ip.value, loc.value)
        self.mc.STR_ri(r.ip.value, loc1.value)
        return fcond

    def emit_op_debug_merge_point(self, op, arglocs, regalloc, fcond):
        return fcond
    emit_op_jit_debug = emit_op_debug_merge_point
    emit_op_keepalive = emit_op_debug_merge_point

    def emit_op_cond_call_gc_wb(self, op, arglocs, regalloc, fcond):
        # Write code equivalent to write_barrier() in the GC: it checks
        # a flag in the object at arglocs[0], and if set, it calls a
        # helper piece of assembler.  The latter saves registers as needed
        # and call the function jit_remember_young_pointer() from the GC.
        descr = op.getdescr()
        if we_are_translated():
            cls = self.cpu.gc_ll_descr.has_write_barrier_class()
            assert cls is not None and isinstance(descr, cls)
        #
        opnum = op.getopnum()
        card_marking = False
        mask = descr.jit_wb_if_flag_singlebyte
        if opnum == rop.COND_CALL_GC_WB_ARRAY and descr.jit_wb_cards_set != 0:
            # assumptions the rest of the function depends on:
            assert (descr.jit_wb_cards_set_byteofs ==
                    descr.jit_wb_if_flag_byteofs)
            assert descr.jit_wb_cards_set_singlebyte == -0x80
            card_marking = True
            mask = descr.jit_wb_if_flag_singlebyte | -0x80
        #
        loc_base = arglocs[0]
        self.mc.LDRB_ri(r.ip.value, loc_base.value,
                                    imm=descr.jit_wb_if_flag_byteofs)
        mask &= 0xFF
        self.mc.TST_ri(r.ip.value, imm=mask)

        jz_location = self.mc.currpos()
        self.mc.BKPT()

        # for cond_call_gc_wb_array, also add another fast path:
        # if GCFLAG_CARDS_SET, then we can just set one bit and be done
        if card_marking:
            # GCFLAG_CARDS_SET is in this byte at 0x80
            self.mc.TST_ri(r.ip.value, imm=0x80)

            js_location = self.mc.currpos()
            self.mc.BKPT()
        else:
            js_location = 0

        # Write only a CALL to the helper prepared in advance, passing it as
        # argument the address of the structure we are writing into
        # (the first argument to COND_CALL_GC_WB).
        helper_num = card_marking
        if self._regalloc.vfprm.reg_bindings:
            helper_num += 2
        if self.wb_slowpath[helper_num] == 0:    # tests only
            assert not we_are_translated()
            self.cpu.gc_ll_descr.write_barrier_descr = descr
            self._build_wb_slowpath(card_marking,
                                    bool(self._regalloc.vfprm.reg_bindings))
            assert self.wb_slowpath[helper_num] != 0
        #
        if loc_base is not r.r0:
            # push two registers to keep stack aligned
            self.mc.PUSH([r.r0.value, loc_base.value])
            remap_frame_layout(self, [loc_base], [r.r0], r.ip)
        self.mc.BL(self.wb_slowpath[helper_num])
        if loc_base is not r.r0:
            self.mc.POP([r.r0.value, loc_base.value])

        if card_marking:
            # The helper ends again with a check of the flag in the object.  So
            # here, we can simply write again a conditional jump, which will be
            # taken if GCFLAG_CARDS_SET is still not set.
            jns_location = self.mc.currpos()
            self.mc.BKPT()
            #
            # patch the JS above
            offset = self.mc.currpos()
            pmc = OverwritingBuilder(self.mc, js_location, WORD)
            pmc.B_offs(offset, c.NE)  # We want to jump if the z flag isn't set
            #
            # case GCFLAG_CARDS_SET: emit a few instructions to do
            # directly the card flag setting
            loc_index = arglocs[1]
            assert loc_index.is_reg()
            # must save the register loc_index before it is mutated
            self.mc.PUSH([loc_index.value])
            tmp1 = loc_index
            tmp2 = arglocs[-1]  # the last item is a preallocated tmp
            # lr = byteofs
            s = 3 + descr.jit_wb_card_page_shift
            self.mc.MVN_rr(r.lr.value, loc_index.value,
                                       imm=s, shifttype=shift.LSR)

            # tmp1 = byte_index
            self.mc.MOV_ri(r.ip.value, imm=7)
            self.mc.AND_rr(tmp1.value, r.ip.value, loc_index.value,
            imm=descr.jit_wb_card_page_shift, shifttype=shift.LSR)

            # set the bit
            self.mc.MOV_ri(tmp2.value, imm=1)
            self.mc.LDRB_rr(r.ip.value, loc_base.value, r.lr.value)
            self.mc.ORR_rr_sr(r.ip.value, r.ip.value, tmp2.value,
                                          tmp1.value, shifttype=shift.LSL)
            self.mc.STRB_rr(r.ip.value, loc_base.value, r.lr.value)
            # done
            self.mc.POP([loc_index.value])
            #
            #
            # patch the JNS above
            offset = self.mc.currpos()
            pmc = OverwritingBuilder(self.mc, jns_location, WORD)
            pmc.B_offs(offset, c.EQ)  # We want to jump if the z flag is set

        offset = self.mc.currpos()
        pmc = OverwritingBuilder(self.mc, jz_location, WORD)
        pmc.B_offs(offset, c.EQ)
        return fcond

    emit_op_cond_call_gc_wb_array = emit_op_cond_call_gc_wb

    def emit_op_setfield_gc(self, op, arglocs, regalloc, fcond):
        value_loc, base_loc, ofs, size = arglocs
        if size.value == 8:
            assert value_loc.is_vfp_reg()
            # vstr only supports imm offsets
            # so if the ofset is too large we add it to the base and use an
            # offset of 0
            if ofs.is_reg():
                self.mc.ADD_rr(r.ip.value, base_loc.value, ofs.value)
                base_loc = r.ip
                ofs = imm(0)
            else:
                assert ofs.value % 4 == 0
            self.mc.VSTR(value_loc.value, base_loc.value, ofs.value)
        elif size.value == 4:
            if ofs.is_imm():
                self.mc.STR_ri(value_loc.value, base_loc.value, ofs.value)
            else:
                self.mc.STR_rr(value_loc.value, base_loc.value, ofs.value)
        elif size.value == 2:
            if ofs.is_imm():
                self.mc.STRH_ri(value_loc.value, base_loc.value, ofs.value)
            else:
                self.mc.STRH_rr(value_loc.value, base_loc.value, ofs.value)
        elif size.value == 1:
            if ofs.is_imm():
                self.mc.STRB_ri(value_loc.value, base_loc.value, ofs.value)
            else:
                self.mc.STRB_rr(value_loc.value, base_loc.value, ofs.value)
        else:
            assert 0
        return fcond

    emit_op_setfield_raw = emit_op_setfield_gc

    def emit_op_getfield_gc(self, op, arglocs, regalloc, fcond):
        base_loc, ofs, res, size = arglocs
        signed = op.getdescr().is_field_signed()
        if size.value == 8:
            assert res.is_vfp_reg()
            # vldr only supports imm offsets
            # so if the ofset is too large we add it to the base and use an
            # offset of 0
            if ofs.is_reg():
                self.mc.ADD_rr(r.ip.value, base_loc.value, ofs.value)
                base_loc = r.ip
                ofs = imm(0)
            else:
                assert ofs.value % 4 == 0
            self.mc.VLDR(res.value, base_loc.value, ofs.value)
        elif size.value == 4:
            if ofs.is_imm():
                self.mc.LDR_ri(res.value, base_loc.value, ofs.value)
            else:
                self.mc.LDR_rr(res.value, base_loc.value, ofs.value)
        elif size.value == 2:
            if ofs.is_imm():
                if signed:
                    self.mc.LDRSH_ri(res.value, base_loc.value, ofs.value)
                else:
                    self.mc.LDRH_ri(res.value, base_loc.value, ofs.value)
            else:
                if signed:
                    self.mc.LDRSH_rr(res.value, base_loc.value, ofs.value)
                else:
                    self.mc.LDRH_rr(res.value, base_loc.value, ofs.value)
        elif size.value == 1:
            if ofs.is_imm():
                if signed:
                    self.mc.LDRSB_ri(res.value, base_loc.value, ofs.value)
                else:
                    self.mc.LDRB_ri(res.value, base_loc.value, ofs.value)
            else:
                if signed:
                    self.mc.LDRSB_rr(res.value, base_loc.value, ofs.value)
                else:
                    self.mc.LDRB_rr(res.value, base_loc.value, ofs.value)
        else:
            assert 0
        return fcond

    emit_op_getfield_raw = emit_op_getfield_gc
    emit_op_getfield_raw_pure = emit_op_getfield_gc
    emit_op_getfield_gc_pure = emit_op_getfield_gc

    def emit_op_getinteriorfield_gc(self, op, arglocs, regalloc, fcond):
        (base_loc, index_loc, res_loc,
            ofs_loc, ofs, itemsize, fieldsize) = arglocs
        self.mc.gen_load_int(r.ip.value, itemsize.value)
        self.mc.MUL(r.ip.value, index_loc.value, r.ip.value)
        descr = op.getdescr()
        assert isinstance(descr, InteriorFieldDescr)
        signed = descr.fielddescr.is_field_signed()
        if ofs.value > 0:
            if ofs_loc.is_imm():
                self.mc.ADD_ri(r.ip.value, r.ip.value, ofs_loc.value)
            else:
                self.mc.ADD_rr(r.ip.value, r.ip.value, ofs_loc.value)

        if fieldsize.value == 8:
            # vldr only supports imm offsets
            # so if the ofset is too large we add it to the base and use an
            # offset of 0
            assert res_loc.is_vfp_reg()
            self.mc.ADD_rr(r.ip.value, base_loc.value, r.ip.value)
            self.mc.VLDR(res_loc.value, r.ip.value, 0)
        elif fieldsize.value == 4:
            self.mc.LDR_rr(res_loc.value, base_loc.value, r.ip.value)
        elif fieldsize.value == 2:
            if signed:
                self.mc.LDRSH_rr(res_loc.value, base_loc.value, r.ip.value)
            else:
                self.mc.LDRH_rr(res_loc.value, base_loc.value, r.ip.value)
        elif fieldsize.value == 1:
            if signed:
                self.mc.LDRSB_rr(res_loc.value, base_loc.value, r.ip.value)
            else:
                self.mc.LDRB_rr(res_loc.value, base_loc.value, r.ip.value)
        else:
            assert 0

        return fcond

    def emit_op_setinteriorfield_gc(self, op, arglocs, regalloc, fcond):
        (base_loc, index_loc, value_loc,
            ofs_loc, ofs, itemsize, fieldsize) = arglocs
        self.mc.gen_load_int(r.ip.value, itemsize.value)
        self.mc.MUL(r.ip.value, index_loc.value, r.ip.value)
        if ofs.value > 0:
            if ofs_loc.is_imm():
                self.mc.ADD_ri(r.ip.value, r.ip.value, ofs_loc.value)
            else:
                self.mc.ADD_rr(r.ip.value, r.ip.value, ofs_loc.value)
        if fieldsize.value == 8:
            # vstr only supports imm offsets
            # so if the ofset is too large we add it to the base and use an
            # offset of 0
            assert value_loc.is_vfp_reg()
            self.mc.ADD_rr(r.ip.value, base_loc.value, r.ip.value)
            self.mc.VSTR(value_loc.value, r.ip.value, 0)
        elif fieldsize.value == 4:
            self.mc.STR_rr(value_loc.value, base_loc.value, r.ip.value)
        elif fieldsize.value == 2:
            self.mc.STRH_rr(value_loc.value, base_loc.value, r.ip.value)
        elif fieldsize.value == 1:
            self.mc.STRB_rr(value_loc.value, base_loc.value, r.ip.value)
        else:
            assert 0
        return fcond
    emit_op_setinteriorfield_raw = emit_op_setinteriorfield_gc

    def emit_op_arraylen_gc(self, op, arglocs, regalloc, fcond):
        res, base_loc, ofs = arglocs
        self.mc.LDR_ri(res.value, base_loc.value, ofs.value)
        return fcond

    def emit_op_setarrayitem_gc(self, op, arglocs, regalloc, fcond):
        value_loc, base_loc, ofs_loc, scale, ofs = arglocs
        assert ofs_loc.is_reg()
        if scale.value > 0:
            self.mc.LSL_ri(r.ip.value, ofs_loc.value, scale.value)
            ofs_loc = r.ip

        # add the base offset
        if ofs.value > 0:
            self.mc.ADD_ri(r.ip.value, ofs_loc.value, imm=ofs.value)
            ofs_loc = r.ip
        self._write_to_mem(value_loc, base_loc, ofs_loc, scale, fcond)
        return fcond

    def _write_to_mem(self, value_loc, base_loc, ofs_loc, scale, fcond=c.AL):
        if scale.value == 3:
            assert value_loc.is_vfp_reg()
            assert ofs_loc.is_reg()
            self.mc.ADD_rr(r.ip.value, base_loc.value, ofs_loc.value)
            self.mc.VSTR(value_loc.value, r.ip.value, cond=fcond)
        elif scale.value == 2:
            self.mc.STR_rr(value_loc.value, base_loc.value, ofs_loc.value,
                                                                    cond=fcond)
        elif scale.value == 1:
            self.mc.STRH_rr(value_loc.value, base_loc.value, ofs_loc.value,
                                                                    cond=fcond)
        elif scale.value == 0:
            self.mc.STRB_rr(value_loc.value, base_loc.value, ofs_loc.value,
                                                                    cond=fcond)
        else:
            assert 0

    emit_op_setarrayitem_raw = emit_op_setarrayitem_gc

    def emit_op_raw_store(self, op, arglocs, regalloc, fcond):
        value_loc, base_loc, ofs_loc, scale, ofs = arglocs
        assert ofs_loc.is_reg()
        self._write_to_mem(value_loc, base_loc, ofs_loc, scale, fcond)
        return fcond

    def emit_op_getarrayitem_gc(self, op, arglocs, regalloc, fcond):
        res_loc, base_loc, ofs_loc, scale, ofs = arglocs
        assert ofs_loc.is_reg()
        signed = op.getdescr().is_item_signed()

        # scale the offset as required
        if scale.value > 0:
            self.mc.LSL_ri(r.ip.value, ofs_loc.value, scale.value)
            ofs_loc = r.ip
        # add the base offset
        if ofs.value > 0:
            self.mc.ADD_ri(r.ip.value, ofs_loc.value, imm=ofs.value)
            ofs_loc = r.ip
        #
        self._load_from_mem(res_loc, base_loc, ofs_loc, scale, signed)
        return fcond

    def _load_from_mem(self, res_loc, base_loc, ofs_loc, scale,
                                            signed=False, fcond=c.AL):
        if scale.value == 3:
            assert res_loc.is_vfp_reg()
            assert ofs_loc.is_reg()
            self.mc.ADD_rr(r.ip.value, base_loc.value, ofs_loc.value)
            self.mc.VLDR(res_loc.value, r.ip.value, cond=fcond)
        elif scale.value == 2:
            self.mc.LDR_rr(res_loc.value, base_loc.value,
                                 ofs_loc.value, cond=fcond)
        elif scale.value == 1:
            if signed:
                self.mc.LDRSH_rr(res_loc.value, base_loc.value,
                                 ofs_loc.value, cond=fcond)
            else:
                self.mc.LDRH_rr(res_loc.value, base_loc.value,
                                 ofs_loc.value, cond=fcond)
        elif scale.value == 0:
            if signed:
                self.mc.LDRSB_rr(res_loc.value, base_loc.value,
                                 ofs_loc.value, cond=fcond)
            else:
                self.mc.LDRB_rr(res_loc.value, base_loc.value,
                                 ofs_loc.value, cond=fcond)
        else:
            assert 0

    emit_op_getarrayitem_raw = emit_op_getarrayitem_gc
    emit_op_getarrayitem_gc_pure = emit_op_getarrayitem_gc

    def emit_op_raw_load(self, op, arglocs, regalloc, fcond):
        res_loc, base_loc, ofs_loc, scale, ofs = arglocs
        assert ofs_loc.is_reg()
        # no base offset
        assert ofs.value == 0
        signed = op.getdescr().is_item_signed()
        self._load_from_mem(res_loc, base_loc, ofs_loc, scale, signed)
        return fcond

    def emit_op_strlen(self, op, arglocs, regalloc, fcond):
        l0, l1, res = arglocs
        if l1.is_imm():
            self.mc.LDR_ri(res.value, l0.value, l1.getint(), cond=fcond)
        else:
            self.mc.LDR_rr(res.value, l0.value, l1.value, cond=fcond)
        return fcond

    def emit_op_strgetitem(self, op, arglocs, regalloc, fcond):
        res, base_loc, ofs_loc, basesize = arglocs
        if ofs_loc.is_imm():
            self.mc.ADD_ri(r.ip.value, base_loc.value, ofs_loc.getint(),
                                                                    cond=fcond)
        else:
            self.mc.ADD_rr(r.ip.value, base_loc.value, ofs_loc.value,
                                                                    cond=fcond)

        self.mc.LDRB_ri(res.value, r.ip.value, basesize.value, cond=fcond)
        return fcond

    def emit_op_strsetitem(self, op, arglocs, regalloc, fcond):
        value_loc, base_loc, ofs_loc, basesize = arglocs
        if ofs_loc.is_imm():
            self.mc.ADD_ri(r.ip.value, base_loc.value, ofs_loc.getint(),
                                                            cond=fcond)
        else:
            self.mc.ADD_rr(r.ip.value, base_loc.value, ofs_loc.value,
                                                            cond=fcond)

        self.mc.STRB_ri(value_loc.value, r.ip.value, basesize.value,
                                                            cond=fcond)
        return fcond

    #from ../x86/regalloc.py:928 ff.
    def emit_op_copystrcontent(self, op, arglocs, regalloc, fcond):
        assert len(arglocs) == 0
        self._emit_copystrcontent(op, regalloc, fcond, is_unicode=False)
        return fcond

    def emit_op_copyunicodecontent(self, op, arglocs, regalloc, fcond):
        assert len(arglocs) == 0
        self._emit_copystrcontent(op, regalloc, fcond, is_unicode=True)
        return fcond

    def _emit_copystrcontent(self, op, regalloc, fcond, is_unicode):
        # compute the source address
        args = op.getarglist()
        base_loc = regalloc.make_sure_var_in_reg(args[0], args)
        ofs_loc = regalloc.make_sure_var_in_reg(args[2], args)
        assert args[0] is not args[1]    # forbidden case of aliasing
        regalloc.possibly_free_var(args[0])
        regalloc.free_temp_vars()
        if args[3] is not args[2] is not args[4]:  # MESS MESS MESS: don't free
            regalloc.possibly_free_var(args[2])  # it if ==args[3] or args[4]
            regalloc.free_temp_vars()
        srcaddr_box = TempPtr()
        forbidden_vars = [args[1], args[3], args[4], srcaddr_box]
        srcaddr_loc = regalloc.force_allocate_reg(srcaddr_box,
                                                        selected_reg=r.r1)
        self._gen_address_inside_string(base_loc, ofs_loc, srcaddr_loc,
                                        is_unicode=is_unicode)

        # compute the destination address
        forbidden_vars = [args[4], args[3], srcaddr_box]
        dstaddr_box = TempPtr()
        dstaddr_loc = regalloc.force_allocate_reg(dstaddr_box,
                                                        selected_reg=r.r0)
        forbidden_vars.append(dstaddr_box)
        base_loc = regalloc.make_sure_var_in_reg(args[1], forbidden_vars)
        ofs_loc = regalloc.make_sure_var_in_reg(args[3], forbidden_vars)
        assert base_loc.is_reg()
        assert ofs_loc.is_reg()
        regalloc.possibly_free_var(args[1])
        if args[3] is not args[4]:     # more of the MESS described above
            regalloc.possibly_free_var(args[3])
        regalloc.free_temp_vars()
        self._gen_address_inside_string(base_loc, ofs_loc, dstaddr_loc,
                                        is_unicode=is_unicode)

        # compute the length in bytes
        forbidden_vars = [srcaddr_box, dstaddr_box]
        # XXX basically duplicates regalloc.ensure_value_is_boxed, but we
        # need the box here
        if isinstance(args[4], Box):
            length_box = args[4]
            length_loc = regalloc.make_sure_var_in_reg(args[4],
                                                        forbidden_vars)
        else:
            length_box = TempInt()
            length_loc = regalloc.force_allocate_reg(length_box,
                                        forbidden_vars, selected_reg=r.r2)
            immloc = regalloc.convert_to_imm(args[4])
            self.load(length_loc, immloc)
        if is_unicode:
            bytes_box = TempPtr()
            bytes_loc = regalloc.force_allocate_reg(bytes_box,
                                        forbidden_vars, selected_reg=r.r2)
            scale = self._get_unicode_item_scale()
            assert length_loc.is_reg()
            self.mc.MOV_ri(r.ip.value, 1 << scale)
            self.mc.MUL(bytes_loc.value, r.ip.value, length_loc.value)
            length_box = bytes_box
            length_loc = bytes_loc
        # call memcpy()
        regalloc.before_call()
        self._emit_call(NO_FORCE_INDEX, imm(self.memcpy_addr),
                            [dstaddr_loc, srcaddr_loc, length_loc])

        regalloc.possibly_free_var(length_box)
        regalloc.possibly_free_var(dstaddr_box)
        regalloc.possibly_free_var(srcaddr_box)

    def _gen_address_inside_string(self, baseloc, ofsloc, resloc, is_unicode):
        if is_unicode:
            ofs_items, _, _ = symbolic.get_array_token(rstr.UNICODE,
                                              self.cpu.translate_support_code)
            scale = self._get_unicode_item_scale()
        else:
            ofs_items, itemsize, _ = symbolic.get_array_token(rstr.STR,
                                              self.cpu.translate_support_code)
            assert itemsize == 1
            scale = 0
        self._gen_address(ofsloc, ofs_items, scale, resloc, baseloc)

    def _gen_address(self, sizereg, baseofs, scale, result, baseloc=None):
        assert sizereg.is_reg()
        if scale > 0:
            scaled_loc = r.ip
            self.mc.LSL_ri(r.ip.value, sizereg.value, scale)
        else:
            scaled_loc = sizereg
        if baseloc is not None:
            assert baseloc.is_reg()
            self.mc.ADD_rr(result.value, baseloc.value, scaled_loc.value)
            self.mc.ADD_ri(result.value, result.value, baseofs)
        else:
            self.mc.ADD_ri(result.value, scaled_loc.value, baseofs)

    def _get_unicode_item_scale(self):
        _, itemsize, _ = symbolic.get_array_token(rstr.UNICODE,
                                              self.cpu.translate_support_code)
        if itemsize == 4:
            return 2
        elif itemsize == 2:
            return 1
        else:
            raise AssertionError("bad unicode item size")

    emit_op_unicodelen = emit_op_strlen

    def emit_op_unicodegetitem(self, op, arglocs, regalloc, fcond):
        res, base_loc, ofs_loc, scale, basesize, itemsize = arglocs
        self.mc.ADD_rr(r.ip.value, base_loc.value, ofs_loc.value, cond=fcond,
                                        imm=scale.value, shifttype=shift.LSL)
        if scale.value == 2:
            self.mc.LDR_ri(res.value, r.ip.value, basesize.value, cond=fcond)
        elif scale.value == 1:
            self.mc.LDRH_ri(res.value, r.ip.value, basesize.value, cond=fcond)
        else:
            assert 0, itemsize.value
        return fcond

    def emit_op_unicodesetitem(self, op, arglocs, regalloc, fcond):
        value_loc, base_loc, ofs_loc, scale, basesize, itemsize = arglocs
        self.mc.ADD_rr(r.ip.value, base_loc.value, ofs_loc.value, cond=fcond,
                                        imm=scale.value, shifttype=shift.LSL)
        if scale.value == 2:
            self.mc.STR_ri(value_loc.value, r.ip.value, basesize.value,
                                                                    cond=fcond)
        elif scale.value == 1:
            self.mc.STRH_ri(value_loc.value, r.ip.value, basesize.value,
                                                                    cond=fcond)
        else:
            assert 0, itemsize.value

        return fcond

    def emit_op_force_token(self, op, arglocs, regalloc, fcond):
        res_loc = arglocs[0]
        self.mc.MOV_rr(res_loc.value, r.fp.value)
        return fcond

    # from: ../x86/assembler.py:1668
    # XXX Split into some helper methods
    def emit_guard_call_assembler(self, op, guard_op, arglocs, regalloc,
                                                                    fcond):
        tmploc = arglocs[1]
        resloc = arglocs[2]
        callargs = arglocs[3:]

        faildescr = guard_op.getdescr()
        fail_index = self.cpu.get_fail_descr_number(faildescr)
        self._write_fail_index(fail_index)
        descr = op.getdescr()
        assert isinstance(descr, JitCellToken)
        # check value
        assert tmploc is r.r0
        self._emit_call(fail_index, imm(descr._arm_func_addr),
                                callargs, fcond, resloc=tmploc)
        if op.result is None:
            value = self.cpu.done_with_this_frame_void_v
        else:
            kind = op.result.type
            if kind == INT:
                value = self.cpu.done_with_this_frame_int_v
            elif kind == REF:
                value = self.cpu.done_with_this_frame_ref_v
            elif kind == FLOAT:
                value = self.cpu.done_with_this_frame_float_v
            else:
                raise AssertionError(kind)
        from rpython.jit.backend.llsupport.descr import unpack_fielddescr
        from rpython.jit.backend.llsupport.descr import unpack_interiorfielddescr
        descrs = self.cpu.gc_ll_descr.getframedescrs(self.cpu)
        _offset, _size, _ = unpack_fielddescr(descrs.jf_descr)
        fail_descr = self.cpu.get_fail_descr_from_number(value)
        value = fail_descr.hide(self.cpu)
        rgc._make_sure_does_not_move(value)
        value = rffi.cast(lltype.Signed, value)

        if check_imm_arg(_offset):
            self.mc.LDR_ri(r.ip.value, tmploc.value, imm=_offset)
        else:
            self.mc.gen_load_int(r.ip.value, _offset)
            self.mc.LDR_rr(r.ip.value, tmploc.value, r.ip.value)
        if check_imm_arg(value):
            self.mc.CMP_ri(r.ip.value, imm=value)
        else:
            self.mc.gen_load_int(r.lr.value, value)
            self.mc.CMP_rr(r.lr.value, r.ip.value)


        #if values are equal we take the fast path
        # Slow path, calling helper
        # jump to merge point

        jd = descr.outermost_jitdriver_sd
        assert jd is not None

        # Path A: load return value and reset token
        # Fast Path using result boxes

        fast_path_cond = c.EQ
        # Reset the vable token --- XXX really too much special logic here:-(
        if jd.index_of_virtualizable >= 0:
            from rpython.jit.backend.llsupport.descr import FieldDescr
            fielddescr = jd.vable_token_descr
            assert isinstance(fielddescr, FieldDescr)
            ofs = fielddescr.offset
            tmploc = regalloc.get_scratch_reg(INT)
            self.mov_loc_loc(arglocs[0], r.ip, cond=fast_path_cond)
            self.mc.MOV_ri(tmploc.value, 0, cond=fast_path_cond)
            self.mc.STR_ri(tmploc.value, r.ip.value, ofs, cond=fast_path_cond)

        if op.result is not None:
            # load the return value from fail_boxes_xxx[0]
            kind = op.result.type
            if kind == FLOAT:
                t = unpack_interiorfielddescr(descrs.as_float)[0]
                if not check_imm_arg(t):
                    self.mc.gen_load_int(r.ip.value, t, cond=fast_path_cond)
                    self.mc.ADD_rr(r.ip.value, r.r0.value, r.ip.value,
                                          cond=fast_path_cond)
                    t = 0
                    base = r.ip
                else:
                    base = r.r0
                self.mc.VLDR(resloc.value, base.value, imm=t,
                                          cond=fast_path_cond)
            else:
                assert resloc is r.r0
                if kind == INT:
                    t = unpack_interiorfielddescr(descrs.as_int)[0]
                else:
                    t = unpack_interiorfielddescr(descrs.as_ref)[0]
                if not check_imm_arg(t):
                    self.mc.gen_load_int(r.ip.value, t, cond=fast_path_cond)
                    self.mc.LDR_rr(resloc.value, resloc.value, r.ip.value,
                                          cond=fast_path_cond)
                else:
                    self.mc.LDR_ri(resloc.value, resloc.value, imm=t,
                                          cond=fast_path_cond)
        # jump to merge point
        jmp_pos = self.mc.currpos()
        self.mc.BKPT()

        # Path B: use assembler helper
        asm_helper_adr = self.cpu.cast_adr_to_int(jd.assembler_helper_adr)
        if self.cpu.supports_floats:
            floats = r.caller_vfp_resp
        else:
            floats = []
        # in case the call has a result we do not need to save the
        # corresponding result register because it was already allocated for
        # the result
        core = r.caller_resp
        if op.result:
            if resloc.is_vfp_reg():
                floats = r.caller_vfp_resp[1:]
            else:
                core = r.caller_resp[1:] + [r.ip]  # keep alignment
        with saved_registers(self.mc, core, floats):
            # result of previous call is in r0
            self.mov_loc_loc(arglocs[0], r.r1)
            self.mc.BL(asm_helper_adr)
            if not self.cpu.use_hf_abi and op.result and resloc.is_vfp_reg():
                # move result to the allocated register
                self.mov_to_vfp_loc(r.r0, r.r1, resloc)

        # merge point
        currpos = self.mc.currpos()
        pmc = OverwritingBuilder(self.mc, jmp_pos, WORD)
        pmc.B_offs(currpos, fast_path_cond)

        self.mc.LDR_ri(r.ip.value, r.fp.value)
        self.mc.CMP_ri(r.ip.value, 0)

        self._emit_guard(guard_op, regalloc._prepare_guard(guard_op),
                                                    c.GE, save_exc=True)
        return fcond

    # ../x86/assembler.py:668
    def redirect_call_assembler(self, oldlooptoken, newlooptoken):
        # some minimal sanity checking
        old_nbargs = oldlooptoken.compiled_loop_token._debug_nbargs
        new_nbargs = newlooptoken.compiled_loop_token._debug_nbargs
        assert old_nbargs == new_nbargs
        # we overwrite the instructions at the old _arm_func_adddr
        # to start with a JMP to the new _arm_func_addr.
        # Ideally we should rather patch all existing CALLs, but well.
        oldadr = oldlooptoken._arm_func_addr
        target = newlooptoken._arm_func_addr
        mc = ARMv7Builder()
        mc.B(target)
        mc.copy_to_raw_memory(oldadr)

    def emit_guard_call_may_force(self, op, guard_op, arglocs, regalloc,
                                                                    fcond):
        faildescr = guard_op.getdescr()
        fail_index = self.cpu.get_fail_descr_number(faildescr)
        self._write_fail_index(fail_index)
        numargs = op.numargs()
        callargs = arglocs[2:numargs + 1]  # extract the arguments to the call
        adr = arglocs[1]
        resloc = arglocs[0]
        #
        descr = op.getdescr()
        size = descr.get_result_size()
        signed = descr.is_result_signed()
        #
        self._emit_call(fail_index, adr, callargs, fcond,
                                    resloc, (size, signed))

        self.mc.LDR_ri(r.ip.value, r.fp.value)
        self.mc.CMP_ri(r.ip.value, 0)
        self._emit_guard(guard_op, arglocs[1 + numargs:], c.GE,
                                   save_exc=True, is_guard_not_forced=True)
        return fcond

    def emit_guard_call_release_gil(self, op, guard_op, arglocs, regalloc,
                                                                    fcond):

        # first, close the stack in the sense of the asmgcc GC root tracker
        gcrootmap = self.cpu.gc_ll_descr.gcrootmap
        numargs = op.numargs()
        callargs = arglocs[2:numargs + 1]  # extract the arguments to the call
        adr = arglocs[1]
        resloc = arglocs[0]

        if gcrootmap:
            self.call_release_gil(gcrootmap, arglocs, fcond)
        # do the call
        faildescr = guard_op.getdescr()
        fail_index = self.cpu.get_fail_descr_number(faildescr)
        self._write_fail_index(fail_index)
        #
        descr = op.getdescr()
        size = descr.get_result_size()
        signed = descr.is_result_signed()
        #
        self._emit_call(fail_index, adr, callargs, fcond,
                                    resloc, (size, signed))
        # then reopen the stack
        if gcrootmap:
            self.call_reacquire_gil(gcrootmap, resloc, fcond)

        self.mc.LDR_ri(r.ip.value, r.fp.value)
        self.mc.CMP_ri(r.ip.value, 0)

        self._emit_guard(guard_op, arglocs[1 + numargs:], c.GE, save_exc=True)
        return fcond

    def call_release_gil(self, gcrootmap, save_registers, fcond):
        # First, we need to save away the registers listed in
        # 'save_registers' that are not callee-save.
        # NOTE: We assume that  the floating point registers won't be modified.
        regs_to_save = []
        for reg in self._regalloc.rm.save_around_call_regs:
            if reg in save_registers:
                regs_to_save.append(reg)
        assert gcrootmap.is_shadow_stack
        with saved_registers(self.mc, regs_to_save):
            self._emit_call(NO_FORCE_INDEX,
                                imm(self.releasegil_addr), [], fcond)

    def call_reacquire_gil(self, gcrootmap, save_loc, fcond):
        # save the previous result into the stack temporarily.
        # NOTE: like with call_release_gil(), we assume that we don't need to
        # save vfp regs in this case. Besides the result location
        regs_to_save = []
        vfp_regs_to_save = []
        if save_loc.is_reg():
            regs_to_save.append(save_loc)
        if save_loc.is_vfp_reg():
            vfp_regs_to_save.append(save_loc)
        # call the reopenstack() function (also reacquiring the GIL)
        if len(regs_to_save) % 2 != 1:
            regs_to_save.append(r.ip)  # for alingment
        assert gcrootmap.is_shadow_stack
        with saved_registers(self.mc, regs_to_save, vfp_regs_to_save):
            self._emit_call(NO_FORCE_INDEX, imm(self.reacqgil_addr), [], fcond)

    def write_new_force_index(self):
        # for shadowstack only: get a new, unused force_index number and
        # write it to FORCE_INDEX_OFS.  Used to record the call shape
        # (i.e. where the GC pointers are in the stack) around a CALL
        # instruction that doesn't already have a force_index.
        gcrootmap = self.cpu.gc_ll_descr.gcrootmap
        if gcrootmap and gcrootmap.is_shadow_stack:
            clt = self.current_clt
            force_index = clt.reserve_and_record_some_faildescr_index()
            self._write_fail_index(force_index)
            return force_index
        else:
            return 0

    def _write_fail_index(self, fail_index):
        self.mc.gen_load_int(r.ip.value, fail_index)
        self.mc.STR_ri(r.ip.value, r.fp.value)

    def emit_op_call_malloc_gc(self, op, arglocs, regalloc, fcond):
        self.emit_op_call(op, arglocs, regalloc, fcond)
        self.propagate_memoryerror_if_r0_is_null()
        self._alignment_check()
        return fcond

    def emit_op_call_malloc_nursery(self, op, arglocs, regalloc, fcond):
        # registers r0 and r1 are allocated for this call
        assert len(arglocs) == 1
        size = arglocs[0].value
        gc_ll_descr = self.cpu.gc_ll_descr
        self.malloc_cond(
            gc_ll_descr.get_nursery_free_addr(),
            gc_ll_descr.get_nursery_top_addr(),
            size
            )
        self._alignment_check()
        return fcond

    def _alignment_check(self):
        if not self.debug:
            return
        self.mc.MOV_rr(r.ip.value, r.r0.value)
        self.mc.AND_ri(r.ip.value, r.ip.value, 3)
        self.mc.CMP_ri(r.ip.value, 0)
        self.mc.MOV_rr(r.pc.value, r.pc.value, cond=c.EQ)
        self.mc.BKPT()
        self.mc.NOP()

    emit_op_float_add = gen_emit_float_op('float_add', 'VADD')
    emit_op_float_sub = gen_emit_float_op('float_sub', 'VSUB')
    emit_op_float_mul = gen_emit_float_op('float_mul', 'VMUL')
    emit_op_float_truediv = gen_emit_float_op('float_truediv', 'VDIV')

    emit_op_float_neg = gen_emit_unary_float_op('float_neg', 'VNEG')
    emit_op_float_abs = gen_emit_unary_float_op('float_abs', 'VABS')
    emit_op_math_sqrt = gen_emit_unary_float_op('math_sqrt', 'VSQRT')

    emit_op_float_lt = gen_emit_float_cmp_op('float_lt', c.VFP_LT)
    emit_op_float_le = gen_emit_float_cmp_op('float_le', c.VFP_LE)
    emit_op_float_eq = gen_emit_float_cmp_op('float_eq', c.EQ)
    emit_op_float_ne = gen_emit_float_cmp_op('float_ne', c.NE)
    emit_op_float_gt = gen_emit_float_cmp_op('float_gt', c.GT)
    emit_op_float_ge = gen_emit_float_cmp_op('float_ge', c.GE)

    emit_guard_float_lt = gen_emit_float_cmp_op_guard('float_lt', c.VFP_LT)
    emit_guard_float_le = gen_emit_float_cmp_op_guard('float_le', c.VFP_LE)
    emit_guard_float_eq = gen_emit_float_cmp_op_guard('float_eq', c.EQ)
    emit_guard_float_ne = gen_emit_float_cmp_op_guard('float_ne', c.NE)
    emit_guard_float_gt = gen_emit_float_cmp_op_guard('float_gt', c.GT)
    emit_guard_float_ge = gen_emit_float_cmp_op_guard('float_ge', c.GE)

    def emit_op_cast_float_to_int(self, op, arglocs, regalloc, fcond):
        arg, res = arglocs
        assert arg.is_vfp_reg()
        assert res.is_reg()
        self.mc.VCVT_float_to_int(r.vfp_ip.value, arg.value)
        self.mc.VMOV_rc(res.value, r.ip.value, r.vfp_ip.value)
        return fcond

    def emit_op_cast_int_to_float(self, op, arglocs, regalloc, fcond):
        arg, res = arglocs
        assert res.is_vfp_reg()
        assert arg.is_reg()
        self.mc.MOV_ri(r.ip.value, 0)
        self.mc.VMOV_cr(res.value, arg.value, r.ip.value)
        self.mc.VCVT_int_to_float(res.value, res.value)
        return fcond

    emit_op_llong_add = gen_emit_float_op('llong_add', 'VADD_i64')
    emit_op_llong_sub = gen_emit_float_op('llong_sub', 'VSUB_i64')
    emit_op_llong_and = gen_emit_float_op('llong_and', 'VAND_i64')
    emit_op_llong_or = gen_emit_float_op('llong_or', 'VORR_i64')
    emit_op_llong_xor = gen_emit_float_op('llong_xor', 'VEOR_i64')

    def emit_op_llong_to_int(self, op, arglocs, regalloc, fcond):
        loc = arglocs[0]
        res = arglocs[1]
        assert loc.is_vfp_reg()
        assert res.is_reg()
        self.mc.VMOV_rc(res.value, r.ip.value, loc.value)
        return fcond

    emit_op_convert_float_bytes_to_longlong = gen_emit_unary_float_op(
                                    'float_bytes_to_longlong', 'VMOV_cc')
    emit_op_convert_longlong_bytes_to_float = gen_emit_unary_float_op(
                                    'longlong_bytes_to_float', 'VMOV_cc')

    def emit_op_read_timestamp(self, op, arglocs, regalloc, fcond):
        assert 0, 'not supported'
        tmp = arglocs[0]
        res = arglocs[1]
        self.mc.MRC(15, 0, tmp.value, 15, 12, 1)
        self.mc.MOV_ri(r.ip.value, 0)
        self.mc.VMOV_cr(res.value, tmp.value, r.ip.value)
        return fcond

    def emit_op_cast_float_to_singlefloat(self, op, arglocs, regalloc, fcond):
        arg, res = arglocs
        assert arg.is_vfp_reg()
        assert res.is_reg()
        self.mc.VCVT_f64_f32(r.vfp_ip.value, arg.value)
        self.mc.VMOV_rc(res.value, r.ip.value, r.vfp_ip.value)
        return fcond
    
    def emit_op_cast_singlefloat_to_float(self, op, arglocs, regalloc, fcond):
        arg, res = arglocs
        assert res.is_vfp_reg()
        assert arg.is_reg()
        self.mc.MOV_ri(r.ip.value, 0)
        self.mc.VMOV_cr(res.value, arg.value, r.ip.value)
        self.mc.VCVT_f32_f64(res.value, res.value)
        return fcond
