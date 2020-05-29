import copy
import time
import uuid
import numpy as np
import ast
import re
from numerous.engine.system.connector import Connector
from numerous.utils.historyDataFrame import HistoryDataFrame
from numerous.engine.scope import Scope, TemporaryScopeWrapper, ScopeVariable
from numerous.engine.simulation.simulation_callbacks import _SimulationCallback, _Event
from numerous.engine.system.subsystem import Subsystem
from numerous.engine.variables import VariableType


class ModelNamespace:

    def __init__(self, tag):
        self.tag = tag
        self.equation_dict = {}
        self.eq_variables_ids = []
        self.variables = {}


class ModelAssembler:

    @staticmethod
    def __create_scope(eq_tag, eq_variables, namespace, tag, variables):
        scope_id = "{0}_{1}_{2}".format(eq_tag, namespace.tag, tag, str(uuid.uuid4()))
        scope = Scope(scope_id)
        for variable in eq_variables:
            scope.add_variable(variable)
            # Needed for updating states after solve run
            if variable.type.value == VariableType.STATE.value:
                variable.associated_state_scope.append(scope_id)
            variables.update({variable.id: variable})
        return scope

    @staticmethod
    def t_1(input_namespace):
        scope_select = {}
        variables = {}
        equation_dict = {}
        tag, namespaces = input_namespace
        for namespace in namespaces:
            for i, (eq_tag, eq_methods) in enumerate(namespace.equation_dict.items()):
                scope = ModelAssembler.__create_scope(eq_tag,
                                                      map(namespace.variables.get, namespace.eq_variables_ids[i]),
                                                      namespace, tag, variables)
                scope_select.update({scope.id: scope})
                equation_dict.update({scope.id: eq_methods})

        return variables, scope_select, equation_dict


