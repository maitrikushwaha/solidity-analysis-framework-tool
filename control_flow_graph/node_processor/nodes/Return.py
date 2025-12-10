'''
Class definition for the Return CFG (AST) node
'''
from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import BasicBlockTypes
from control_flow_graph.node_processor import Node

class Return(Node):
    '''
    Return Node
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata: CFGMetadata):
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

        # Node-specific metadata
        # Expression being returned, if any
        self.return_expression = ast_node.get('expression', None)
        self.computed_return_expression = None

        # Log the return expression, if it exists
        if self.return_expression:
            self.process_return_expression()
        
        # Add this node as the next node for the previous node
        self.cfg_metadata.get_node(prev_node_id).add_next_node(self.cfg_id)

    def process_return_expression(self):
        '''
        Process the return expression if it exists
        '''
        print(f"Processing Return Expression for Node {self.cfg_id}")
        print(f"Return Expression: {self.return_expression}")

        # Example processing: you can directly store or process the expression here
        # Currently, just logging or processing within the class is sufficient
        # Any additional handling can be added here if needed

    def get_leaf_nodes(self) -> set:
        '''
        Return this node as the leaf node since it's an exit point
        '''
        return {self.cfg_id}
