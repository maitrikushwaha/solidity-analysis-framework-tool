'''
Auxiliary Objects Module
'''
from typing import Any, Tuple, Union, List, Set, Dict
from enum import Enum

class VariableRegistry(object):
    '''
    Class representing a variable registry to store variables and
    assign them IDs to recognize
    '''

    def __init__(self):
        self.variable_table = dict()
        self.variable_count = 0

    def  register_variable(self, variable: str, stateVariable: bool = False, value: Union[Tuple[int, int], None] = None, constant_registry=None) -> dict:
        '''
        Register a variable, define whether it's a state variable (True or False), and return its identifier
        '''

        if variable not in self.variable_table:
            self.variable_table[variable] = {
                'id': self.variable_count,
                'name': variable,
                'stateVariable': stateVariable,  # Adding the stateVariable field
                'value': value
            }
            self.variable_count += 1
            print(f"[REGISTER] Variable '{variable}' registered with ID {self.variable_count}, "
                  f"State Variable: {stateVariable}, Initial Value: {value}")
        else:
            existing_var = self.variable_table[variable]
            print(f"[REGISTER] Variable '{variable}' already registered with ID {existing_var['id']}, "
                  f"State Variable: {existing_var['stateVariable']}, Current Value: {existing_var['value']}")

        return self.variable_table[variable]

    def get_id(self, variable: str) -> int:
        '''
        Get the identifier of a variable
        '''

        var_id = self.variable_table[variable]['id'] if variable in self.variable_table else -1
        print(f"[GET_ID] Retrieved ID {var_id} for variable '{variable}'")
        return var_id

    def get_value(self, variable: str) -> Any:
        '''
        Get the value of a variable
        '''

        if variable not in self.variable_table:
            raise Exception(f'Variable {variable} not registered!')

        value = self.variable_table[variable]['value']
        print(f"[GET_VALUE] Retrieved value {value} for variable '{variable}'")
        return value

    def set_value(self, variable: str, value: Any) -> None:
        '''
        Set the value of a variable
        '''

        if variable not in self.variable_table:
            raise Exception(f'Variable {variable} not registered!')

        self.variable_table[variable]['value'] = value
        print(f"[SET_VALUE] Set value {value} for variable '{variable}'")

    def is_state_variable(self, variable: str) -> bool:
        '''
        Check if a variable is a state variable (True or False)
        '''

        if variable not in self.variable_table:
            raise Exception(f'Variable {variable} not registered!')

        state_var = self.variable_table[variable]['stateVariable']
        print(f"[IS_STATE_VARIABLE] Variable '{variable}' is a state variable: {state_var}")
        return state_var


class NumericalDomain(Enum):
    '''
    Numerical Domain Lattice Class
    '''

    Top = 'Top'
    Bottom = 'Bottom'


class PointState(object):
    '''
    Class representing the state of variables at a program point
    '''

    def __init__(self, _variable_registry: VariableRegistry, starting_node: str):
        # also reference the variable registry
        self.variable_registry = _variable_registry
        self.starting_node = starting_node

        # variable to store the states of a particular node in the cfg
        self.node_states = dict()

        # the iteration counter variable to keep track of the iterations taken
        self.iteration = 0

    def register_node(self, node_id: str) -> None:
        '''
        Register a node and initialize the state
        for the entry and exit points of the node
        '''

        # if the node is already registered, raise an exception
        if node_id in self.node_states:
            raise Exception(f"Node with id {node_id} already registered!")

        # init the state table
        self.node_states[node_id] = {
            'entry': dict(),
            'exit': dict()
        }

        # initialize the state table for the entry and exit points
        self.node_states[node_id]['entry'][0] = set()
        # in case of exit, we need to have different state sets for each of the next nodes
        # this is why we include a dictionary of next_node_id -> state_set
        # in this case, if we don't need to specify a next node, we use the wildcard '*'
        self.node_states[node_id]['exit'][0] = {'*': set()}

    def get_node_state_set(self, node_id: str, iteration: int, is_entry=True, next_node='*') -> Union[Set[Tuple[int]], Dict[str, Set[Tuple[int]]]]:
        '''
        Get the entry or exit state for a given node at a specific iteration
        '''

        point = 'entry' if is_entry else 'exit'

        if node_id not in self.node_states:
            raise Exception(f"Node with id {node_id} is not registered!")

        if iteration not in self.node_states[node_id][point]:
            raise Exception(f"State for Iteration {iteration} is not available for node {node_id}!")

        if not is_entry:
            if next_node not in self.node_states[node_id][point][iteration]:
                if '*' in self.node_states[node_id][point][iteration]:
                    return self.node_states[node_id][point][iteration]['*']
                else:
                    return self.node_states[node_id][point][iteration]
            else:
                return self.node_states[node_id][point][iteration][next_node]

        return self.node_states[node_id][point][iteration]

    def start_computation_round(self) -> None:
        '''
        Start the computation round by incrementing the iteration counter
        '''

        self.iteration += 1

    def is_fixed_point_reached(self) -> bool:
        '''
        Check if the fixed point is reached or not
        '''

        if self.iteration < 1:
            return False

        # iterate over all the nodes and check their entry states
        for node_id in self.node_states:
            current_state = self.node_states[node_id]['entry'][self.iteration]
            prev_state = self.node_states[node_id]['entry'][self.iteration - 1]

            if current_state != prev_state:
                return False

        return True

    def update_node_entry_state(self, node_id: str, prev_nodes: List[str]) -> None:
        '''
        Update state ordered-pair for the current iteration
        of a given node at its entry point.
        '''

        # edge case: node is the starting node
        if node_id == self.starting_node:
            self.__init_start_node(node_id)
            return

        prev_states = [self.get_node_state_set(prev_node, self.iteration - 1, is_entry=False, next_node=node_id)
                       for prev_node in prev_nodes]

        self.node_states[node_id]['entry'][self.iteration] = set.union(*prev_states)

    def update_node_exit_state(self, node_id: str, next_node_id: str, exit_state_set: Set[Tuple[Any]]) -> None:
        '''
        Update state ordered-pair for the current iteration
        of a given node at its exit point.
        This exit set might be different for different next nodes of the node
        '''

        if self.iteration not in self.node_states[node_id]['exit']:
            self.node_states[node_id]['exit'][self.iteration] = dict()

        self.node_states[node_id]['exit'][self.iteration][next_node_id] = exit_state_set

    def __init_start_node(self, node_id: str) -> None:
        '''
        Initialize the state of the Start Node (from where the CFG begins)
        '''

        state_tuple_set = set()
        state_tuple_set.add(self.__generate_state_tuple())
        self.node_states[node_id]['entry'][self.iteration] = state_tuple_set

    def __generate_state_tuple(self) -> Tuple[Any]:
        '''
        Generate the initial state tuple based on
        the variables present in the variable registry
        '''
        variables = self.variable_registry.variable_table.keys()
        state_tuple = tuple('btm' for _ in variables)

        return state_tuple
