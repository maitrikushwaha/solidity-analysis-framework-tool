'''
Class definition for the Variable Declaration CFG (AST) node
'''
from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import BasicBlockTypes
from control_flow_graph.node_processor import Node


class VariableDeclaration(Node):
    '''
    Variable Declaration Node
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata: CFGMetadata):
        '''
        Constructor
        '''
        super(VariableDeclaration, self).__init__(ast_node, entry_node_id, prev_node_id,
                                                  exit_node_id, cfg_metadata)

        # set the basic block type and node type
        self.basic_block_type = BasicBlockTypes.Statement
        self.node_type = 'VariableDeclaration'

        # link the previous node to indexing
        self.add_prev_node(prev_node_id)

        # register the node to the CFG Metadata store and
        # obtain a CFG ID of the form f'{node_type}_{n}'
        self.cfg_id = cfg_metadata.register_node(self, self.node_type)

        print(f'Processing CFG Node {self.cfg_id}')

        # node specific metadata
        self.constant = ast_node.get('constant', None)
        self.visibility = ast_node.get('visibility', None)
        self.value = ast_node.get('value', dict())
        self.typeName = ast_node.get('typeName', dict())
        self.typeDescriptions = ast_node.get('typeDescriptions', dict())
        self.storageLocation = ast_node.get('storageLocation', None)
        self.stateVariable = ast_node.get('stateVariable', None)
        self.name = ast_node.get('name', None)
        self.scope = ast_node.get('scope', None)

        # register the variable in the CFG Metadata
        cfg_metadata.register_variable(
            self.name, self.typeDescriptions['typeString'])
        
        # Debugging print statements
        print(f"VariableDeclaration Node: name={self.name}, stateVariable={self.stateVariable}, value={self.value}, scope={self.scope}")

        # add self as a leaf node (because this node does not have any children)
        self.leaves.add(self.cfg_id)

    def get_leaf_nodes(self) -> set:
        '''
        Returns the leaf node(a) in the current branch,
        where the current node is the root node 
        '''
        return self.leaves