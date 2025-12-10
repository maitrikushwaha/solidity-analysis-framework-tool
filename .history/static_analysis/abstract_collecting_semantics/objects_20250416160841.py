'''
Auxiliary Objects Module
'''
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

    
    def register_variable(self, variable: str, stateVariable: bool = False, value: Union[apron.Interval, Tuple[int, int], None] = None, constant_registry=None) -> dict:
        '''
        Register a variable, define whether it's a state variable (True or False), and return its identifier.
        If the value is a tuple, convert it to apron.Interval.
        '''
        
        if variable not in self.variable_table:
            self.variable_table[variable] = {
                'id': self.variable_count,
                'name': variable,
                'stateVariable': stateVariable,
                'value': value
            }
            # print(f"[REGISTER] Variable '{variable}' registered with ID {self.variable_count}, "
            #     f"State Variable: {stateVariable}, Initial Value: {value}")
            self.variable_count += 1
        else:
            existing_var = self.variable_table[variable]
            # print(f"[REGISTER] Variable '{variable}' already registered with ID {existing_var['id']}, "
            #     f"State Variable: {existing_var['stateVariable']}, Current Value: {existing_var['value']}")
            
        # Print the entire variable registry after each registration
        # print("[VARIABLE REGISTRY STATE] Current variable registry:")
        # for var, details in self.variable_table.items():
        #     print(f"  Variable: {var}, Details: {details}")

        return self.variable_table[variable]


    def get_id(self, variable: str) -> int:
        '''
        Get the identifier of a variable
        '''
        var_id = self.variable_table[variable]['id'] if variable in self.variable_table else -1
        print(f"[GET_ID] Retrieved ID {var_id} for variable '{variable}'")
        return var_id

    def get_value(self, variable: str) -> Union[apron.Interval, apron.MpqScalar]:
        '''
        Get the value of a variable
        '''
        if variable not in self.variable_table:
            raise Exception(f'Variable {variable} not registered!')
        value = self.variable_table[variable]['value']
        print(f"[GET_VALUE] Retrieved value {value} for variable '{variable}'")
        return value

    def set_value(self, variable: str, value: Union[apron.Interval, apron.MpqScalar]) -> None:
        '''
        Set the value of a variable
        '''
        if variable not in self.variable_table:
            raise Exception(f'Variable {variable} not registered!')
        self.variable_table[variable]['value'] = value
        print(f"[SET_VALUE] Set value {value} for variable '{variable}'")

        # Print the entire variable registry after updating a value
        print("[VARIABLE REGISTRY STATE] Current variable registry:")
        for var, details in self.variable_table.items():
            print(f"  Variable: {var}, Details: {details}")


    def is_state_variable(self, variable: str) -> bool:
        '''
        Check if a variable is a state variable (True or False)
        '''
        if variable not in self.variable_table:
            raise Exception(f'Variable {variable} not registered!')
        state_var = self.variable_table[variable]['stateVariable']
        print(f"[IS_STATE_VARIABLE] Variable '{variable}' is a state variable: {state_var}")
        return state_var


