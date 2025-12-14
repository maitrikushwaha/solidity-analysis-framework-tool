from control_flow_graph.node_processor import Node

class Throw(Node):
    def __init__(self, ast_node, entry_node, cfg_id, parent=None, cfg_metadata=None):
        super(Throw, self).__init__(ast_node, entry_node, cfg_id, parent, cfg_metadata)
        self.node_type = "Throw"

        # Correctly register this node
        self.cfg_id = cfg_metadata.register_node(self, self.node_type)

    def get_leaf_nodes(self):
        return {self.cfg_id}
