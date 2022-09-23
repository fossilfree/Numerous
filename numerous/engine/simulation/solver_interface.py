import numpy as np
from numba.core.registry import CPUDispatcher
import numpy.typing as npt
from numerous.engine.model.compiled_model import CompiledModel
from numerous.engine.model import Model
from numerous.solver.interface import Interface, EventHandler, model, Model as SolverModel, SolveEvent


class NumerousEngineModelInterface(Interface):
    def __init__(self, model):
        self.model: NumerousEngineModel = model

    def get_deriv(self, t) -> np.array:
        y = self.get_states()
        return self.model.numba_model.func(t, y)

    def get_states(self) -> np.array:
        return self.model.numba_model.get_states()

    def set_states(self, states: npt.ArrayLike) -> None:
        return self.model.numba_model.set_states(states)

    def _get_variables(self) -> np.array:
        return self.model.numba_model.read_variables()

    def _write_variables(self, value: float, idx: int) -> None:
        self.model.numba_model.write_variables(value, idx)

    def _is_store_required(self) -> bool:
        return self.model.numba_model.is_store_required()

    def _is_external_data_update_needed(self, t) -> bool:
        return self.model.numba_model.is_external_data_update_needed(t)

    def _map_external_data(self, t) -> None:
        return self.model.numba_model.map_external_data(t)

    def historian_update(self, t: np.float64) -> SolveEvent:
        self.model.numba_model.historian_update(t)
        if self._is_store_required():
            return SolveEvent.Historian
        else:
            return SolveEvent.NoneEvent

    def pre_step(self, t) -> None:
        self._map_external_data(t)

    def post_step(self, t) -> SolveEvent:
        self._map_external_data(t)

        if self._is_store_required() and not self._is_external_data_update_needed(t):
            return SolveEvent.Historian
        elif not self._is_store_required() and self._is_external_data_update_needed(t):
            return SolveEvent.ExternalDataUpdate
        elif self._is_store_required() and self._is_external_data_update_needed(t):
            return SolveEvent.HistorianAndExternalUpdate
        else:
            return SolveEvent.NoneEvent

    def post_event(self, t: np.float64) -> SolveEvent:
        return self.historian_update(t)

    def get_event_results(self, t, y):
        ynew = self._get_variables_modified(y)
        return self.model.event_functions(t, ynew)

    def run_event_action(self, time_, event_id):
        modified_variables = self.model.event_actions(time_, self._get_variables(), event_id)
        modified_mask = (modified_variables != self._get_variables())
        for idx in np.argwhere(modified_mask):
            self._write_variables(modified_variables[idx[0]], idx[0])

    def get_next_time_event(self, t) -> tuple[int, float]:
        if len(self.model.time_events) == 0:
            return -1, -1
        else:
            t_event_min = -1
            event_ix_min = -1
            for event_ix, timestamps in enumerate(self.model.time_events):
                ix = np.searchsorted(timestamps, t, 'left')
                if ix > len(timestamps) - 1:
                    continue
                else:
                    t_event = timestamps[ix]
                    if t_event_min < 0:
                        t_event_min = t_event
                        event_ix_min = event_ix
                    if t_event < t_event_min:
                        t_event_min = t_event
                        event_ix_min = event_ix

            return event_ix_min, t_event_min

    def run_time_event_action(self, t, t_event_ix):

        modified_variables = self.model.time_event_actions(t, self._get_variables(), t_event_ix)
        modified_mask = (modified_variables != self._get_variables())
        for idx in np.argwhere(modified_mask):
            self._write_variables(modified_variables[idx[0]], idx[0])

    def _get_variables_modified(self, y_):
        old_states = self.get_states()
        self.set_states(y_)

        vars = self._get_variables().copy()
        self.set_states(old_states)
        return vars

    def get_event_directions(self) -> np.array:
        return self.model.event_directions

@model(interface=NumerousEngineModelInterface)
class NumerousEngineModel(SolverModel):
    def __init__(self, numba_model, event_functions, event_directions, event_actions, time_events,
                 time_event_actions):
        self.numba_model = numba_model
        self.event_functions = event_functions
        self.event_directions = event_directions
        self.event_actions = event_actions
        self.time_events = time_events
        self.time_event_actions = time_event_actions


class NumerousEngineEventHandler(EventHandler):
    def __init__(self, model: Model, nm: CompiledModel):
        super(NumerousEngineEventHandler, self).__init__()
        self._model = model
        self._nm = nm

    def handle_solve_event(self, interface, event_id: SolveEvent, t: float):
        if event_id == SolveEvent.Historian:
            self._model.create_historian_df()
            self._nm.historian_reinit()
        elif event_id == SolveEvent.ExternalDataUpdate:
            self._load_external_data(t)
        elif event_id == SolveEvent.HistorianAndExternalUpdate:
            self._model.create_historian_df()
            self._nm.historian_reinit()
            self._load_external_data(t)

    def _load_external_data(self, t):
        is_external_data = self._model.external_mappings.load_new_external_data_batch(t)
        external_mappings_numpy = self._model.external_mappings.external_mappings_numpy
        external_mappings_time = self._model.external_mappings.external_mappings_time
        max_external_t = self._model.external_mappings.t_max
        min_external_t = self._model.external_mappings.t_min

        if t > max_external_t:
            raise ValueError(f"No more external data at t={t} (t_max={max_external_t}")
        self._nm.is_external_data = is_external_data
        self._nm.update_external_data(external_mappings_numpy, external_mappings_time, max_external_t,
                                      min_external_t)

def generate_numerous_engine_solver_interface(model: Model, nm: CompiledModel,
                                              events: tuple[CPUDispatcher, np.ndarray, CPUDispatcher],
                                              timeevents: tuple[np.ndarray, CPUDispatcher]):
    event_functions = events[0]
    event_directions = events[1]
    event_actions = events[2]
    time_events = timeevents[0]
    time_event_actions = timeevents[1]

    numerous_engine_model = NumerousEngineModel(nm, event_functions, event_directions, event_actions, time_events,
                 time_event_actions)

    numerous_event_handler = NumerousEngineEventHandler(model, nm)

    return numerous_engine_model, numerous_event_handler
