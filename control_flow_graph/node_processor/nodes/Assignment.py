'''
Class definition for the Assignment CFG (AST) node
'''
from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import BasicBlockTypes
from control_flow_graph.node_processor import Node
import control_flow_graph.node_processor.nodes as nodes


class Assignment(Node):
    '''
    Assignment Node
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata: CFGMetadata):
        '''
        Constructor
        '''
        super(Assignment, self).__init__(ast_node, entry_node_id, prev_node_id,
                                         exit_node_id, cfg_metadata)

        # set the basic block type and node type
        self.basic_block_type = BasicBlockTypes.Statement
        self.node_type = 'Assignment'

        # link the previous node to indexing
        self.add_prev_node(prev_node_id)

        # register the node to the CFG Metadata store and
        # obtain a CFG ID of the form f'{node_type}_{n}'
        self.cfg_id = cfg_metadata.register_node(self, self.node_type)

        print(f'Processing CFG Node {self.cfg_id}')

        # node specific metadata
        self.argumentTypes = ast_node.get('argumentTypes', None)
        self.hexValue = ast_node.get('hexValue', None)
        self.isConstant = ast_node.get('isConstant', None)
        self.isLValue = ast_node.get('isLValue', None)
        self.isPure = ast_node.get('isPure', None)
        self.lValueRequested = ast_node.get('lValueRequested', None)
        self.operator = ast_node.get('operator', None)
        self.typeDescriptions = ast_node.get('typeDescriptions', dict())

        self.leftHandSide = ast_node.get('leftHandSide', None)
        self.leftHandSide = getattr(nodes, self.leftHandSide['nodeType'], Node)(
            self.leftHandSide, None, None, None, self.cfg_metadata)

        self.rightHandSide = ast_node.get('rightHandSide', None)
        self.rightHandSide = getattr(nodes, self.rightHandSide['nodeType'], Node)(
            self.rightHandSide, None, None, None, self.cfg_metadata)

        # add self as a leaf node (because this node does not have any children)
        self.leaves.add(self.cfg_id)

    def get_leaf_nodes(self) -> set:
        '''
        Returns the leaf node(a) in the current branch,
        where the current node is the root node 
        '''

        return self.leaves
