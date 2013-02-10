from rpython.jit.codewriter.effectinfo import EffectInfo
from rpython.jit.metainterp import compile
from rpython.jit.metainterp.history import (Const, ConstInt, BoxInt, BoxFloat,
    BoxPtr, make_hashable_int)
from rpython.jit.metainterp.optimize import InvalidLoop
from rpython.jit.metainterp.optimizeopt.intutils import IntBound
from rpython.jit.metainterp.optimizeopt.optimizer import (Optimization, REMOVED,
    CONST_0, CONST_1)
from rpython.jit.metainterp.optimizeopt.util import _findall, make_dispatcher_method
from rpython.jit.metainterp.resoperation import (opboolinvers, opboolreflex, rop,
    ResOperation)
from rpython.rlib.rarithmetic import highest_bit


class OptRewrite(Optimization):
    """Rewrite operations into equivalent, cheaper operations.
       This includes already executed operations and constants.
    """
    def __init__(self):
        self.loop_invariant_results = {}
        self.loop_invariant_producer = {}

    def new(self):
        return OptRewrite()

    def produce_potential_short_preamble_ops(self, sb):
        for op in self.loop_invariant_producer.values():
            sb.add_potential(op)

    def propagate_forward(self, op):
        args = self.optimizer.make_args_key(op)
        if self.find_rewritable_bool(op, args):
            return

        dispatch_opt(self, op)

    def try_boolinvers(self, op, targs):
        oldop = self.get_pure_result(targs)
        if oldop is not None and oldop.getdescr() is op.getdescr():
            value = self.getvalue(oldop.result)
            if value.is_constant():
                if value.box.same_constant(CONST_1):
                    self.make_constant(op.result, CONST_0)
                    return True
                elif value.box.same_constant(CONST_0):
                    self.make_constant(op.result, CONST_1)
                    return True

        return False


    def find_rewritable_bool(self, op, args):
        try:
            oldopnum = opboolinvers[op.getopnum()]
        except KeyError:
            pass
        else:
            targs = self.optimizer.make_args_key(ResOperation(oldopnum, [args[0], args[1]],
                                                              None))
            if self.try_boolinvers(op, targs):
                return True

        try:
            oldopnum = opboolreflex[op.getopnum()] # FIXME: add INT_ADD, INT_MUL
        except KeyError:
            pass
        else:
            targs = self.optimizer.make_args_key(ResOperation(oldopnum, [args[1], args[0]],
                                                              None))
            oldop = self.get_pure_result(targs)
            if oldop is not None and oldop.getdescr() is op.getdescr():
                self.make_equal_to(op.result, self.getvalue(oldop.result))
                return True

        try:
            oldopnum = opboolinvers[opboolreflex[op.getopnum()]]
        except KeyError:
            pass
        else:
            targs = self.optimizer.make_args_key(ResOperation(oldopnum, [args[1], args[0]],
                                                              None))
            if self.try_boolinvers(op, targs):
                return True

        return False

    def optimize_INT_AND(self, op):
        v1 = self.getvalue(op.getarg(0))
        v2 = self.getvalue(op.getarg(1))
        if v1.is_null() or v2.is_null():
            self.make_constant_int(op.result, 0)
        else:
            self.emit_operation(op)

    def optimize_INT_OR(self, op):
        v1 = self.getvalue(op.getarg(0))
        v2 = self.getvalue(op.getarg(1))
        if v1.is_null():
            self.make_equal_to(op.result, v2)
        elif v2.is_null():
            self.make_equal_to(op.result, v1)
        else:
            self.emit_operation(op)

    def optimize_INT_SUB(self, op):
        v1 = self.getvalue(op.getarg(0))
        v2 = self.getvalue(op.getarg(1))
        if v2.is_constant() and v2.box.getint() == 0:
            self.make_equal_to(op.result, v1)
        else:
            self.emit_operation(op)
            # Synthesize the reverse ops for optimize_default to reuse
            self.pure(rop.INT_ADD, [op.result, op.getarg(1)], op.getarg(0))
            self.pure(rop.INT_SUB, [op.getarg(0), op.result], op.getarg(1))

    def optimize_INT_ADD(self, op):
        v1 = self.getvalue(op.getarg(0))
        v2 = self.getvalue(op.getarg(1))

        # If one side of the op is 0 the result is the other side.
        if v1.is_constant() and v1.box.getint() == 0:
            self.make_equal_to(op.result, v2)
        elif v2.is_constant() and v2.box.getint() == 0:
            self.make_equal_to(op.result, v1)
        else:
            self.emit_operation(op)
            # Synthesize the reverse op for optimize_default to reuse
            self.pure(rop.INT_SUB, [op.result, op.getarg(1)], op.getarg(0))
            self.pure(rop.INT_SUB, [op.result, op.getarg(0)], op.getarg(1))

    def optimize_INT_MUL(self, op):
        v1 = self.getvalue(op.getarg(0))
        v2 = self.getvalue(op.getarg(1))

        # If one side of the op is 1 the result is the other side.
        if v1.is_constant() and v1.box.getint() == 1:
            self.make_equal_to(op.result, v2)
        elif v2.is_constant() and v2.box.getint() == 1:
            self.make_equal_to(op.result, v1)
        elif (v1.is_constant() and v1.box.getint() == 0) or \
             (v2.is_constant() and v2.box.getint() == 0):
            self.make_constant_int(op.result, 0)
        else:
            for lhs, rhs in [(v1, v2), (v2, v1)]:
                if lhs.is_constant():
                    x = lhs.box.getint()
                    # x & (x - 1) == 0 is a quick test for power of 2
                    if x & (x - 1) == 0:
                        new_rhs = ConstInt(highest_bit(lhs.box.getint()))
                        op = op.copy_and_change(rop.INT_LSHIFT, args=[rhs.box, new_rhs])
                        break
            self.emit_operation(op)

    def optimize_UINT_FLOORDIV(self, op):
        v1 = self.getvalue(op.getarg(0))
        v2 = self.getvalue(op.getarg(1))

        if v2.is_constant() and v2.box.getint() == 1:
            self.make_equal_to(op.result, v1)
        else:
            self.emit_operation(op)

    def optimize_INT_LSHIFT(self, op):
        v1 = self.getvalue(op.getarg(0))
        v2 = self.getvalue(op.getarg(1))

        if v2.is_constant() and v2.box.getint() == 0:
            self.make_equal_to(op.result, v1)
        else:
            self.emit_operation(op)

    def optimize_INT_RSHIFT(self, op):
        v1 = self.getvalue(op.getarg(0))
        v2 = self.getvalue(op.getarg(1))

        if v2.is_constant() and v2.box.getint() == 0:
            self.make_equal_to(op.result, v1)
        else:
            self.emit_operation(op)

    def optimize_FLOAT_MUL(self, op):
        arg1 = op.getarg(0)
        arg2 = op.getarg(1)

        # Constant fold f0 * 1.0 and turn f0 * -1.0 into a FLOAT_NEG, these
        # work in all cases, including NaN and inf
        for lhs, rhs in [(arg1, arg2), (arg2, arg1)]:
            v1 = self.getvalue(lhs)
            v2 = self.getvalue(rhs)

            if v1.is_constant():
                if v1.box.getfloat() == 1.0:
                    self.make_equal_to(op.result, v2)
                    return
                elif v1.box.getfloat() == -1.0:
                    self.emit_operation(ResOperation(
                        rop.FLOAT_NEG, [rhs], op.result
                    ))
                    return
        self.emit_operation(op)
        self.pure(rop.FLOAT_MUL, [arg2, arg1], op.result)

    def optimize_FLOAT_NEG(self, op):
        v1 = op.getarg(0)
        self.emit_operation(op)
        self.pure(rop.FLOAT_NEG, [op.result], v1)

    def optimize_guard(self, op, constbox, emit_operation=True):
        value = self.getvalue(op.getarg(0))
        if value.is_constant():
            box = value.box
            assert isinstance(box, Const)
            if not box.same_constant(constbox):
                raise InvalidLoop('A GUARD_{VALUE,TRUE,FALSE} was proven to' +
                                  'always fail')
            return
        if emit_operation:
            self.emit_operation(op)
        value.make_constant(constbox)
        self.optimizer.turned_constant(value)

    def optimize_GUARD_ISNULL(self, op):
        value = self.getvalue(op.getarg(0))
        if value.is_null():
            return
        elif value.is_nonnull():
            raise InvalidLoop('A GUARD_ISNULL was proven to always fail')
        self.emit_operation(op)
        value.make_constant(self.optimizer.cpu.ts.CONST_NULL)

    def optimize_GUARD_NONNULL(self, op):
        value = self.getvalue(op.getarg(0))
        if value.is_nonnull():
            return
        elif value.is_null():
            raise InvalidLoop('A GUARD_NONNULL was proven to always fail')
        self.emit_operation(op)
        value.make_nonnull(op)

    def optimize_GUARD_VALUE(self, op):
        value = self.getvalue(op.getarg(0))
        if value.is_virtual():
            raise InvalidLoop('A promote of a virtual (a recently allocated object) never makes sense!')
        if value.last_guard:
            # there already has been a guard_nonnull or guard_class or
            # guard_nonnull_class on this value, which is rather silly.
            # replace the original guard with a guard_value
            old_guard_op = value.last_guard
            if old_guard_op.getopnum() != rop.GUARD_NONNULL:
                # This is only safe if the class of the guard_value matches the
                # class of the guard_*_class, otherwise the intermediate ops might
                # be executed with wrong classes.
                previous_classbox = value.get_constant_class(self.optimizer.cpu)            
                expected_classbox = self.optimizer.cpu.ts.cls_of_box(op.getarg(1))
                assert previous_classbox is not None
                assert expected_classbox is not None
                if not previous_classbox.same_constant(expected_classbox):
                    raise InvalidLoop('A GUARD_VALUE was proven to always fail')
            op = old_guard_op.copy_and_change(rop.GUARD_VALUE,
                                      args = [old_guard_op.getarg(0), op.getarg(1)])
            self.optimizer.replaces_guard[op] = old_guard_op
            # hack hack hack.  Change the guard_opnum on
            # new_guard_op.getdescr() so that when resuming,
            # the operation is not skipped by pyjitpl.py.
            descr = op.getdescr()
            assert isinstance(descr, compile.ResumeGuardDescr)
            descr.guard_opnum = rop.GUARD_VALUE
            descr.make_a_counter_per_value(op)
            # to be safe
            value.last_guard = None
        constbox = op.getarg(1)
        assert isinstance(constbox, Const)
        self.optimize_guard(op, constbox)

    def optimize_GUARD_TRUE(self, op):
        self.optimize_guard(op, CONST_1)

    def optimize_GUARD_FALSE(self, op):
        self.optimize_guard(op, CONST_0)

    def optimize_RECORD_KNOWN_CLASS(self, op):
        value = self.getvalue(op.getarg(0))
        expectedclassbox = op.getarg(1)
        assert isinstance(expectedclassbox, Const)
        realclassbox = value.get_constant_class(self.optimizer.cpu)
        if realclassbox is not None:
            assert realclassbox.same_constant(expectedclassbox)
            return
        value.make_constant_class(expectedclassbox, None)

    def optimize_GUARD_CLASS(self, op):
        value = self.getvalue(op.getarg(0))
        expectedclassbox = op.getarg(1)
        assert isinstance(expectedclassbox, Const)
        realclassbox = value.get_constant_class(self.optimizer.cpu)
        if realclassbox is not None:
            if realclassbox.same_constant(expectedclassbox):
                return
            raise InvalidLoop('A GUARD_CLASS was proven to always fail')
        if value.last_guard:
            # there already has been a guard_nonnull or guard_class or
            # guard_nonnull_class on this value.
            old_guard_op = value.last_guard
            if old_guard_op.getopnum() == rop.GUARD_NONNULL:
                # it was a guard_nonnull, which we replace with a
                # guard_nonnull_class.
                op = old_guard_op.copy_and_change (rop.GUARD_NONNULL_CLASS,
                                         args = [old_guard_op.getarg(0), op.getarg(1)])
                self.optimizer.replaces_guard[op] = old_guard_op
                # hack hack hack.  Change the guard_opnum on
                # new_guard_op.getdescr() so that when resuming,
                # the operation is not skipped by pyjitpl.py.
                descr = op.getdescr()
                assert isinstance(descr, compile.ResumeGuardDescr)
                descr.guard_opnum = rop.GUARD_NONNULL_CLASS
        self.emit_operation(op)
        value.make_constant_class(expectedclassbox, op)

    def optimize_GUARD_NONNULL_CLASS(self, op):
        value = self.getvalue(op.getarg(0))
        if value.is_null():
            raise InvalidLoop('A GUARD_NONNULL_CLASS was proven to always ' +
                              'fail')
        self.optimize_GUARD_CLASS(op)

    def optimize_CALL_LOOPINVARIANT(self, op):
        arg = op.getarg(0)
        # 'arg' must be a Const, because residual_call in codewriter
        # expects a compile-time constant
        assert isinstance(arg, Const)
        key = make_hashable_int(arg.getint())

        resvalue = self.loop_invariant_results.get(key, None)
        if resvalue is not None:
            self.make_equal_to(op.result, resvalue)
            self.last_emitted_operation = REMOVED
            return
        # change the op to be a normal call, from the backend's point of view
        # there is no reason to have a separate operation for this
        self.loop_invariant_producer[key] = op
        op = op.copy_and_change(rop.CALL)
        self.emit_operation(op)
        resvalue = self.getvalue(op.result)
        self.loop_invariant_results[key] = resvalue

    def _optimize_nullness(self, op, box, expect_nonnull):
        value = self.getvalue(box)
        if value.is_nonnull():
            self.make_constant_int(op.result, expect_nonnull)
        elif value.is_null():
            self.make_constant_int(op.result, not expect_nonnull)
        else:
            self.emit_operation(op)

    def optimize_INT_IS_TRUE(self, op):
        if self.getvalue(op.getarg(0)) in self.optimizer.bool_boxes:
            self.make_equal_to(op.result, self.getvalue(op.getarg(0)))
            return
        self._optimize_nullness(op, op.getarg(0), True)

    def optimize_INT_IS_ZERO(self, op):
        self._optimize_nullness(op, op.getarg(0), False)

    def _optimize_oois_ooisnot(self, op, expect_isnot, instance):
        value0 = self.getvalue(op.getarg(0))
        value1 = self.getvalue(op.getarg(1))
        if value0.is_virtual():
            if value1.is_virtual():
                intres = (value0 is value1) ^ expect_isnot
                self.make_constant_int(op.result, intres)
            else:
                self.make_constant_int(op.result, expect_isnot)
        elif value1.is_virtual():
            self.make_constant_int(op.result, expect_isnot)
        elif value1.is_null():
            self._optimize_nullness(op, op.getarg(0), expect_isnot)
        elif value0.is_null():
            self._optimize_nullness(op, op.getarg(1), expect_isnot)
        elif value0 is value1:
            self.make_constant_int(op.result, not expect_isnot)
        else:
            if instance:
                cls0 = value0.get_constant_class(self.optimizer.cpu)
                if cls0 is not None:
                    cls1 = value1.get_constant_class(self.optimizer.cpu)
                    if cls1 is not None and not cls0.same_constant(cls1):
                        # cannot be the same object, as we know that their
                        # class is different
                        self.make_constant_int(op.result, expect_isnot)
                        return
            self.emit_operation(op)

    def optimize_PTR_EQ(self, op):
        self._optimize_oois_ooisnot(op, False, False)

    def optimize_PTR_NE(self, op):
        self._optimize_oois_ooisnot(op, True, False)

    def optimize_INSTANCE_PTR_EQ(self, op):
        self._optimize_oois_ooisnot(op, False, True)

    def optimize_INSTANCE_PTR_NE(self, op):
        self._optimize_oois_ooisnot(op, True, True)

