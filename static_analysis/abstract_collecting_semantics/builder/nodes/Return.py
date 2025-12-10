'''
Class definition for the Return CFG (AST) node
'''
from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import BasicBlockTypes
from control_flow_graph.node_processor import Node
from static_analysis.abstract_collecting_semantics.builder.common import Bottom
from static_analysis.abstract_collecting_semantics.builder.common import compute_expression_object
class Return(Node):
    '''
    Return Node
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata: CFGMetadata,
                 var_registry=None, const_registry=None, abstract_state=None, manager=None):
        '''
        Constructor
        '''
        super(Return, self).__init__(ast_node, entry_node_id, prev_node_id,
                                     exit_node_id, cfg_metadata)

        # Set the basic block type and node type
        self.basic_block_type = BasicBlockTypes.Exit
        self.node_type = 'Return'

        # Link the previous node to indexing
        self.add_prev_node(prev_node_id)

        # Register the node to the CFG Metadata store and
        # obtain a CFG ID of the form f'{node_type}_{n}'
        self.cfg_id = self.cfg_metadata.register_node(self, self.node_type)

        print(f'Processing CFG Node {self.cfg_id}')
        print("mk, this function 2 is running")
        # Node-specific metadata
        # Expression being returned, if any
        self.return_expression = ast_node.get('expression', None)
        self.computed_return_expression = None

        # Log the return expression, if it exists
        # if self.return_expression:
        #     self.process_return_expression()
        if self.return_expression and var_registry and const_registry and abstract_state and manager:
            self.process_return_expression(var_registry, const_registry, abstract_state, manager)

        # Add this node as the next node for the previous node
        self.cfg_metadata.get_node(prev_node_id).add_next_node(self.cfg_id)

    # def process_return_expression(self):
    #     '''
    #     Process the return expression if it exists
    #     '''
    #     print(f"Processing Return Expression for Node {self.cfg_id}")
    #     print(f"Return Expression: {self.return_expression}")

        # Example processing: you can directly store or process the expression here
        # Currently, just logging or processing within the class is sufficient
        # Any additional handling can be added here if needed
    def process_return_expression(self, var_registry, const_registry, abstract_state, manager):
        '''
        Process and compute the return expression if it exists.
        '''
        if not self.return_expression:
            print(f"No Return Expression for Node {self.cfg_id}")
            return

        try:
            # Compute the return expression
            computed_expression = compute_expression_object(
                self.return_expression, var_registry, const_registry, abstract_state, manager
            )

            if isinstance(computed_expression, Bottom):
                print(f"Return Expression for Node {self.cfg_id} resulted in Bottom state")
                self.computed_return_expression = Bottom()
            else:
                print(f"Computed Return Expression for Node {self.cfg_id}: {computed_expression}")
                self.computed_return_expression = computed_expression
        except Exception as e:
            print(f"Error processing return expression for Node {self.cfg_id}: {e}")
            self.computed_return_expression = Bottom()

    def get_leaf_nodes(self) -> set:
        '''
        Return this node as the leaf node since it's an exit point
        '''
        return {self.cfg_id}