class PointState(object):
    '''
    Class representing the state of variables at a program point
    '''

    def __init__(self, _variable_registry: VariableRegistry, starting_node: str, apron_manager: apron.Manager):  # type: ignore
        # also reference the variable registry
        self.variable_registry = _variable_registry
        self.starting_node = starting_node

        # init the APRON manager as the Box, i.e., the Interval Domain
        self.manager = apron_manager

        # variable to store the states of a particular node in the cfg
        self.node_states = dict()

        # the iteration counter variable to keep record of the iterations taken
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
        self.node_states[node_id]['entry'][0] = None
        # in case of exit, we need to have different state sets for each of the next nodes
        # this is why, we include a dictionary of next_node_id -> state_set
        # in this case, if we don't need to specify a next node, we use the wildcard '*'
        self.node_states[node_id]['exit'][0] = {'*': None}

        # print(f"[REGISTER_NODE] Node '{node_id}' registered with initial entry and exit states.")

    def init_node_states(self) -> None:
        '''
        Initialize the node states to default values or the bottom state at the 0th iteration.
        Global variables retain their previous values across nodes.
        '''
        for node_id in self.node_states:
            # Set default state as initial or bottom based on starting node
            default_state = self.__generate_default_state_tuple() if node_id == self.starting_node \
                else self.__generate_bottom_state_tuple()

            # Retain global variable values if not the starting node, without overwriting local updates
            if node_id != self.starting_node:
                for variable, details in self.variable_registry.variable_table.items():
                    if details['stateVariable']:
                        # Retrieve the ID and last value of the global variable
                        variable_id = details['id']
                        last_value = self.variable_registry.get_value(variable)
                        # Prepare constant expression based on last value type
                        expr = apron.Tcons0.cst(last_value) if isinstance(last_value, apron.Interval) else last_value
                        # Set the global variable's value, ensuring it doesn’t overwrite node-specific updates
                        default_state = default_state.assignCopy(self.manager, variable_id, expr, None)

            # Set entry and exit points for each node
            self.node_states[node_id]['entry'][0] = default_state
            self.node_states[node_id]['exit'][0] = {'*': default_state}

            # Output initialization details for tracking
            # print(f"[INIT_NODE_STATES] Node '{node_id}' initialized with default state.")

        # Print the full state of the variable registry after initialization
        # print("[VARIABLE REGISTRY STATE] Current variable registry after node initialization:")
        # for var, details in self.variable_registry.variable_table.items():
        #     print(f"  Variable: {var}, Details: {details}")

    def get_node_state_set(self, node_id: str, iteration: int, is_entry=True, next_node='*', get_all=False) -> Union[apron.Abstract0, Dict[str, apron.Abstract0]]:
        '''
        Get the entry or exit state of a variable for a given node and iteration
        '''
        point = 'entry' if is_entry else 'exit'

        if node_id not in self.node_states:
            raise Exception(f"Node with id {node_id} is not registered!")

        if iteration not in self.node_states[node_id][point]:
            raise Exception(
                f"State for Iteration {iteration} is not available for node {node_id}!")

        # for exit states, we need to also include the next node for which we fetch the exit node
        if not is_entry:
            if get_all:
                # print(f"[GET_NODE_STATE_SET] Retrieved all exit states for node '{node_id}' at iteration {iteration}.")
                return self.node_states[node_id][point][iteration]
            # print(f"[GET_NODE_STATE_SET] Retrieved exit state for node '{node_id}' at iteration {iteration}: {self.node_states[node_id][point][iteration]}")
            if next_node not in self.node_states[node_id][point][iteration]:
                if '*' in self.node_states[node_id][point][iteration]:
                    return self.node_states[node_id][point][iteration]['*']
                else:
                    return self.node_states[node_id][point][iteration]
            else:
                return self.node_states[node_id][point][iteration][next_node]

        # print(f"[GET_NODE_STATE_SET] Retrieved entry state for node '{node_id}' at iteration {iteration}: {self.node_states[node_id][point][iteration]}")
        return self.node_states[node_id][point][iteration]

    def start_computation_round(self) -> None:
        '''
        Start the computation round by incrementing the iteration counter
        '''
        self.iteration += 1
        # print(f"[COMPUTATION_ROUND] Starting computation round {self.iteration}.")

    def is_fixed_point_reached(self) -> bool:
        '''
        Check if the fixed point is reached or not
        '''
        # base case
        # if the iteration is 0, return False
        if self.iteration < 1:
            # print("[FIXED_POINT] Iteration less than 1, fixed point not reached.")
            return False

        # iterate over all the nodes, and check their exit states
        for node_id in self.node_states:
            current_state = self.node_states[node_id]['entry'][self.iteration]
            prev_state = self.node_states[node_id]['entry'][self.iteration - 1]

            # EDGE CASE: prev state is None
            if prev_state is None:
                # print(f"[FIXED_POINT] Previous state for node '{node_id}' is None.")
                return False

            # if the current state is not equal to the previous state,
            # then the fixed point has not been reached
            # in this case we use the apron method isEqual to check the similarity
            if not current_state.isEqual(self.manager, prev_state):
                # print(f"[FIXED_POINT] Fixed point not reached for node '{node_id}'.")
                return False

        # if everything passes, return True
        # print("[FIXED_POINT] Fixed point reached.")
        return True

    def update_node_entry_state(self, node_id: str, prev_nodes: List[str]) -> None:
        '''
        Update state ordered-pair for the current iteration
        of a given node at its entry point.
        Global variables retain their previous state across nodes.
        '''
        if node_id == self.starting_node:
            prev_nodes = list()

        prev_states = []
        for prev_node in prev_nodes:
            prev_state = self.get_node_state_set(
                prev_node, self.iteration - 1, is_entry=False, next_node=node_id)
            prev_states.append(prev_state)

        # Determine the abstract state by joining the previous states
        if len(prev_states) == 0:
            abs_state = self.node_states[node_id]['entry'][self.iteration - 1]
        else:
            abs_state = prev_states.pop()
            for state in prev_states:
                abs_state = abs_state.joinCopy(self.manager, state)

        # 🔁 If this is a FunctionDefinition node, override entry state from last FunctionExit
        if node_id.startswith("FunctionDefinition_"):
            exit_state_nodes = [k for k in self.node_states if k.startswith("FunctionExit_")]
            if exit_state_nodes:
                current_func_index = int(node_id.split('_')[-1])
                exit_candidates = [k for k in exit_state_nodes if int(k.split('_')[-1]) < current_func_index]
                if exit_candidates:
                    last_exit_id = sorted(exit_candidates, key=lambda x: int(x.split('_')[-1]))[-1]
                    exit_state = self.node_states[last_exit_id]['exit'].get(self.iteration)
                    if exit_state and '*' in exit_state:
                        abs_state = exit_state['*']

            # ✅ After importing previous function’s state, clear local (non-state) variables
            intervals = abs_state.toBox(self.manager)
            for variable, details in self.variable_registry.variable_table.items():
                if not details.get('stateVariable', False):
                    variable_id = details['id']
                    intervals[variable_id] = apron.Interval()
            abs_state = apron.Abstract0(self.manager, len(intervals), 0, intervals)
        
        # ✅ Reinject state variables if they are still Top
        for variable, details in self.variable_registry.variable_table.items():
            if details.get('stateVariable', False):
                variable_id = details['id']
                current_interval = abs_state.getBound(
                    self.manager, apron.Texpr0Intern(apron.Texpr0DimNode(variable_id))
                )
                if current_interval.isTop():
                    last_value = self.variable_registry.get_value(variable)
                    expr = last_value if not isinstance(last_value, apron.Interval) \
                        else apron.Tcons0.cst(last_value)  # May need alternate wrapper if error occurs
                    abs_state = abs_state.assignCopy(self.manager, variable_id, apron.Texpr0Intern(apron.Texpr0DimNode(variable_id)), None)

        # Store the updated entry state
        self.node_states[node_id]['entry'][self.iteration] = abs_state

        # Print for debugging
        print("ABSTATE", java.Arrays.toString(abs_state.toBox(self.manager)))
   
    def update_node_exit_state(self, node_id: str, next_node_id: str, exit_state: apron.Abstract0) -> None:
        '''
        Update state for the current iteration
        of a given node at its exit point.
        This exit set might be different for different next nodes of the node
        '''
        # check if the dictionary for the current iteration is initialized or not
        if self.iteration not in self.node_states[node_id]['exit']:
            self.node_states[node_id]['exit'][self.iteration] = dict()

        # write the exit state set for the next node at the current iteration
        self.node_states[node_id]['exit'][self.iteration][next_node_id] = exit_state

        # print(f"[UPDATE_NODE_EXIT] Node '{node_id}' exit state updated for next node '{next_node_id}' at iteration {self.iteration}: {exit_state.toBox(self.manager)}")

        # Print the entire variable registry whenever a node exit state is updated
        # print("[VARIABLE REGISTRY STATE] Current variable registry after exit update:")
        # for var, details in self.variable_registry.variable_table.items():
        #     print(f"  Variable: {var}, Details: {details}")
    
    def __generate_default_state_tuple(self) -> Tuple[Any]:
        '''
        Generate the initial abstract state tuple based on
        the variables present in the variable registry
        '''
        # obtain the variable names and init the state tuple
        variables = list(self.variable_registry.variable_table.keys())
        int_variables_count = len(variables)
        real_variables_count = 0

        # init the Interval for every variable
        box_state = apron.Interval[int_variables_count]
        for i in range(int_variables_count):
            box_state[i] = apron.Interval()
            # box_state[i].setBottom()

        # generate the level 0 abstract state
        state = apron.Abstract0(self.manager, int_variables_count,
                                real_variables_count, box_state)

        # print(f"[GENERATE_DEFAULT_STATE] Generated default state tuple for iteration 0: {state.toBox(self.manager)}")
        return state

    def __generate_bottom_state_tuple(self) -> Tuple[Any]:
        '''
        Generate the initial abstract state (a bottom state) tuple based on
        the variables present in the variable registry
        '''
        # obtain the variable names and init the state tuple
        variables = list(self.variable_registry.variable_table.keys())
        int_variables_count = len(variables)
        real_variables_count = 0

        # init the Interval for every variable
        box_state = apron.Interval[int_variables_count]
        for i in range(int_variables_count):
            box_state[i] = apron.Interval()
            box_state[i].setBottom()

        # generate the level 0 abstract state
        state = apron.Abstract0(self.manager, int_variables_count,
                                real_variables_count, box_state)

        # print(f"[GENERATE_BOTTOM_STATE] Generated bottom state tuple for node '{self.starting_node}': {state.toBox(self.manager)}")
        return state  