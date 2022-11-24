import pytest
from pytest import approx
import ast

from numerous.engine.model.lowering.utils import VariableArgument
from numerous.engine.model.utils import Imports

imports = Imports()
imports.add_as_import("numpy", "np")
from numerous.engine.model.lowering.ast_builder import ASTBuilder
import numpy as np
import os

initial_values = np.arange(1, 10, dtype=np.float64)
filename = 'ast_IR_code.txt'

GLOBAL_VARS = {'global_vars_t_7d17b9fa_71f6_4d99_8e9a_f91c1d45699a': -1}
IS_GLOBAL_VAR = False


@pytest.fixture(autouse=True)
def run_around_tests():
    yield
    if os.path.exists(filename):
        os.remove(filename)


eval_ast_signature = 'void(float64, float64, CPointer(float64), CPointer(float64))'

eval_ast = ast.parse('''def eval_ast(s_x1, s_x2, s_x2_dot, s_x3_dot):
    s_x2_dot = -100 if s_x1 > s_x2 else 50
    s_x3_dot = -s_x2_dot
    return s_x2_dot,s_x3_dot''').body[0]

eval_ast_mix_signature = 'void(float64, CPointer(float64),float64, CPointer(float64))'

eval_ast_mix = ast.parse('''def eval_ast_mix(s_x1, s_x2_dot, s_x2, s_x3_dot):
    s_x2_dot = -100 if s_x1 > s_x2 else 50
    s_x3_dot = -s_x2_dot
    return s_x2_dot,s_x3_dot''').body[0]

eval_ast2_signature = 'void(float64, float64, CPointer(float64), CPointer(float64))'

eval_ast2 = ast.parse('''def eval_ast2(s_x1, s_x2, s_x2_dot, s_x3_dot):
    s_x2_dot = nested(-100) if s_x1 > s_x2 else 50
    s_x3_dot = -s_x2_dot
    return s_x2_dot,s_x3_dot''').body[0]

nested = ast.parse('''def nested(s_x):
    return s_x + 1''').body[0]
nested_signature = "void(float64)"

number_of_derivatives = 3
number_of_states = 3

variable_names = {
    "oscillator1.mechanics.x": 0,
    "oscillator1.mechanics.y": 1,
    "oscillator1.mechanics.z": 2,
    "oscillator1.mechanics.a": 3,
    "oscillator1.mechanics.b": 4,
    "oscillator1.mechanics.c": 5,
    "oscillator1.mechanics.x_dot": 6,
    "oscillator1.mechanics.y_dot": 7,
    "oscillator1.mechanics.z_dot": 8,
}

variable_distributed = {
    "oscillator1.mechanics.a": 0,
    "oscillator1.mechanics.x_dot": 1,
    "oscillator1.mechanics.y_dot": 2,
    "oscillator1.mechanics.z_dot": 3,
    "oscillator1.mechanics.x": 4,
    "oscillator1.mechanics.b": 5,
    "oscillator1.mechanics.c": 6,
    "oscillator1.mechanics.y": 7,
    "oscillator1.mechanics.z": 8,
}
DERIVATIVES = ["oscillator1.mechanics.x_dot", "oscillator1.mechanics.y_dot", "oscillator1.mechanics.z_dot"]
STATES = ["oscillator1.mechanics.x", "oscillator1.mechanics.y", "oscillator1.mechanics.z"]


def test_ast_1_to_1_mapping_state():
    ast_program = ASTBuilder(initial_values, variable_names, GLOBAL_VARS, STATES, DERIVATIVES)

    ast_program.add_mapping([VariableArgument("oscillator1.mechanics.x", IS_GLOBAL_VAR)],
                            [VariableArgument("oscillator1.mechanics.x_dot", IS_GLOBAL_VAR)])

    diff, var_func, _ = ast_program.generate(imports)

    assert approx(diff(np.array([2.1, 2.2, 2.3]), np.array([0.0]))) == np.array([2.1, 8, 9.])


