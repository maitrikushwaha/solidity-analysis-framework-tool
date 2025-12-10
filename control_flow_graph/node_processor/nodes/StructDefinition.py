'''
Class definition for the StructDefinition CFG (AST) node
'''

from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import BasicBlockTypes
from control_flow_graph.node_processor import Node

class StructDefinition(Node):
    '''
    StructDefinition Node
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata: CFGMetadata):
        '''
        Constructor
        '''
        super(StructDefinition, self).__init__(ast_node, entry_node_id, prev_node_id,
                                               exit_node_id, cfg_metadata)

        # set the basic block type and node type
        self.basic_block_type = BasicBlockTypes.Statement
        self.node_type = 'StructDefinition'

        # link the previous node to indexing
        self.add_prev_node(prev_node_id)

        # register the node
        self.cfg_id = cfg_metadata.register_node(self, self.node_type)

        # Specific fields for Struct
        self.canonicalName = ast_node.get('canonicalName', "")
        self.documentation = ast_node.get('documentation', None)
        self.name = ast_node.get('name', "")
        self.members = ast_node.get('members', [])  # List of VariableDeclaration objects
        self.visibility = ast_node.get('visibility', "internal")

        self.member_names = [member.get('name', 'unknown') for member in self.members]

        print(f'Processing CFG Node {self.cfg_id} (Struct {self.name}): {{{", ".join(self.member_names)}}}')

        # add self as a leaf node
        self.leaves.add(self.cfg_id)

    def get_leaf_nodes(self) -> set:
        '''
        Return the leaf node(s) for this Struct node
        '''
        return self.leaves
