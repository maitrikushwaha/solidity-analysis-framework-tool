'''
Generic skip-node classes for Solidity AST node types that appear
at the contract level but do not contribute to intra-procedural
control / data flow (events, errors, modifiers, using-for, etc.).

Each class registers itself properly so lookups never return None,
but has no control-flow children.
'''
from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import BasicBlockTypes
from control_flow_graph.node_processor import Node


def _make_skip_node_class(class_name):
    """Factory that produces a minimal registered Node subclass."""

    class SkipNode(Node):
        __qualname__ = class_name

        def __init__(self, ast_node, entry_node_id, prev_node_id,
                     exit_node_id, cfg_metadata):
            super().__init__(ast_node, entry_node_id, prev_node_id,
                             exit_node_id, cfg_metadata)
            self.basic_block_type = BasicBlockTypes.Statement
            self.node_type = class_name
            self.add_prev_node(prev_node_id)
            self.cfg_id = cfg_metadata.register_node(self, self.node_type)
            self.leaves.add(self.cfg_id)

        def get_leaf_nodes(self):
            child_leaves = set()
            for nid in self.next_nodes:
                n = self.cfg_metadata.get_node(nid)
                if n is not None:
                    child_leaves.update(n.get_leaf_nodes())
            if child_leaves:
                self.leaves = set(child_leaves)
            return self.leaves

        def get_whois_next_node(self):
            return self.cfg_id

    SkipNode.__name__ = class_name
    return SkipNode


# ---- Contract-level declarations ----
EventDefinition     = _make_skip_node_class('EventDefinition')
ErrorDefinition     = _make_skip_node_class('ErrorDefinition')
ModifierDefinition  = _make_skip_node_class('ModifierDefinition')
UsingForDirective   = _make_skip_node_class('UsingForDirective')

# ---- Statement-level nodes (modern Solidity) ----
PlaceholderStatement = _make_skip_node_class('PlaceholderStatement')
InlineAssembly       = _make_skip_node_class('InlineAssembly')
BreakStatement       = _make_skip_node_class('BreakStatement')
ContinueStatement    = _make_skip_node_class('ContinueStatement')