def test_ast_1_to_1_mapping_parameter():
    ast_program = ASTBuilder(initial_values, variable_names, GLOBAL_VARS, STATES, DERIVATIVES)

    ast_program.add_mapping([VariableArgument("oscillator1.mechanics.b", IS_GLOBAL_VAR)],
                            [VariableArgument("oscillator1.mechanics.x_dot", IS_GLOBAL_VAR)])

    diff, var_func, _ = ast_program.generate(imports)

    assert approx(diff(np.array([2.1, 2.2, 2.3]), np.array([0.0]))) == np.array([5, 8, 9.])


def test_ast_n_to_1_sum_mapping():
    ast_program = ASTBuilder(initial_values, variable_names, GLOBAL_VARS, STATES, DERIVATIVES)

    ast_program.add_mapping([VariableArgument("oscillator1.mechanics.x", IS_GLOBAL_VAR),
                             VariableArgument("oscillator1.mechanics.y", IS_GLOBAL_VAR),
                             VariableArgument("oscillator1.mechanics.b", IS_GLOBAL_VAR)],
                            [VariableArgument("oscillator1.mechanics.x_dot", IS_GLOBAL_VAR)])

    diff, var_func, _ = ast_program.generate(imports)

    assert approx(diff(np.array([2.1, 2.2, 2.3]), np.array([0.0]))) == np.array([9.3, 8, 9.])


def test_ast_1_to_n_mapping():
    ast_program = ASTBuilder(initial_values, variable_names, GLOBAL_VARS, STATES, DERIVATIVES)

    ast_program.add_mapping([VariableArgument("oscillator1.mechanics.x", IS_GLOBAL_VAR)],
                            [VariableArgument("oscillator1.mechanics.x_dot", IS_GLOBAL_VAR),
                             VariableArgument("oscillator1.mechanics.y_dot", IS_GLOBAL_VAR)])

    diff, var_func, _ = ast_program.generate(imports)

    assert approx(diff(np.array([2.1, 2.2, 2.3]), np.array([0.0]))) == np.array([2.1, 2.1, 9.])


