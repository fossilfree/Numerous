from numba import int32, float64, boolean, int64, njit, types, typed, typeof

import numpy as np

# key and value types
kv_ty = (types.unicode_type, float64)

numba_model_spec = [
    ('var_idxs_pos_3d', types.Tuple((int64[:], int64[:], int64[:]))),
    ('var_idxs_pos_3d_helper', int64[:]),
    ('start_time', int64),
    ('eq_count', int64),
    ('number_of_timesteps', int64),
    ('number_of_variables', int64),
    ('number_of_states', int64),
    ('number_of_mappings', int64),
    ('scope_vars_3d', float64[:, :, :]),
    ('state_idxs_3d', types.Tuple((int64[:], int64[:], int64[:]))),
    ('deriv_idxs_3d', types.Tuple((int64[:], int64[:], int64[:]))),
    ('differing_idxs_pos_3d', types.Tuple((int64[:], int64[:], int64[:]))),
    ('differing_idxs_from_3d', types.Tuple((int64[:], int64[:], int64[:]))),
    ('num_uses_per_eq', int64[:]),
    ('sum_idxs_pos_3d', types.Tuple((int64[:], int64[:], int64[:]))),
    ('sum_idxs_sum_3d', types.Tuple((int64[:], int64[:], int64[:]))),
    ('sum_slice_idxs', int64[:]),
    ('sum_slice_idxs_len', int64[:]),
    ('sum_mapping', boolean),
    ('global_vars', float64[:]),
    ('historian_ix', int64),
    ('historian_data', float64[:, :]),
    ('path_variables', types.DictType(*kv_ty)),
    ('path_keys', types.ListType(types.unicode_type)),
    ('mapped_variables_array', int64[:,:])
]