##    def optimize_INSTANCEOF(self, op):
##        value = self.getvalue(op.args[0])
##        realclassbox = value.get_constant_class(self.optimizer.cpu)
##        if realclassbox is not None:
##            checkclassbox = self.optimizer.cpu.typedescr2classbox(op.descr)
##            result = self.optimizer.cpu.ts.subclassOf(self.optimizer.cpu,
##                                                      realclassbox,
##                                                      checkclassbox)
##            self.make_constant_int(op.result, result)
##            return
##        self.emit_operation(op)

    def optimize_CALL(self, op):
        # dispatch based on 'oopspecindex' to a method that handles
        # specifically the given oopspec call.  For non-oopspec calls,
        # oopspecindex is just zero.
        effectinfo = op.getdescr().get_extra_info()
        oopspecindex = effectinfo.oopspecindex
        if oopspecindex == EffectInfo.OS_ARRAYCOPY:
            if self._optimize_CALL_ARRAYCOPY(op):
                return
        self.emit_operation(op)

    def _optimize_CALL_ARRAYCOPY(self, op):
        source_value = self.getvalue(op.getarg(1))
        dest_value = self.getvalue(op.getarg(2))
        source_start_box = self.get_constant_box(op.getarg(3))
        dest_start_box = self.get_constant_box(op.getarg(4))
        length = self.get_constant_box(op.getarg(5))
        extrainfo = op.getdescr().get_extra_info()
        if (source_start_box and dest_start_box
            and length and (dest_value.is_virtual() or length.getint() <= 8) and
            (source_value.is_virtual() or length.getint() <= 8) and
            len(extrainfo.write_descrs_arrays) == 1):   # <-sanity check
            from rpython.jit.metainterp.optimizeopt.virtualize import VArrayValue
            source_start = source_start_box.getint()
            dest_start = dest_start_box.getint()
            # XXX fish fish fish
            arraydescr = extrainfo.write_descrs_arrays[0]
            for index in range(length.getint()):
                if source_value.is_virtual():
                    assert isinstance(source_value, VArrayValue)
                    val = source_value.getitem(index + source_start)
                else:
                    if arraydescr.is_array_of_pointers():
                        resbox = BoxPtr()
                    elif arraydescr.is_array_of_floats():
                        resbox = BoxFloat()
                    else:
                        resbox = BoxInt()
                    newop = ResOperation(rop.GETARRAYITEM_GC,
                                      [op.getarg(1),
                                       ConstInt(index + source_start)], resbox,
                                       descr=arraydescr)
                    self.optimizer.propagate_forward(newop)
                    val = self.getvalue(resbox)
                if dest_value.is_virtual():
                    dest_value.setitem(index + dest_start, val)
                else:
                    newop = ResOperation(rop.SETARRAYITEM_GC,
                                         [op.getarg(2),
                                          ConstInt(index + dest_start),
                                          val.get_key_box()], None,
                                         descr=arraydescr)
                    self.emit_operation(newop)
            return True
        if length and length.getint() == 0:
            return True # 0-length arraycopy
        return False

    def optimize_CALL_PURE(self, op):
        arg_consts = []
        for i in range(op.numargs()):
            arg = op.getarg(i)
            const = self.get_constant_box(arg)
            if const is None:
                break
            arg_consts.append(const)
        else:
            # all constant arguments: check if we already know the result
            try:
                result = self.optimizer.call_pure_results[arg_consts]
            except KeyError:
                pass
            else:
                # this removes a CALL_PURE with all constant arguments.
                self.make_constant(op.result, result)
                self.last_emitted_operation = REMOVED
                return
        self.emit_operation(op)

    def optimize_GUARD_NO_EXCEPTION(self, op):
        if self.last_emitted_operation is REMOVED:
            # it was a CALL_PURE or a CALL_LOOPINVARIANT that was killed;
            # so we also kill the following GUARD_NO_EXCEPTION
            return
        self.emit_operation(op)

    def optimize_INT_FLOORDIV(self, op):
        v1 = self.getvalue(op.getarg(0))
        v2 = self.getvalue(op.getarg(1))

        if v2.is_constant() and v2.box.getint() == 1:
            self.make_equal_to(op.result, v1)
            return
        elif v1.is_constant() and v1.box.getint() == 0:
            self.make_constant_int(op.result, 0)
            return
        if v1.intbound.known_ge(IntBound(0, 0)) and v2.is_constant():
            val = v2.box.getint()
            if val & (val - 1) == 0 and val > 0: # val == 2**shift
                op = op.copy_and_change(rop.INT_RSHIFT,
                                        args = [op.getarg(0), ConstInt(highest_bit(val))])
        self.emit_operation(op)

    def optimize_CAST_PTR_TO_INT(self, op):
        self.pure(rop.CAST_INT_TO_PTR, [op.result], op.getarg(0))
        self.emit_operation(op)

    def optimize_CAST_INT_TO_PTR(self, op):
        self.pure(rop.CAST_PTR_TO_INT, [op.result], op.getarg(0))
        self.emit_operation(op)

    def optimize_SAME_AS(self, op):
        self.make_equal_to(op.result, self.getvalue(op.getarg(0)))

dispatch_opt = make_dispatcher_method(OptRewrite, 'optimize_',
        default=OptRewrite.emit_operation)
optimize_guards = _findall(OptRewrite, 'optimize_', 'GUARD')
