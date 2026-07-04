'''
The Collecting Semantics Analysis in the Interval Abstract Domain
'''
import logging
from java_wrapper import apron, java
from control_flow_graph import ControlFlowGraph
from static_analysis.abstract_collecting_semantics.objects import VariableRegistry, PointState
import static_analysis.abstract_collecting_semantics.builder as builder
from time import sleep
from control_flow_graph.node_processor.nodes.Return import Return
from control_flow_graph.node_processor.nodes.IfStatement import IfStatement


class AbstractCollectingSemanticsAnalysis(object):
    '''
    Class defining the collecting semantics analysis in multiple abstract domains.
    Supports Box (Interval), Octagon, and Polka (Polyhedra) domains.
    '''

    def __init__(self, cfg: ControlFlowGraph, starting_node: str, ending_node: str,
                 _java_class_path: str, _java_lib_path=None, domain_type="Box"):
        '''Constructor'''
        self.domain_type = domain_type
        if domain_type == "Box":
            self.manager = apron.Box()
        elif domain_type == "Polka":
            self.manager = apron.Polka(False)
        elif domain_type == "Octagon":
            self.manager = apron.Octagon()
        else:
            raise ValueError(f"Unsupported abstract domain: {domain_type}")

        logging.debug(f"Initialized analysis with {domain_type} abstract domain.")

        self.cfg = cfg
        self.starting_node = starting_node
        self.ending_node = ending_node

        self.variable_registry = VariableRegistry()
        self.constant_registry = VariableRegistry()
        self.point_state = PointState(
            self.variable_registry, self.starting_node, self.manager)

    def compute(self) -> None:
        '''Compute the collecting semantics analysis'''
        self.__compute_variables()

        # ENTRY/EXIT state output — captured by main.py via StringIO redirect
        # during reentrancy pipeline; kept as print() so the capture works.
        self.__compute_abstract_collecting_semantics()

        if self.domain_type == "Box":
            entry_function = lambda state: state.toBox(self.manager)
            exit_function  = lambda state: state.toBox(self.manager)
        else:
            entry_function = lambda state: state.toLincons(self.manager)
            exit_function  = lambda state: state.toLincons(self.manager)

        for i in range(1, self.point_state.iteration + 1):
            for node in self.point_state.node_states.keys():
                print('ENTRY', i, node, java.Arrays.toString(entry_function(
                    self.point_state.get_node_state_set(node, i, True)
                )))
                exit_state = self.point_state.get_node_state_set(node, i, False)
                if isinstance(exit_state, dict):
                    for key, value in exit_state.items():
                        print('EXIT', i, node, key, java.Arrays.toString(exit_function(value)))
                else:
                    print('EXIT', i, node, java.Arrays.toString(exit_function(exit_state)))

    def __compute_variables(self) -> None:
        '''Compute and enroll all variables present in the CFG'''
        visited = set()

        def traverse(node_id, visited: set, cfg: ControlFlowGraph):
            if node_id in visited:
                return
            visited.add(node_id)
            node = cfg.cfg_metadata.get_node(node_id)
            self.point_state.register_node(node_id)
            variables = builder.get_variables(node)
            if variables is None:  # some node handlers return None — skip gracefully
                variables = []
            for variable in variables:
                self.variable_registry.register_variable(variable)
            logging.debug("VARIABLE-REGISTRY %s %s", node_id, variables)
            if node_id != self.ending_node:
                for child_id in node.next_nodes:
                    child_node = cfg.cfg_metadata.get_node(child_id)
                    traverse(child_node.cfg_id, visited, cfg)

        traverse(self.starting_node, visited, self.cfg)
        self.point_state.init_node_states()

    def __compute_abstract_collecting_semantics(self) -> None:
        '''Compute the Collecting Semantics'''

        def traverse(node_id, visited: set, cfg: ControlFlowGraph):
            if node_id in visited:
                return
            visited.add(node_id)
            logging.debug("COLLSEM-TRV %s", node_id)
            node = cfg.cfg_metadata.get_node(node_id)
            prev_nodes = list(node.prev_nodes.keys())

            self.point_state.update_node_entry_state(node_id, prev_nodes)
            entry_set = self.point_state.get_node_state_set(
                node_id, self.point_state.iteration)
            exit_sets = self.point_state.get_node_state_set(
                node_id, self.point_state.iteration - 1, False, '*', True)

            if any(keyword in node_id for keyword in
                   ["IfConditionJoin", "FunctionExit", "FunctionDefinition",
                    "FunctionEntry", "Return"]):
                exit_sets = {'*': entry_set}
            else:
                exit_sets = builder.generate_exit_sets(
                    node, entry_set, exit_sets,
                    self.variable_registry, self.constant_registry, self.manager)

            for next_node_id, exit_set in exit_sets.items():
                self.point_state.update_node_exit_state(node_id, next_node_id, exit_set)

            if node_id != self.ending_node:
                for child_id in node.next_nodes:
                    child_node = cfg.cfg_metadata.get_node(child_id)
                    traverse(child_node.cfg_id, visited, cfg)

        while True:
            visited = set()
            self.point_state.start_computation_round()
            logging.debug("Start Iter: %d", self.point_state.iteration)
            traverse(self.starting_node, visited, self.cfg)
            sleep(0.2)
            if self.point_state.is_fixed_point_reached():
                break