def test_ast_1_function():
    ast_program = ASTBuilder(initial_values, variable_names, GLOBAL_VARS, STATES, DERIVATIVES)
    ast_program.add_external_function(eval_ast, eval_ast_signature, number_of_args=4, target_ids=[2, 3])

    ast_program.add_call(eval_ast.name,
                         [VariableArgument("oscillator1.mechanics.x", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.y", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.x_dot", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.y_dot", IS_GLOBAL_VAR)],
                         target_ids=[2, 3])

    diff, var_func, _ = ast_program.generate(imports)

    assert approx(diff(np.array([2.1, 2.2, 2.3]), np.array([0.0]))) == np.array([50, -50, 9.])
    assert approx(diff(np.array([2.3, 2.2, 2.1]), np.array([0.0]))) == np.array([-100, 100, 9.])


def test_ast_nested_function_and_mapping():
    ast_program = ASTBuilder(initial_values, variable_names, GLOBAL_VARS, STATES, DERIVATIVES)
    ast_program.add_external_function(eval_ast2, eval_ast2_signature, number_of_args=4, target_ids=[2, 3])
    ast_program.add_external_function(nested, nested_signature, number_of_args=1, target_ids=[])
    ast_program.add_call(eval_ast2.name,
                         [VariableArgument("oscillator1.mechanics.x", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.y", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.a", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.y_dot", IS_GLOBAL_VAR)],
                         target_ids=[2, 3])

    ast_program.add_mapping(args=[VariableArgument("oscillator1.mechanics.a", IS_GLOBAL_VAR)],
                            targets=[VariableArgument("oscillator1.mechanics.x_dot", IS_GLOBAL_VAR)])

    diff, var_func, _ = ast_program.generate(imports)

    assert approx(diff(np.array([2.1, 2.2, 2.3]), np.array([0.0]))) == np.array([50, -50, 9.])
    assert approx(diff(np.array([2.3, 2.2, 2.1]), np.array([0.0]))) == np.array([-99, 99, 9.])


def test_ast_1_function_and_mapping():
    ast_program = ASTBuilder(initial_values, variable_names, GLOBAL_VARS, STATES, DERIVATIVES)
    ast_program.add_external_function(eval_ast, eval_ast_signature, number_of_args=4, target_ids=[2, 3])

    ast_program.add_call(eval_ast.name,
                         [VariableArgument("oscillator1.mechanics.x", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.y", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.a", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.y_dot", IS_GLOBAL_VAR)],
                         target_ids=[2, 3])

    ast_program.add_mapping([VariableArgument("oscillator1.mechanics.a", IS_GLOBAL_VAR)],
                            [VariableArgument("oscillator1.mechanics.x_dot", IS_GLOBAL_VAR)])

    diff, var_func, _ = ast_program.generate(imports)

    assert approx(diff(np.array([2.1, 2.2, 2.3]), np.array([0.0]))) == np.array([50, -50, 9.])
    assert approx(diff(np.array([2.3, 2.2, 2.1]), np.array([0.0]))) == np.array([-100, 100, 9.])


def test_ast_unordered_vars():
    ast_program = ASTBuilder(initial_values, variable_distributed, GLOBAL_VARS, STATES, DERIVATIVES)
    ast_program.add_external_function(eval_ast, eval_ast_signature, number_of_args=4, target_ids=[2, 3])
    diff, var_func, _ = ast_program.generate(imports)
    assert approx(diff(np.array([2.1, 2.2, 2.3]), np.array([0.0]))) == np.array([2., 3., 4.])
    assert approx(var_func()) == np.array([1., 2., 3., 4., 2.1, 6., 7., 2.2, 2.3])


def test_ast_1_function_and_mapping_unordered_vars():
    ast_program = ASTBuilder(initial_values, variable_distributed, GLOBAL_VARS, STATES, DERIVATIVES)
    ast_program.add_external_function(eval_ast, eval_ast_signature, number_of_args=4, target_ids=[2, 3])

    ast_program.add_call(eval_ast.name,
                         [VariableArgument("oscillator1.mechanics.x", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.y", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.a", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.y_dot", IS_GLOBAL_VAR)],
                         target_ids=[2, 3])

    ast_program.add_mapping(args=[VariableArgument("oscillator1.mechanics.a", IS_GLOBAL_VAR)],
                            targets=[VariableArgument("oscillator1.mechanics.x_dot", IS_GLOBAL_VAR)])

    diff, var_func, _ = ast_program.generate(imports)
    assert approx(diff(np.array([2.1, 2.2, 2.3]), np.array([0.0]))) == np.array([50., -50., 4.])
    assert approx(diff(np.array([2.3, 2.2, 2.1]), np.array([0.0]))) == np.array([-100, 100, 4.])


def test_ast_1_function_and_mappings():
    ast_program = ASTBuilder(initial_values, variable_names, GLOBAL_VARS, STATES, DERIVATIVES)
    ast_program.add_external_function(eval_ast, eval_ast_signature, number_of_args=4, target_ids=[2, 3])

    ast_program.add_mapping(args=[VariableArgument("oscillator1.mechanics.x", IS_GLOBAL_VAR)],
                            targets=[VariableArgument("oscillator1.mechanics.b", IS_GLOBAL_VAR)])

    ast_program.add_call(eval_ast.name,
                         [VariableArgument("oscillator1.mechanics.b", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.y", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.a", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.y_dot", IS_GLOBAL_VAR)],
                         target_ids=[2, 3])

    ast_program.add_mapping(args=[VariableArgument("oscillator1.mechanics.a", IS_GLOBAL_VAR)],
                            targets=[VariableArgument("oscillator1.mechanics.b", IS_GLOBAL_VAR)])

    ast_program.add_call(eval_ast.name,
                         [VariableArgument("oscillator1.mechanics.b", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.y", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.a", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.y_dot", IS_GLOBAL_VAR)],
                         target_ids=[2, 3])

    diff, var_func, _ = ast_program.generate(imports)

    assert approx(diff(np.array([2.1, 2.2, 2.3]), np.array([0.0]))) == np.array([7., 100., 9.])

    assert approx(var_func()) == np.array([2.1, 2.2, 2.3, -100., 50., 6., 7., 100., 9.])


def test_ast_2_function_and_mappings():
    ast_program = ASTBuilder(initial_values, variable_names, GLOBAL_VARS, STATES, DERIVATIVES)
    ast_program.add_external_function(eval_ast, eval_ast_signature, number_of_args=4, target_ids=[2, 3])

    ast_program.add_call(eval_ast.name,
                         [VariableArgument("oscillator1.mechanics.b", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.y", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.a", IS_GLOBAL_VAR),
                          VariableArgument("oscillator1.mechanics.y_dot", IS_GLOBAL_VAR)],
                         target_ids=[2, 3])
    diff, var_func, _ = ast_program.generate(imports)

    assert approx(diff(np.array([2.1, 2.2, 2.3]), np.array([0.0]))) == np.array([7., 100., 9.])

    assert approx(var_func()) == np.array([2.1, 2.2, 2.3, -100., 5., 6., 7., 100., 9.])


def test_ast_loop_seq():
    ast_program = ASTBuilder(initial_values, variable_names, GLOBAL_VARS, STATES, DERIVATIVES)
    ast_program.add_external_function(eval_ast, eval_ast_signature, number_of_args=4, target_ids=[2, 3])

    ast_program.add_set_call(eval_ast.name, [
        ["oscillator1.mechanics.y",
         "oscillator1.mechanics.z",
         "oscillator1.mechanics.a",
         "oscillator1.mechanics.b"],
        ["oscillator1.mechanics.c",
         "oscillator1.mechanics.x_dot",
         "oscillator1.mechanics.y_dot",
         "oscillator1.mechanics.z_dot"]], targets_ids=[2, 3])

    diff, var_func, _ = ast_program.generate(imports)

    assert approx(diff(np.array([2.6, 2.2, 2.3]), np.array([0.0]))) == np.array([7, 50., -50])
    ##Note that state is not changed. States can only be changed by the solver
    assert approx(var_func()) == np.array([2.6, 2.2, 2.3, 50, -50., 6., 7., 50., -50.])


def test_ast_loop_mix():
    ast_program = ASTBuilder(initial_values, variable_names, GLOBAL_VARS, STATES, DERIVATIVES)
    ast_program.add_external_function(eval_ast_mix, eval_ast_mix_signature, number_of_args=4, target_ids=[1, 3])

    ast_program.add_set_call(eval_ast_mix.name, [
        ["oscillator1.mechanics.y", "oscillator1.mechanics.z", "oscillator1.mechanics.a", "oscillator1.mechanics.b"],
        ["oscillator1.mechanics.c", "oscillator1.mechanics.x_dot",
         "oscillator1.mechanics.y_dot",
         "oscillator1.mechanics.z_dot"]], targets_ids=[1, 3])

    diff, var_func, _ = ast_program.generate(imports)
    assert approx(diff(np.array([2.6, 2.2, 2.3]), np.array([0.0]))) == np.array([50, 8, -50])
    assert approx(var_func()) == np.array([2.6, 2.2, 50, 4, -50., 6., 50, 8., -50.])


def test_ast_idx_write():
    ast_program = ASTBuilder(initial_values, variable_names, GLOBAL_VARS, STATES, DERIVATIVES)
    ast_program.add_mapping([VariableArgument("oscillator1.mechanics.b", IS_GLOBAL_VAR)],
                            [VariableArgument("oscillator1.mechanics.x_dot", IS_GLOBAL_VAR),
                             VariableArgument("oscillator1.mechanics.y_dot", IS_GLOBAL_VAR)])
    diff, var_func, var_write = ast_program.generate(imports)

    var_write(100, 4)

    assert approx(var_func()) == np.array([1.0, 2.0, 3.0, 4., 100., 6., 7., 8., 9.])
    assert approx(diff(np.array([2.6, 2.2, 2.3]), np.array([0.0]))) == np.array([100, 100., 9.])