class NumbaModel:
    def __init__(self, var_idxs_pos_3d, var_idxs_pos_3d_helper, eq_count, number_of_states, number_of_mappings,
                 scope_vars_3d, state_idxs_3d, deriv_idxs_3d,
                 differing_idxs_pos_3d, differing_idxs_from_3d, num_uses_per_eq,
                 sum_idxs_pos_3d, sum_idxs_sum_3d, sum_slice_idxs, sum_slice_idxs_len, sum_mapping,
                 global_vars, number_of_timesteps, number_of_variables, start_time, mapped_variables_array):

        self.var_idxs_pos_3d = var_idxs_pos_3d
        self.var_idxs_pos_3d_helper = var_idxs_pos_3d_helper
        self.eq_count = eq_count
        self.number_of_states = number_of_states
        self.scope_vars_3d = scope_vars_3d
        self.state_idxs_3d = state_idxs_3d
        self.deriv_idxs_3d = deriv_idxs_3d
        self.differing_idxs_pos_3d = differing_idxs_pos_3d
        self.differing_idxs_from_3d = differing_idxs_from_3d
        self.num_uses_per_eq = num_uses_per_eq
        self.number_of_mappings = number_of_mappings
        self.sum_idxs_pos_3d = sum_idxs_pos_3d
        self.sum_idxs_sum_3d = sum_idxs_sum_3d
        self.sum_slice_idxs = sum_slice_idxs
        self.sum_slice_idxs_len = sum_slice_idxs_len
        self.sum_mapping = sum_mapping
        self.global_vars = global_vars
        self.path_variables = typed.Dict.empty(*kv_ty)
        self.path_keys = typed.List.empty_list(types.unicode_type)
        self.number_of_timesteps = number_of_timesteps
        self.number_of_variables = number_of_variables
        self.start_time = start_time
        self.historian_ix = 0
        ##* simulation.num_inner
        self.historian_data = np.empty((self.number_of_variables + 1, number_of_timesteps), dtype=np.float64)
        self.historian_data.fill(np.nan)
        self.mapped_variables_array = mapped_variables_array
        ##Function is genrated in model.py contains creation and initialization of all callback related variables

    def update_states(self, state_values):
        for i in range(self.number_of_states):
            self.scope_vars_3d[self.state_idxs_3d[0][i]][self.state_idxs_3d[1][i]][self.state_idxs_3d[2][i]] \
                = state_values[i]

    def update_states_idx(self, state_value, idx_3d):
        self.scope_vars_3d[idx_3d] = state_value

    def get_derivatives(self):
        result = []
        for i in range(self.number_of_states):
            result.append(
                self.scope_vars_3d[self.deriv_idxs_3d[0][i]][self.deriv_idxs_3d[1][i]][self.deriv_idxs_3d[2][i]])
        return result

    def get_mapped_variables(self, scope_3d):
        result = []
        for i in range(self.number_of_mappings):
            result.append(
                scope_3d[self.differing_idxs_from_3d[0][i]][self.differing_idxs_from_3d[1][i]]
                [self.differing_idxs_from_3d[2][i]])
        return np.array(result, dtype=np.float64)

    def get_states(self):
        result = []
        for i in range(self.number_of_states):
            result.append(
                self.scope_vars_3d[self.state_idxs_3d[0][i]][self.state_idxs_3d[1][i]][self.state_idxs_3d[2][i]])
        return result

    def historian_update(self, time: np.int64) -> None:
        ix = self.historian_ix
        varix = 1
        self.historian_data[0][ix] = time
        for j in self.var_idxs_pos_3d_helper:
            self.historian_data[varix][ix] = self.scope_vars_3d[self.var_idxs_pos_3d[0][j]][self.var_idxs_pos_3d[1][j]][
                self.var_idxs_pos_3d[2][j]]
            varix += 1
        self.historian_ix += 1

    def run_callbacks_with_updates(self, time: np.int64) -> None:
        '''
        Updates all the values of all Variable instances stored in
        `self.variables` with the values stored in `self.scope_vars_3d`.
        '''

        for key, j in zip(self.path_keys,
                          self.var_idxs_pos_3d_helper):
            self.path_variables[key] \
                = self.scope_vars_3d[self.var_idxs_pos_3d[0][j]][self.var_idxs_pos_3d[1][j]][
                self.var_idxs_pos_3d[2][j]]

        self.run_callbacks(time)

        for key, j in zip(self.path_keys,
                          self.var_idxs_pos_3d_helper):
            self.scope_vars_3d[self.var_idxs_pos_3d[0][j]][self.var_idxs_pos_3d[1][j]][self.var_idxs_pos_3d[2][j]] \
                = self.path_variables[key]

    def get_derivatives_idx(self, idx_3d):
        return self.scope_vars_3d[idx_3d]

    def compute(self):
        if self.sum_mapping:
            sum_mappings(self.sum_idxs_pos_3d, self.sum_idxs_sum_3d,
                         self.sum_slice_idxs, self.scope_vars_3d, self.sum_slice_idxs_len)

        mapping_ = True
        prev_scope_vars_3d = self.scope_vars_3d.copy()
        iter=0
        while mapping_:
            iter+=1



            for i in range(self.number_of_mappings):
                self.scope_vars_3d[self.differing_idxs_pos_3d[0][i]][self.differing_idxs_pos_3d[1][i]][
                    self.differing_idxs_pos_3d[2][i]] = self.scope_vars_3d[
                    self.differing_idxs_from_3d[0][i]][self.differing_idxs_from_3d[1][i]][
                    self.differing_idxs_from_3d[2][i]]

            self.compute_eq(self.scope_vars_3d)

            if self.sum_mapping:
                sum_mappings(self.sum_idxs_pos_3d, self.sum_idxs_sum_3d,
                             self.sum_slice_idxs, self.scope_vars_3d, self.sum_slice_idxs_len)

            mapping_ = not np.all(np.abs(self.get_mapped_variables(prev_scope_vars_3d)
                                         - self.get_mapped_variables(self.scope_vars_3d)) < 1e-6)
            prev_scope_vars_3d = np.copy(self.scope_vars_3d)

        #print(iter)

    def func(self, _t, y):
        print('y: ')
        for di in y:
            print(di)
        # self.info["Number of Equation Calls"] += 1
        self.update_states(y)
        self.global_vars[0] = _t
        self.compute()
        y_dot = self.get_derivatives()
        print('y_dot: ')
        for di in y_dot:
            print(di)
        return y_dot


@njit
def sum_mappings(sum_idxs_pos_3d, sum_idxs_sum_3d,
                 sum_slice_idxs, scope_vars_3d, sum_slice_idxs_len):
    idx_sum = 0
    for i, len_ in enumerate(sum_slice_idxs_len):
        sum_ = 0
        for j in sum_slice_idxs[idx_sum:idx_sum + len_]:
            sum_ += scope_vars_3d[sum_idxs_sum_3d[0][j]][sum_idxs_sum_3d[1][j]][sum_idxs_sum_3d[2][j]]
        idx_sum += len_
        scope_vars_3d[sum_idxs_pos_3d[0][i]][sum_idxs_pos_3d[1][i]][sum_idxs_pos_3d[2][i]] = sum_
