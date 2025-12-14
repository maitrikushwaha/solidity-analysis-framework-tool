'''
Class definition for the Conditional (ternary) CFG (AST) node
'''
from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import BasicBlockTypes
from control_flow_graph.node_processor import Node
import control_flow_graph.node_processor.nodes as nodes


class Conditional(Node):
    '''
    Conditional (ternary) Node
    Example: z = (y > x) ? y : x;
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata: CFGMetadata):
        '''
        Constructor
        '''
        super(Conditional, self).__init__(ast_node, entry_node_id, prev_node_id,
                                          exit_node_id, cfg_metadata)

        # set the basic block type and node type
        self.basic_block_type = BasicBlockTypes.Statement
        self.node_type = 'Conditional'

        # link the previous node to indexing
        self.add_prev_node(prev_node_id)

        # register the node to the CFG Metadata store and get the ID
        self.cfg_id = cfg_metadata.register_node(self, self.node_type)

        print(f'Processing CFG Node {self.cfg_id}')

        # node specific metadata
        self.argumentTypes = ast_node.get('argumentTypes', None)
        self.isConstant = ast_node.get('isConstant', None)
        self.isLValue = ast_node.get('isLValue', None)
        self.isPure = ast_node.get('isPure', None)
        self.lValueRequested = ast_node.get('lValueRequested', None)
        self.typeDescriptions = ast_node.get('typeDescriptions', dict())

        # Parse condition
        self.condition = ast_node.get('condition', None)
        if self.condition:
            self.condition = getattr(nodes, self.condition['nodeType'], Node)(
                self.condition, None, None, None, self.cfg_metadata)

        # Parse trueExpression
        self.trueExpression = ast_node.get('trueExpression', None)
        if self.trueExpression:
            self.trueExpression = getattr(nodes, self.trueExpression['nodeType'], Node)(
                self.trueExpression, None, None, None, self.cfg_metadata)

        # Parse falseExpression
        self.falseExpression = ast_node.get('falseExpression', None)
        if self.falseExpression:
            self.falseExpression = getattr(nodes, self.falseExpression['nodeType'], Node)(
                self.falseExpression, None, None, None, self.cfg_metadata)

        # add self as a leaf node (no internal children beyond expressions)
        self.leaves.add(self.cfg_id)

    def get_leaf_nodes(self) -> set:
        '''
        Returns the leaf node(s) for this branch
        '''
        return self.leaves
