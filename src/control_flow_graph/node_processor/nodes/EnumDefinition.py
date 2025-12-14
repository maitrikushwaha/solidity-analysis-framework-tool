'''
Class definition for the EnumDefinition CFG (AST) node
'''
from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import BasicBlockTypes
from control_flow_graph.node_processor import Node

class EnumDefinition(Node):
    '''
    EnumDefinition Node
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata: CFGMetadata):
        '''
        Constructor
        '''
        super(EnumDefinition, self).__init__(ast_node, entry_node_id, prev_node_id,
                                             exit_node_id, cfg_metadata)

        # set the basic block type and node type
        self.basic_block_type = BasicBlockTypes.Statement
        self.node_type = 'EnumDefinition'

        # link the previous node to indexing
        self.add_prev_node(prev_node_id)

        # register the node to the CFG Metadata store
        self.cfg_id = cfg_metadata.register_node(self, self.node_type)

        # Specific fields from EnumDefinition
        self.canonicalName = ast_node.get('canonicalName', "")
        self.documentation = ast_node.get('documentation', None)
        self.name = ast_node.get('name', "")
        self.members = ast_node.get('members', [])  # List of EnumValue nodes

        # Enum members are simple names; no need to parse children
        self.member_names = [member['name'] for member in self.members]

        print(f'Processing CFG Node {self.cfg_id} ({self.name}): {{{", ".join(self.member_names)}}}')
        
        # add self as a leaf node
        self.leaves.add(self.cfg_id)

    def get_leaf_nodes(self) -> set:
        '''
        Returns the leaf node(s) in the current branch
        '''
        return self.leaves
