from __future__ import print_function

from ctypes import CFUNCTYPE, POINTER, c_double, c_float, c_void_p, c_int64
from numba import carray, cfunc, njit

from time import perf_counter as time
from numerous import config
import faulthandler
import numpy as np

import llvmlite.ir as ll
import llvmlite.binding as llvm

faulthandler.enable()
llvm.initialize()
llvm.initialize_native_target()
llvm.initialize_native_asmprinter()
llvmmodule = llvm.parse_assembly("")
target_machine = llvm.Target.from_default_triple().create_target_machine()
ee = llvm.create_mcjit_compiler(llvmmodule, target_machine)


class LLVMGenerator:

    def __init__(self):
        self.detailed_print('target data: ', target_machine.target_data)
        self.detailed_print('target triple: ', target_machine.triple)
        self.module = ll.Module()
        self.ext_funcs = {}

    def add_external_function(self, function):
        """
        Wrap the function and make it available in the LLVM module
        """
        f_c = cfunc(sig=function['signature'])(function['func'])

        if not 'name' in function:
            function['name'] = function['func'].__qualname__

        name = function['name']

        f_c_sym = llvm.add_symbol(name, f_c.address)

        fnty_c_func = ll.FunctionType(ll.VoidType(),
                                      [ll.DoubleType() for _ in function['args']] + [ll.DoubleType().as_pointer() for _ in
                                                                              function['targets']])
        fnty_c_func.as_pointer(f_c_sym)
        f_llvm = ll.Function(self.module, fnty_c_func, name=name)

        self.ext_funcs[name] = f_llvm

    def generate(self, program, functions, variables, variable_values, ix_d, n_deriv):
        self.detailed_print('program lines: ', len(program))
        t1 = time()

        # Define the overall function
        fnty = ll.FunctionType(ll.DoubleType().as_pointer(), [
            ll.DoubleType().as_pointer()
        ])

        fnty.args[0].name = "y"

        for function in functions:
            self.add_external_function(function)

        # Define global variable array

        max_deriv = np.int64(n_deriv)
        max_var = np.int64(len(variables))

        var_global = ll.GlobalVariable(self.module, ll.ArrayType(ll.DoubleType(), max_var), 'global_var')
        var_global.initializer = ll.Constant(ll.ArrayType(ll.DoubleType(), max_var),
                                             [float(v) for v in variable_values])

        func = ll.Function(self.module, fnty, name="kernel")

        bb_entry = func.append_basic_block(name='entry')
        bb_loop = func.append_basic_block(name='main')
        bb_store = func.append_basic_block(name='store')
        bb_exit = func.append_basic_block(name='exit')

        builder = ll.IRBuilder()

        builder.position_at_end(bb_entry)
        index0 = builder.phi(ll.IntType(64), name='ix0')
        index0.add_incoming(ll.Constant(index0.type, 0), bb_entry)

        values = {}

        poplist = []
        for ix, p in enumerate(program):

            if p['func'] == 'load':

                index = builder.phi(ll.IntType(64), name=p['arg'] + f"_ix_{p['ix']}")
                index.add_incoming(ll.Constant(index.type, p['ix']), bb_entry)

                if p['arg'] == 'variables':
                    ptr = var_global
                    indices = [index0, index]

                elif p['arg'] == 'y':
                    ptr = func.args[0]
                    indices = [index]

                eptr = builder.gep(ptr, indices, name=p['arg'] + "_" + p['var'])
                values[p['var']] = eptr

                poplist.append(ix)

        [program.pop(i) for i in reversed(poplist)]

        builder.branch(bb_loop)
        builder.position_at_end(bb_loop)

        poplist = []
        single_arg_sum_counter = 0
        for ix, p in enumerate(program):

            if 'args' in p:
                args = [builder.load(values[a], 'arg_' + a) for a in p['args']]

            target_pointers = []
            if 'targets' in p:

                for t in p['targets']:
                    index = builder.phi(ll.IntType(64), name=t + "_ix")
                    index.add_incoming(ll.Constant(index.type, variables.index(t)), bb_entry)

                    ptr = var_global
                    indices = [index0, index]

                    eptr = builder.gep(ptr, indices, name=t)

                    target_pointers.append(eptr)
                    values[t] = eptr

            if p['func'] == 'call':

                builder.call(self.ext_funcs[p['ext_func']], args + target_pointers)

                poplist.append(ix)




            elif p['func'] == 'sum':

                accum = builder.phi(ll.DoubleType())
                accum.add_incoming(ll.Constant(accum.type, 0), bb_entry)
                la = len(p['args'])
                if la == 0:
                    pass
                elif la == 1:
                    single_arg_sum_counter += 1
                    for t in p['targets']:
                        builder.store(args[0], values[t])
                elif la == 2:
                    sum_ = builder.fadd(args[0], args[1])
                    for t in p['targets']:
                        builder.store(sum_, values[t])

                else:
                    accum = builder.fadd(args[0], args[1])
                    for i, a in enumerate(args[2:]):
                        accum = builder.fadd(accum, a)

                    for t in p['targets']:
                        builder.store(accum, values[t])

                poplist.append(ix)

        [program.pop(i) for i in reversed(poplist)]

        self.detailed_print('single assignments: ', single_arg_sum_counter)

        builder.branch(bb_store)
        builder.position_at_end(bb_store)

        poplist = []

        for ix, p in enumerate(program):
            if p['func'] == 'store':

                index = builder.phi(ll.IntType(64), name=p['arg'] + f"_ix_{p['ix']}")
                index.add_incoming(ll.Constant(index.type, p['ix']), bb_store)

                if p['arg'] == 'variables':
                    ptr = var_global
                    indices = [index0, index]

                eptr = builder.gep(ptr, indices)
                builder.store(builder.load(values[p['var']]), eptr)
                poplist.append(ix)

        [program.pop(i) for i in reversed(poplist)]

        if len(program) > 0:
            raise ValueError(f'Still program lines left: {str(program)}')

        builder.branch(bb_exit)

        builder.position_at_end(bb_exit)

        indexd = builder.phi(ll.IntType(64))

        indexd.add_incoming(ll.Constant(indexd.type, ix_d), bb_entry)
        dg_ptr = builder.gep(var_global, [index0, indexd])

        builder.ret(dg_ptr)
        # Vars function
        fnty_vars = ll.FunctionType(ll.DoubleType().as_pointer(), [ll.IntType(64)
                                                                   ])

        vars_func = ll.Function(self.module, fnty_vars, name="vars")

        bb_entry_var = vars_func.append_basic_block()

        bb_exit_var = vars_func.append_basic_block()

        builder_var = ll.IRBuilder()
        builder_var.position_at_end(bb_entry_var)
        builder_var.branch(bb_exit_var)

        builder_var.position_at_end(bb_exit_var)

        index0_var = builder_var.phi(ll.IntType(64))
        index0_var.add_incoming(ll.Constant(index0_var.type, 0), bb_entry_var)
        vg_ptr = builder_var.gep(var_global, [index0_var, index0_var])
        builder_var.ret(vg_ptr)

        t2 = time()

        self.detailed_print("-- generate IR:", t2 - t1)

        t3 = time()

        self.save_module('llvm_IR_code.txt')

        llmod = llvm.parse_assembly(str(self.module))

        t4 = time()

        self.detailed_print("-- parse assembly:", t4 - t3)

        pmb = llvm.create_pass_manager_builder()
        pmb.opt_level = 1
        pm = llvm.create_module_pass_manager()
        pmb.populate(pm)

        t5 = time()

        pm.run(llmod)

        t6 = time()

        self.detailed_print("-- optimize:", t6 - t5)

        t7 = time()

        ee.add_module(llmod)

        ee.finalize_object()
        cfptr = ee.get_function_address("kernel")
        cfptr_var = ee.get_function_address("vars")

        t8 = time()
        self.detailed_print("-- JIT compile:", t8 - t7)

        c_float_type = type(np.ctypeslib.as_ctypes(np.float64()))
        self.detailed_print(c_float_type)

        diff_ = CFUNCTYPE(POINTER(c_float_type), POINTER(c_float_type))(cfptr)

        vars_ = CFUNCTYPE(POINTER(c_float_type), c_int64)(cfptr_var)

        @njit('float64[:](float64[:])')
        def diff(y):

            deriv_pointer = diff_(y.ctypes)

            return carray(deriv_pointer, (n_deriv,)).copy()

        @njit('float64[:](float64[:],int64)')
        def variables_(var, set_):
            variables_pointer = vars_(0)
            variables_array = carray(variables_pointer, (max_var,))

            if set_ > 0:
                if len(var) == max_var:

                    variables_array[:] = var[:]
                else:
                    raise ValueError('bad length!')

            return variables_array

        @njit('float64[:](float64)')
        def variables__(f):
            variables_pointer = vars_(0)
            variables_array = carray(variables_pointer, (max_var,))

            return variables_array.copy()

        return diff, variables__, variables_, max_deriv

    def detailed_print(self, *args, sep=' ', end='\n', file=None):
        if config.PRINT_LLVM:
            print(*args, sep, end, file)

    def save_module(self, filename):
        with open(filename, 'w') as f:
            f.write(str(self.module))
