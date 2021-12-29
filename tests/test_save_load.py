import os

from pytest import approx
import pytest

from numerous.engine.model import Model
from numerous.engine.simulation import Simulation
from numerous.engine.system import ConnectorItem, ConnectorTwoWay, Item, Subsystem
from numerous.engine.simulation.solvers.base_solver import solver_types
from tests.test_equations import TestEq_input, Test_Eq, TestEq_ground



class I(ConnectorItem):
    def __init__(self, tag, P, T, R):
        super(I, self).__init__(tag)

        self.create_binding('output')

        t1 = self.create_namespace('t1')

        t1.add_equations([TestEq_input(P=P, T=T, R=R)])
        ##this line has to be after t1.add_equations since t1 inside output is created there
        self.output.t1.create_variable(name='T')
        t1.T_o = self.output.t1.T


class T(ConnectorTwoWay):
    def __init__(self, tag, T, R):
        super().__init__(tag, side1_name='input', side2_name='output')

        t1 = self.create_namespace('t1')
        t1.add_equations([Test_Eq(T=T, R=R)])

        t1.R_i = self.input.t1.R
        t1.T_i = self.input.t1.T

        ##we ask for variable T
        t1.T_o = self.output.t1.T


class G(Item):
    def __init__(self, tag, TG, RG):
        super().__init__(tag)

        t1 = self.create_namespace('t1')
        t1.add_equations([TestEq_ground(TG=TG, RG=RG)])

        # ##since we asked for variable T in binding we have to create variable T and map it to TG
        # t1.create_variable('T')
        # t1.T = t1.TG


class S3(Subsystem):
    def __init__(self, tag):
        super().__init__(tag)

        input = I('1', P=100, T=0, R=10)
        item1 = T('2', T=0, R=5)
        item2 = T('3', T=0, R=3)
        item3 = T('4', T=0, R=2)
        ## RG is redundant we use item3.R as a last value of R in a chain
        ground = G('5', TG=10, RG=2)

        input.bind(output=item1)

        item1.bind(input=input, output=item2)

        item2.bind(input=item1, output=item3)
        item3.bind(input=item2, output=ground)

        self.register_items([input, item1, item2, item3, ground])


@pytest.fixture()
def filename():
    filename  = 'test_stop_start'
    yield filename
    os.remove(filename)


@pytest.mark.parametrize("solver", solver_types)
@pytest.mark.parametrize("use_llvm", [True])
def test_import_export(solver,use_llvm):
    tag = 'S3_sl'
    Model(S3(tag),export_model=True)
    m2 = Model.from_file(f'./export_model/{tag}.numerous')
    s1 = Simulation(m2, t_start=0, t_stop=1000, num=100,solver_type=solver)
    s1.solve()
    assert approx(m2.states_as_vector, rel=0.1) == [2010, 1010, 510, 210]
