'''
Auxiliary Objects Module
'''
import logging
from typing import Any, Tuple, Union, List, Set, Dict
from java_wrapper import apron, java


class VariableRegistry(object):
    '''
    Class representing a variable registry to store variables and
    assign them IDs to recognize
    '''

    def __init__(self):
        self.variable_table = dict()
        self.variable_count = 0

    def register_variable(self, variable: str, stateVariable: bool = False,
                          value: Union[apron.Interval, Tuple[int, int], None] = None,
                          constant_registry=None) -> dict:
        '''
        Register a variable, define whether it's a state variable, and return its identifier.
        '''
        if variable not in self.variable_table:
            self.variable_table[variable] = {
                'id': self.variable_count,
                'name': variable,
                'stateVariable': stateVariable,
                'value': value
            }
            self.variable_count += 1
        return self.variable_table[variable]

    def get_id(self, variable: str) -> int:
        '''Get the identifier of a variable'''
        var_id = self.variable_table[variable]['id'] if variable in self.variable_table else -1
        logging.debug(f"[GET_ID] Retrieved ID {var_id} for variable '{variable}'")
        return var_id

    def get_value(self, variable: str) -> Union[apron.Interval, apron.MpqScalar]:
        '''Get the value of a variable'''
        if variable not in self.variable_table:
            raise Exception(f'Variable {variable} not registered!')
        value = self.variable_table[variable]['value']
        logging.debug(f"[GET_VALUE] Retrieved value {value} for variable '{variable}'")
        return value

    def set_value(self, variable: str, value: Union[apron.Interval, apron.MpqScalar]) -> None:
        '''Set the value of a variable'''
        if variable not in self.variable_table:
            raise Exception(f'Variable {variable} not registered!')
        self.variable_table[variable]['value'] = value
        logging.debug(f"[SET_VALUE] Set value {value} for variable '{variable}'")

    def is_state_variable(self, variable: str) -> bool:
        '''Check if a variable is a state variable'''
        if variable not in self.variable_table:
            raise Exception(f'Variable {variable} not registered!')
        state_var = self.variable_table[variable]['stateVariable']
        logging.debug(f"[IS_STATE_VARIABLE] Variable '{variable}' is a state variable: {state_var}")
        return state_var