class Model:
    """
     The model object traverses the system to collect all information needed to pass to the solver
     for computation – the model also back-propagates the numerical results from the solver into the system,
     so they can be accessed as variable values there.
    """

    def __init__(self, system=None, historian=None, assemble=True, validate=False):

        self.system = system
        self.events = {}
        self.historian = historian if historian else HistoryDataFrame()
        self.callbacks = [self.historian.callback]
        self.derivatives = {}
        self.model_items = {}
        self.state_history = {}
        self.synchronized_scope = {}
        self.compiled_eq = []
        self.flat_scope_idx = None
        self.flat_scope_idx_from = None

        self.equation_dict = {}
        self.scope_variables = {}
        self.variables = {}
        self.flat_variables = {}
        self.path_variables = {}
        self.path_scope_variables = {}
        self.states = {}
        self.period = 1
        self.mapping_from = []
        self.mapping_to = []
        self.sum_mapping_from = []
        self.sum_mapping_to = []
        self.scope_variables_flat = []
        self.states_idx = []
        self.derivatives_idx = []
        self.scope_to_variables_idx = []

        self.info = {}
        if assemble:
            self.assemble()

        if validate:
            self.validate()

    def __restore_state(self):
        for key, value in self.historian.get_last_state():
            self.scope_variables[key] = value

    def sychronize_scope(self):
        """
        Synchronize the values between ScopeVariables and SystemVariables
        """
        self.scope_variables_flat = self.flat_variables[self.scope_to_variables_idx.flatten()]

    def _get_initial_scope_copy(self):
        return TemporaryScopeWrapper(copy.copy(self.scope_variables_flat), self.states_idx, self.derivatives_idx)

    def __add_item(self, item):
        model_namespaces = []
        if item.id in self.model_items:
            return model_namespaces

        if item.callbacks:
            self.callbacks.append(item.callbacks)

        self.model_items.update({item.id: item})
        model_namespaces.append((item.id, self.create_model_namespaces(item)))
        if isinstance(item, Connector):
            for binded_item in item.get_binded_items():
                model_namespaces.extend(self.__add_item(binded_item))
        if isinstance(item, Subsystem):
            for registered_item in item.registered_items.values():
                model_namespaces.extend(self.__add_item(registered_item))
        return model_namespaces

    def assemble(self):
        """
        Assembles the model.
        """
        assemble_start = time.time()
        model_namespaces = []
        for item in self.system.registered_items.values():
            model_namespaces.extend(self.__add_item(item))

        for (variables, scope_select, equation_dict) in map(ModelAssembler.t_1, model_namespaces):
            self.equation_dict.update(equation_dict)
            self.synchronized_scope.update(scope_select)
            self.scope_variables.update(variables)

        for tt in self.synchronized_scope.keys():
            eq_text = ""
            if self.equation_dict[tt]:
                eq_text = self.equation_dict[tt][0].lines

                for i, var in enumerate(self.synchronized_scope[tt].variables.values()):
                    p = re.compile(r"\." + var.tag + r"(?=[^\w*])")
                    eq_text = p.sub("[" + str(i) + "]", eq_text)
                eq_text = eq_text.replace("@Equation()", "")
                eq_text = eq_text.replace("self,", "")
                eq_text = eq_text.strip()
                idx = eq_text.find('\n') + 1
                spaces_len = len(eq_text[idx:]) - len(eq_text[idx:].lstrip())
                eq_text = eq_text[:idx] + " " * spaces_len + 'import numpy as np\n' + eq_text[idx:]
            else:
                eq_text = "def eval(scope):\n   pass"
            tree = ast.parse(eq_text, mode='exec')
            code = compile(tree, filename='test', mode='exec')
            namespace = {}
            exec(code, namespace)
            self.compiled_eq.append(list(namespace.values())[1])

        for i, variable in enumerate(self.scope_variables.values()):
            self.scope_variables_flat.append(variable.value)
            variable.position = i
            self.variables[variable.id].idx_in_scope.append(i)
            if variable.type.value == VariableType.STATE.value:
                self.states_idx.append(i)
            if variable.type.value == VariableType.DERIVATIVE.value:
                self.derivatives_idx.append(i)

        for i, variable in enumerate(self.scope_variables.values()):
            for mapping_id in variable.mapping_ids:
                self.mapping_from.append(i)
                ##TODO [0] is mapping to 1 var in scope_vars/ is it correct?
                if len(self.variables[mapping_id].idx_in_scope) > 1:
                    raise ValueError("Mapping to more then 1 variable")
                self.mapping_to.append(self.variables[mapping_id].idx_in_scope[0])
            for sum_mapping_id in variable.sum_mapping_ids:
                self.sum_mapping_from.append(i)
                self.sum_mapping_to.append(self.variables[sum_mapping_id].idx_in_scope[0])

        result = []
        for i, scope in enumerate(self.synchronized_scope.values()):
            row = []
            for j, var in enumerate(scope.variables.values()):
                row.append(var.position)
            result.append(np.array(row))
        result.append(np.array([0]))
        self.flat_scope_idx = np.array(result)
        self.flat_scope_idx_from = np.copy(self.flat_scope_idx)
        self.sum_mapping_mask = copy.deepcopy(self.flat_scope_idx)

        for scope in self.sum_mapping_mask:
            for i, idx in enumerate(scope):
                scope[i]=0

        for k, scope in enumerate(self.flat_scope_idx):
            for i, idx in enumerate(scope):
                for j, mapping_idx in enumerate(self.mapping_from):
                    if mapping_idx == idx:
                        scope[i] = self.mapping_to[j]
                for j, mapping_idx in enumerate(self.sum_mapping_from):
                    if mapping_idx == idx:
                        scope[i] = self.sum_mapping_to[j]
                        self.sum_mapping_mask[k][i] = 1

        self.scope_variables_flat = np.array(self.scope_variables_flat, dtype=np.float32)
        self.states_idx = np.array(self.states_idx)
        self.derivatives_idx = np.array(self.derivatives_idx)

        for variable in self.variables.values():
            for path in variable.path.path[self.system.id]:
                self.path_variables.update({path: variable})

        for variable in self.scope_variables.values():
            for path in self.variables[variable.id].path.path[self.system.id]:
                self.path_scope_variables.update({path: variable})

        self.__create_scope_mappings()

        self.flat_variables = np.array([x.value for x in self.variables.values()])
        self.flat_variables_ids = [x.id for x in self.variables.values()]
        self.scope_to_variables_idx = np.array([np.array(x.idx_in_scope) for x in self.variables.values()])
        assemble_finish = time.time()
        self.info.update({"Assemble time": assemble_finish - assemble_start})
        self.info.update({"Number of items": len(self.model_items)})
        self.info.update({"Number of variables": len(self.scope_variables)})
        self.info.update({"Number of equation scopes": len(self.equation_dict)})
        self.info.update({"Solver": {}})

    def get_states(self):
        """

        Returns
        -------
        states : list of states
            list of all states.
        """
        return self.scope_variables[self.states_idx]

    def validate(self):
        """
        Checks that all bindings are fulfilled.
        """
        valid = True
        for item in self.model_items.values():
            for binding in item.bindings:
                if binding.is_bindend():
                    pass
                else:
                    valid = False
        return valid

    def search_items(self, item_tag):
        """
        Search an item in items registered in the model by a tag

        Returns
        ----------
        items : list of :class:`numerous.engine.system.Item`
            set of items with given tag
               """
        return [item for item in self.model_items.values() if item.tag == item_tag]

    def __create_scope_mappings(self):
        for scope in self.synchronized_scope.values():
            for var in scope.variables.values():
                for mapping_id in var.mapping_ids:
                    var.mapping.append(self.scope_variables[mapping_id])
                for mapping_id in var.sum_mapping_ids:
                    var.sum_mapping.append(self.scope_variables[mapping_id])

    def restore_state(self, timestep=-1):
        """

        Parameters
        ----------
        timestep : time
            timestep that should be restored in the model. Default last known state is restored.

        Restores last saved state from the historian.
        """
        last_states = self.historian.get_last_state()
        r1 = []
        for state_name in last_states:
            if state_name in self.path_variables:
                if self.path_variables[state_name].type.value not in [VariableType.CONSTANT.value]:
                    self.path_variables[state_name].value = list(last_states[state_name].values())[0]
                if self.path_variables[state_name].type.value is VariableType.STATE.value:
                    r1.append(list(last_states[state_name].values())[0])
        self.scope_variables_flat[self.states_idx] = np.array(r1)

    @property
    def states_as_vector(self):
        """
        Returns current states values.

        Returns
        -------
        state_values : array of state values

        """
        if self.states_idx.size == 0:
            return np.array([])
        else:
            return self.scope_variables_flat[self.states_idx]

    def get_variable_path(self, id, item):
        for (variable, namespace) in item.get_variables():
            if variable.id == id:
                return "{0}.{1}".format(namespace.tag, variable.tag)
        if hasattr(item, 'registered_items'):
            for registered_item in item.registered_items.values():
                result = self.get_variable_path(id, registered_item)
                if result:
                    return "{0}.{1}".format(registered_item.tag, result)
        return ""

    def save_variables_schedule(self, period, filename):
        """
        Save data to file on given period.

        Parameters
        ----------
        period : timedelta
            timedelta of saving history to file

        filename : string
            Name of a file
        Returns
        -------

        """
        self.period = period

        def saver_callback(t, _):
            if t > self.period:
                self.historian.save(filename)
                self.period = t + self.period

        callback = _SimulationCallback("FileWriter")
        callback.add_callback_function(saver_callback)
        self.callbacks.append(callback)

    def add_event(self, name, event_function, callbacks=None):
        """
        Creating and adding Event callback.


        Parameters
        ----------
        name : string
            name of the event

        event_function : callable


        callbacks : list of callable
            callback associated with event

        Returns
        -------

        """
        if not callbacks:
            callbacks = []
        self.events.update({name: _Event(name, self, event_function=event_function, callbacks=callbacks)})

    def add_event_callback(self, event_name, event_callback):
        """
        Adding the callback to existing event

        Parameters
        ----------
        event_name : string
            name of the registered event

        event_callback : callable
            callback associated with event


        Returns
        -------

        """
        self.events[event_name].add_callbacks(event_callback)

    def create_alias(self, variable_name, alias):
        """

        Parameters
        ----------
        variable_name
        alias

        Returns
        -------

        """
        self.scope_variables[variable_name].alias = alias

    def add_callback(self, name, callback_function):
        """
        Adding a callback


        Parameters
        ----------
        name : string
            name of the callback

        callback_function : callable
            callback function

        """
        self.callbacks.append(_SimulationCallback(name, callback_function))

    def create_model_namespaces(self, item):
        namespaces_list = []
        for namespace in item.registered_namespaces.values():
            model_namespace = ModelNamespace(namespace.tag)
            equation_dict = {}
            eq_variables_ids = []
            for eq in namespace.associated_equations.values():
                equations = []
                ids = []
                for equation in eq.equations:
                    equations.append(equation)
                for vardesc in eq.variables_descriptions:
                    variable = namespace.get_variable(vardesc)
                    self.variables.update({variable.id: variable})
                    ids.append(variable.id)
                equation_dict.update({eq.tag: equations})
                eq_variables_ids.append(ids)
            model_namespace.equation_dict = equation_dict
            model_namespace.eq_variables_ids = eq_variables_ids
            model_namespace.variables = {v.id: ScopeVariable(v) for v in namespace.variables.shadow_dict.values()}
            namespaces_list.append(model_namespace)
        return namespaces_list

    def update_model_from_scope(self, t_scope):
        self.flat_variables = t_scope.flat_var[self.scope_to_variables_idx].sum(1)
        for i, v_id in enumerate(self.flat_variables_ids):
            # if not np.isclose(self.variables[v_id].value, self.flat_variables[i]):
            self.variables[v_id].value = self.flat_variables[i]