class PointState(object):
    '''
    Class representing the state of variables at a program point
    '''

    def __init__(self, _variable_registry: VariableRegistry, starting_node: str,
                 apron_manager: apron.Manager):
        self.variable_registry = _variable_registry
        self.starting_node = starting_node
        self.manager = apron_manager
        self.node_states = dict()
        self.iteration = 0

    def register_node(self, node_id: str) -> None:
        '''Register a node and initialize the state for entry and exit points'''
        if node_id in self.node_states:
            raise Exception(f"Node with id {node_id} already registered!")
        self.node_states[node_id] = {'entry': dict(), 'exit': dict()}
        self.node_states[node_id]['entry'][0] = None
        self.node_states[node_id]['exit'][0] = {'*': None}

    def init_node_states(self) -> None:
        '''Initialize node states to default/bottom values at iteration 0.'''
        for node_id in self.node_states:
            default_state = self.__generate_default_state_tuple() if node_id == self.starting_node \
                else self.__generate_bottom_state_tuple()

            if node_id != self.starting_node:
                for variable, details in self.variable_registry.variable_table.items():
                    if details['stateVariable']:
                        variable_id = details['id']
                        last_value = self.variable_registry.get_value(variable)
                        expr = apron.Tcons0.cst(last_value) if isinstance(last_value, apron.Interval) else last_value
                        default_state = default_state.assignCopy(self.manager, variable_id, expr, None)

            self.node_states[node_id]['entry'][0] = default_state
            self.node_states[node_id]['exit'][0] = {'*': default_state}

    def get_node_state_set(self, node_id: str, iteration: int, is_entry=True,
                           next_node='*', get_all=False) -> Union[apron.Abstract0, Dict[str, apron.Abstract0]]:
        '''Get the entry or exit state of a variable for a given node and iteration'''
        point = 'entry' if is_entry else 'exit'

        if node_id not in self.node_states:
            raise Exception(f"Node with id {node_id} is not registered!")
        if iteration not in self.node_states[node_id][point]:
            raise Exception(f"State for Iteration {iteration} is not available for node {node_id}!")

        if not is_entry:
            if get_all:
                return self.node_states[node_id][point][iteration]
            if next_node not in self.node_states[node_id][point][iteration]:
                if '*' in self.node_states[node_id][point][iteration]:
                    return self.node_states[node_id][point][iteration]['*']
                else:
                    # FIX: return bottom state instead of the raw dict
                    # to prevent dict propagation into abstract state joins
                    return self.__generate_bottom_state_tuple()
            else:
                return self.node_states[node_id][point][iteration][next_node]

        return self.node_states[node_id][point][iteration]

    def start_computation_round(self) -> None:
        '''Start the computation round by incrementing the iteration counter'''
        self.iteration += 1

    MAX_ITERATIONS = 50

    def is_fixed_point_reached(self) -> bool:
        if self.iteration < 1:
            return False
        if self.iteration >= self.MAX_ITERATIONS:
            return True
        for node_id in self.node_states:
            current_state = self.node_states[node_id]['entry'][self.iteration]
            prev_state = self.node_states[node_id]['entry'][self.iteration - 1]
            if prev_state is None:
                return False
            # FIX: current_state may be None if node not yet visited this round
            if current_state is None:
                return False
            if not current_state.isEqual(self.manager, prev_state):
                return False
        return True

    def update_node_entry_state(self, node_id: str, prev_nodes: List[str]) -> None:
        '''Update entry state for the current iteration of a given node.'''
        if node_id == self.starting_node:
            prev_nodes = list()

        prev_states = []
        for prev_node in prev_nodes:
            current_exit = (self.node_states
                            .get(prev_node, {})
                            .get('exit', {})
                            .get(self.iteration, {}))
            if node_id in current_exit:
                prev_state = current_exit[node_id]
            elif '*' in current_exit:
                prev_state = current_exit['*']
            else:
                prev_state = self.get_node_state_set(
                    prev_node, self.iteration - 1, is_entry=False, next_node=node_id)
            prev_states.append(prev_state)

        if len(prev_states) == 0:
            abs_state = self.node_states[node_id]['entry'][self.iteration - 1]
        else:
            # FIX: guard against None/dict states that can propagate from
            # get_node_state_set when a predecessor has not yet been visited
            abs_state = prev_states.pop()
            if abs_state is None or isinstance(abs_state, dict):
                abs_state = self.__generate_bottom_state_tuple()
            for state in prev_states:
                if state is None or isinstance(state, dict):
                    continue
                abs_state = abs_state.joinCopy(self.manager, state)

        if node_id.startswith("FunctionDefinition_"):
            exit_state_nodes = [k for k in self.node_states if k.startswith("FunctionExit_")]
            if exit_state_nodes:
                current_func_index = int(node_id.split('_')[-1])
                exit_candidates = [k for k in exit_state_nodes
                                   if int(k.split('_')[-1]) < current_func_index]
                if exit_candidates:
                    last_exit_id = sorted(exit_candidates, key=lambda x: int(x.split('_')[-1]))[-1]
                    exit_state = self.node_states[last_exit_id]['exit'].get(self.iteration)
                    if exit_state and '*' in exit_state:
                        abs_state = exit_state['*']

            intervals = abs_state.toBox(self.manager)
            for variable, details in self.variable_registry.variable_table.items():
                if not details.get('stateVariable', False):
                    variable_id = details['id']
                    intervals[variable_id] = apron.Interval()
            abs_state = apron.Abstract0(self.manager, len(intervals), 0, intervals)

        is_loop_back_edge = (node_id.startswith("ForLoopJoin_")
                             or node_id.startswith("ForLoopContinue_")
                             or node_id.startswith("ForStatement_"))
        if not is_loop_back_edge:
            for variable, details in self.variable_registry.variable_table.items():
                if details.get('stateVariable', False):
                    variable_id = details['id']
                    current_interval = abs_state.getBound(
                        self.manager, apron.Texpr0Intern(apron.Texpr0DimNode(variable_id))
                    )
                    if current_interval.isTop():
                        abs_state = abs_state.assignCopy(
                            self.manager, variable_id,
                            apron.Texpr0Intern(apron.Texpr0DimNode(variable_id)), None)

        if (node_id.startswith("ForLoopJoin_") or node_id.startswith("ForLoopContinue_")):
            prev_entry = self.node_states[node_id]['entry'].get(self.iteration - 1)
            if (prev_entry is not None
                    and not prev_entry.isBottom(self.manager)
                    and not abs_state.isBottom(self.manager)):
                abs_state = prev_entry.widening(self.manager, abs_state)

        self.node_states[node_id]['entry'][self.iteration] = abs_state
        logging.debug("ABSTATE %s", java.Arrays.toString(abs_state.toBox(self.manager)))

    def update_node_exit_state(self, node_id: str, next_node_id: str,
                               exit_state: apron.Abstract0) -> None:
        '''Update exit state for the current iteration of a given node.'''
        if self.iteration not in self.node_states[node_id]['exit']:
            self.node_states[node_id]['exit'][self.iteration] = dict()
        self.node_states[node_id]['exit'][self.iteration][next_node_id] = exit_state

    def __generate_default_state_tuple(self) -> Tuple[Any]:
        '''Generate the initial abstract state tuple'''
        variables = list(self.variable_registry.variable_table.keys())
        int_variables_count = len(variables)
        box_state = apron.Interval[int_variables_count]
        for i in range(int_variables_count):
            box_state[i] = apron.Interval()
        return apron.Abstract0(self.manager, int_variables_count, 0, box_state)

    def __generate_bottom_state_tuple(self) -> Tuple[Any]:
        '''Generate the initial bottom abstract state tuple'''
        variables = list(self.variable_registry.variable_table.keys())
        int_variables_count = len(variables)
        box_state = apron.Interval[int_variables_count]
        for i in range(int_variables_count):
            box_state[i] = apron.Interval()
            box_state[i].setBottom()
        return apron.Abstract0(self.manager, int_variables_count, 0, box_state)