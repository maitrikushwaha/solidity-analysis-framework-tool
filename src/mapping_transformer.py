import re

def transform_mappings(solidity_source):
    """Transforms Solidity code by injecting BAL into contract declarations and modifying mappings."""
    solidity_source = re.sub(r'//[^\n]*', '', solidity_source)
    solidity_source = re.sub(r'/\*.*?\*/', '', solidity_source, flags=re.DOTALL)

    contract_declaration_pattern = re.compile(r'(contract\s+\w+\s*(?:is\s+[^{]*)?\s*{)')

    def inject_bal_variable(match):
        contract_declaration = match.group(1)
        injected_line = "   uint public BAL = 100;uint public attacker_bal = 10;\n"
        return f"{contract_declaration}\n{injected_line}"
    
    mapping_pattern = re.compile(
        r'mapping\s*\(\s*([\w\[\]]+)\s*=>\s*([\w\[\]]+)\s*\)\s*(public|private|internal)?\s*(\w+)\s*;'
    )

    def extract_struct_definitions(code):
        struct_pattern = re.compile(r'struct\s+(\w+)\s*{\s*([^}]+)\s*}')
        struct_definitions = {}
        for match in struct_pattern.finditer(code):
            struct_name = match.group(1)
            struct_body = match.group(2)
            attributes = re.findall(r'\b(\w+)\s+(\w+);', struct_body)
            struct_definitions[struct_name] = {attr[1]: attr[0] for attr in attributes}
        return struct_definitions 
    
    def replace_struct_references(code, struct_definitions):
        """Replace struct member access (e.g. acc.balance) with the flattened"""
        mapped_struct_names = set(
            vt for vt in mapping_types.values() if vt in struct_definitions
        )
        for struct_name in mapped_struct_names:
            attributes = struct_definitions[struct_name]
            for attr_name in attributes.keys():
                attribute_pattern = re.compile(rf'\b\w+\.{attr_name}\b')
                code = attribute_pattern.sub(attr_name, code)
        return code 

    def replace_mapping(match, struct_definitions):
        value_type = match.group(2)
        visibility = match.group(3) if match.group(3) else "public"
        mapping_name = match.group(4)
        
        if value_type in ["uint", "uint256", "uint8", "int"]:
            return f"{value_type} {visibility} {mapping_name} = 40;"
        elif value_type == "bool":
            return f"{value_type} {visibility} {mapping_name} = false;"
        elif value_type in struct_definitions:
            struct_attributes = struct_definitions[value_type]
            init_lines = []
            for attr_name, attr_type in struct_attributes.items():
                if attr_type.startswith("uint"):
                    init_value = "80"
                elif attr_type.startswith("int"):
                    init_value = "80"
                elif attr_type == "bool":
                    init_value = "false"
                elif value_type == "address":
                    return f"{value_type} {visibility} {mapping_name} = address(0);"
                elif attr_type == "string":
                    init_value = '"default"'
                elif attr_type == "address":
                    init_value = 'address(0)'
                else:
                    init_value = f"{attr_type}()"
                init_lines.append(f"{attr_type} {attr_name} = {init_value};  // from struct {value_type}")
            return "\n".join(init_lines)

        return f"// Unable to transform mapping for {mapping_name}"

    mapping_access_pattern = re.compile(r'(\w+)\s*\[([^\[\]]*(?:\[[^\[\]]*\])*[^\[\]]*)\]')

    mapping_names = []
    mapping_types = {}

    def replace_access(match):
        mapping_name = match.group(1)
        if mapping_name in mapping_names:
            return f"{mapping_name}"
        return match.group(0)

    sol08_tuple_call_pattern = re.compile(
        r'\(\s*bool\s+(\w+)\s*,\s*\)\s*=\s*([\w\.]+)\.call\{value\s*:\s*([\w\.]+)\}\s*\(\s*""\s*\)\s*;'
    )
    sol08_tuple_call_bytes_pattern = re.compile(
        r'\(\s*bool\s+(\w+)\s*,\s*(?:bytes\s+memory\s+\w+\s*)?\)\s*=\s*([\w\.]+)\.call\{value\s*:\s*([\w\.]+)\}\s*\(\s*""\s*\)\s*;'
    )

    sol08_tuple_call_data_pattern = re.compile(
        r'\(\s*bool\s+(\w+)\s*,\s*(?:bytes\s+memory\s+\w+\s*)?\)\s*=\s*([\w\.]+)\.call\{value\s*:\s*([\w\.]+)\}\s*\([^)]*\)\s*;'
    )
    sol08_payable_call_pattern = re.compile(
        r'\(\s*bool\s+(\w+)\s*,\s*(?:bytes\s+memory\s+\w+\s*)?\)\s*=\s*payable\(\s*([\w\.]+)\s*\)\.call\{value\s*:\s*([\w\.]+)\}\s*\([^)]*\)\s*;'
    )
    sol08_payable_transfer_pattern = re.compile(
        r'payable\(\s*([\w\.]+)\s*\)\.transfer\(\s*([\w\.]+)\s*\)\s*;'
    )
    sol08_payable_send_pattern = re.compile(
        r'payable\(\s*([\w\.]+)\s*\)\.send\(\s*([\w\.]+)\s*\)'
    )
    sol08_bool_assign_send_pattern = re.compile(
        r'bool\s+(\w+)\s*=\s*(?:payable\(\s*([\w\.]+)\s*\)|([\w\.]+))\.send\(\s*([\w\.]+)\s*\)\s*;'
    )
    sol08_call_gas_pattern = re.compile(
        r'\(\s*bool\s+(\w+)\s*,\s*(?:bytes\s+memory\s+\w+\s*)?\)\s*=\s*([\w\.]+)\.call\{(?:value\s*:\s*([\w\.]+)\s*,\s*gas\s*:\s*[\w\.]+|gas\s*:\s*[\w\.]+\s*,\s*value\s*:\s*([\w\.]+))\s*\}\s*\([^)]*\)\s*;'
    )

    def replace_sol08_payable_call(match):
        res_var = match.group(1)
        recipient = match.group(2)
        amount_var = match.group(3)
        _transformed_bool_vars.add(res_var)
        mapping_name = mapping_names[0] if mapping_names else "BAL"
        return (
            f"bool {res_var} = false;\n"
            f"if (BAL > 0 && {mapping_name} >= {amount_var}) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"    attacker_bal = attacker_bal + {amount_var};\n"
            f"    {res_var} = true;\n"
            f"}} else {{\n"
            f"    {res_var} = false;\n"
            f"}}"
        )

    def replace_sol08_payable_transfer(match):
        recipient = match.group(1)
        amount_var = match.group(2)
        mapping_name = mapping_names[0] if mapping_names else "BAL"
        return (
            f"if (BAL > 0 && {mapping_name} >= {amount_var}) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"    attacker_bal = attacker_bal + {amount_var};\n"
            f"}}"
        )

    def replace_sol08_payable_send(match):
        recipient = match.group(1)
        amount_var = match.group(2)
        mapping_name = mapping_names[0] if mapping_names else "BAL"
        return (
            f"if (BAL > 0 && {mapping_name} >= {amount_var}) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"    attacker_bal = attacker_bal + {amount_var};\n"
            f"}}"
        )

    def replace_sol08_bool_assign_send(match):
        res_var = match.group(1)
        amount_var = match.group(4)
        _transformed_bool_vars.add(res_var)
        mapping_name = mapping_names[0] if mapping_names else "BAL"
        return (
            f"bool {res_var} = false;\n"
            f"if (BAL > 0 && {mapping_name} >= {amount_var}) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"    attacker_bal = attacker_bal + {amount_var};\n"
            f"    {res_var} = true;\n"
            f"}} else {{\n"
            f"    {res_var} = false;\n"
            f"}}"
        )

    def replace_sol08_call_gas(match):
        res_var = match.group(1)
        recipient = match.group(2)
        amount_var = match.group(3) or match.group(4)
        _transformed_bool_vars.add(res_var)
        mapping_name = mapping_names[0] if mapping_names else "BAL"
        return (
            f"bool {res_var} = false;\n"
            f"if (BAL > 0 && {mapping_name} >= {amount_var}) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"    attacker_bal = attacker_bal + {amount_var};\n"
            f"    {res_var} = true;\n"
            f"}} else {{\n"
            f"    {res_var} = false;\n"
            f"}}"
        )
    require_success_pattern = re.compile(
        r'require\s*\(\s*(\w+)\s*(?:,\s*"[^"]*")?\s*\)\s*;'
    )
    delegatecall_stmt_pattern = re.compile(
        r'(?:\(\s*bool\s+\w+\s*,\s*\)\s*=\s*)?[\w\.]+\.(?:delegatecall|staticcall)\s*\([^)]*\)\s*;'
    )
    abi_encode_pattern = re.compile(
        r'abi\.encodeWithSignature\s*\([^)]*\)'
    )

    def replace_sol08_tuple_call(match):
        res_var = match.group(1)
        recipient = match.group(2)
        amount_var = match.group(3)
        mapping_name = mapping_names[0] if mapping_names else "BAL"
        return (
            f"bool {res_var} = false;\n"
            f"if (BAL > 0 && {mapping_name} >= {amount_var}) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"    attacker_bal = attacker_bal + {amount_var};\n"
            f"    {res_var} = true;\n"
            f"}} else {{\n"
            f"    {res_var} = false;\n"
            f"}}"
        )

    call_pattern1 = re.compile(r'bool\s+(\w+)\s*=\s*msg\.sender\.call\.value\(([\w\.]+)\)\(\);')
    call_pattern2 = re.compile(r'\(\s*bool\s+(\w+)\s*,\s*\)\s*=\s*msg\.sender\.call\.value\(([\w\.]+)\)\(""\);')
    call_pattern3 = re.compile(r'bool\s+(\w+)\s*=\s*recipient\.call\.value\(([\w\.]+)\)\(\);')
    call_pattern4 = re.compile(r'\(\s*bool\s+(\w+)\s*,\s*\)\s*=\s*recipient\.call\.value\(([\w\.]+)\)\(""\);')
    call_pattern5 = re.compile(r'([ \t]*msg\.sender\.send\(([\w\.]+)\)\s*;)')
    call_pattern6 = re.compile(r'[ \t]*msg\.sender\.transfer\(\s*([\w\.]+)\s*\)\s*;')
    require_call_pattern = re.compile(r'require\s*\(\s*msg\.sender\.call\.value\(([\w\.]+)\)\(\)\s*\);')
    if_call_pattern = re.compile(r'if\s*\(\s*msg\.sender\.call\.value\(([\w\.]+)\)\(\)\s*\)\s*{([^{}]*)}')
    if_call_pattern1 = re.compile(r'if\s*\(\s*_recipient\.call\.value\(([\w\.]+)\)\(\)\s*\)\s*{([^{}]*)}')
    if_call_pattern2 = re.compile(r'if\s*\(\s*(\w+)\.call\.value\(([\w\.]+)\)\(\)\s*\)\s*{([^{}]*)}')
    if_not_call_pattern = re.compile(r'if\s*\(\s*!\s*\(\s*msg\.sender\.call\.value\(([\w\.\[\]]+)\)\(\)\s*\)\s*\)\s*{([^{}]*)}')
    if_negated_call_throw_pattern = re.compile(r'if\s*\(\s*!\s*\(?\s*(.*?)\.call\.value\(\s*(.*?)\s*\)\s*\(\s*\)\s*\)?\s*\)\s*throw\s*;')
    if_call_value_pattern = re.compile(r'if\s*\(\s*\w+\.call\.value\(\s*balances\[msg\.sender\]\s*\)\s*\(\s*\)\s*\)')
    call_pattern7 = re.compile(r'assert\s*\(\s*msg\.sender\.call\.value\(([\w\[\]\.]+)\)\(\)\s*\)\s*;')
    call_pattern8 = re.compile(r'\bmsg\.sender\.call\.value\(([\w\[\]\.]+)\)\(\)\s*;')
    call_pattern_direct = re.compile(r'([\w\d_]+)\.call\.value\(\s*([\w\d_\.]+)\s*\)\s*\(\s*([^\)]*)\s*\)\s*;')
    if_throw_call_pattern = re.compile(r'if\s*\(\s*!\s*\(([\w\d_]+)\.call\.value\(([\w\d_]+)\)\(([\w\d_]+)\)\)\s*\)\s*throw\s*;')
    call_value_pattern = re.compile(r'\b\w+\.call\.value\(\s*balances\[msg\.sender\]\s*\)\s*\(\s*\)')
    simple_call_value_pattern = re.compile(r'if\s*\(\s*\w+\.call\.value\(\s*balances\s*\)\s*\(\s*\)\s*\)')
    mapping_decrement_pattern = re.compile(r'(\w+)\s*\[\s*([\w\.\[\]]+)\s*\]\s*=\s*\1\s*\[\s*\2\s*\]\s*-\s*([\w\.\[\]]+)\s*;')
    negated_call_if_pattern = re.compile(r'if\s*\(\s*!\s*\(?\s*([\w\.]+)\.call\.value\(([\w\.]+)\)\(\)\s*\)?\s*\)\s*{([^{}]*)}\s*else\s*{([^{}]*)}')
    if_call_value_block_pattern = re.compile(r'if\s*\(\s*\w+\.call\.value\(\s*balances\[msg\.sender\]\s*\)\s*\(\s*\)\s*\)\s*\{\s*balances\[msg\.sender\]\s*=\s*0;\s*\}') 
    generic_require_call_pattern = re.compile(r'(?:require|assert)\s*\(\s*(.*?)\.call\.value\(\s*([^\)]+)\s*\)\s*\(\s*([^\)]*)\s*\)\s*\)\s*;')
    generic_send_pattern = re.compile(r'([ \t]*\w+\.send\(([^)]+)\)\s*;)')
    negated_throw_call_pattern = re.compile(r'if\s*\(\s*!\s*\(?\s*([\w\d_]+)\.call\.value\(\s*([\w\d_\.]+)\s*\)\(\s*\)\s*\)?\s*\)\s*\{\s*throw\s*;\s*\}')
    negated_revert_call_pattern = re.compile(r'if\s*\(\s*!\s*\(?\s*([\w\d_\.]+)\.call\.value\(\s*([\w\d_\.]+)\s*\)\s*\(\s*\)\s*\)?\s*\)\s*revert\s*\(\s*\)\s*;')
    token_balance_assignment_pattern = re.compile(r'(\w+)\s*=\s*(\w+)\.balanceOf\s*\(\s*this\s*\)\s*;')
    generic_transfer_pattern = re.compile(r'[ \t]*(\w+)\.transfer\(\s*([\w\.]+)\s*\)\s*;')

    def replace_negated_throw_call(match):
        addr = match.group(1)
        value = match.group(2)
        mapping_name = mapping_names[0] if mapping_names else "BAL"
        return (
            f"if (BAL > 0 && {mapping_name} >= {value}) {{\n"
            f"    BAL = BAL - {value};\n"
            f"}}"
        )
    
    def replace_if_negated_call_throw(match):
        address_var = match.group(1).strip()
        amount_var = match.group(2).strip()
        mapping_name = mapping_names[0] if mapping_names else "BAL"
        return (
            f"if (BAL > 0 && {mapping_name} >= {amount_var}) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"}}"
        )

    def replace_generic_send(match):
        amount_var = match.group(2).strip()
        mapping_name = mapping_names[0] if mapping_names else "BAL"
        return (
            f"\nif (BAL > 0 && {mapping_name} >= {amount_var}) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"}}\n"
        )

    def replace_if_call(match):
        amount_var = match.group(1)
        mapping_name = mapping_names[0] if mapping_names else "mappingName"
        inner_statements = match.group(2).strip()
        if mapping_name in mapping_types:
            if mapping_types[mapping_name] in ["uint", "uint256"]:
                transformed_code = (
                    f"if (BAL > {amount_var} && {mapping_name} >= {amount_var} ) {{\n"
                    f"    BAL = BAL - {amount_var};\n"
                    f"}}\n"
                    f"{inner_statements}"
                )
            else:
                struct_attributes = struct_definitions.get(mapping_types[mapping_name], {})
                _BALANCE_NAMES = {'balance', 'bal', 'amount', 'value', 'weiAmount', 'deposit'}
                balance_attr = next(
                    (attr for attr, attr_type in struct_attributes.items()
                     if attr_type.startswith("uint") and attr.lower() in _BALANCE_NAMES),
                    next(
                        (attr for attr, attr_type in struct_attributes.items()
                         if attr_type.startswith("uint")),
                        "balance"
                    )
                )
                transformed_code = (
                    f"if (BAL > {amount_var} && {balance_attr} >= {amount_var} ) {{\n"
                    f"    BAL = BAL - {amount_var};\n"
                    f"}}\n"
                    f"{inner_statements}"
                )
            return transformed_code
        return f"// Unable to transform 'if' statement with {mapping_name}"

    def replace_if_call1(match):
        recipient = match.group(1)
        amount_var = match.group(2)
        inner_statements = match.group(3).strip()
        mapping_name = mapping_names[0] if mapping_names else "mappingName"
        return (
            f"if (BAL > 0 && {mapping_name} >= {amount_var}) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"}}\n"
            f"{inner_statements}"
        )

    def replace_if_throw_call(match):
        addr, value, func_hash = match.groups()
        return f"""
            if (BAL >= {value}) {{
                BAL = BAL - {value};
            }}
            """
    
    def replace_if_call_value_block(match):
        recipient_match = re.search(r'if\s*\(\s*(\w+)\.call', match.group(0))
        recipient = recipient_match.group(1) if recipient_match else "recipient"
        value_expr = "balances[msg.sender]"
        return (
            f"if (BAL >= {value_expr}) {{\n"
            f"    BAL = BAL - {value_expr};\n"
            f"}}"
        )

    def replace_simple_call_value(match):
        original = match.group(0)
        recipient_match = re.search(r'(\w+)\.call', original)
        recipient = recipient_match.group(1) if recipient_match else 'recipient'
        return (
            f"if (BAL >= balances) {{\n"
            f"    BAL = BAL - balances;\n"
            f"}}\n"
        )

    def replace_call_value_expr(match):
        full_call = match.group(0)
        recipient = re.match(r'(\w+)\.call', full_call).group(1)
        value_expr = "balances[msg.sender]"
        return (
            f"if (BAL >= {value_expr}) {{\n"
            f"    BAL = BAL - {value_expr};\n"
            f"}}\n"
        )
      
    def replace_if_not_call(match):
        amount_var = match.group(1)
        mapping_name = mapping_names[0] if mapping_names else "mappingName"
        inner_statements = match.group(2).strip()
        transformed_code = (
            f"if (BAL > {amount_var} && {mapping_name} >= {amount_var} ) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"}}\n"
        )
        return transformed_code
    
    def replace_require_call(match):
        amount_var = match.group(1)
        mapping_name = mapping_names[0] if mapping_names else "mappingName"
        transformed_code = (
            f"if (BAL > 0 && {mapping_name} >= {amount_var} ) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"    attacker_bal = attacker_bal + {amount_var};\n"
            f"}}\n"
        )
        return transformed_code
    
    def replace_assert_call(match):
        amount_var = match.group(1)
        mapping_name = mapping_names[0] if mapping_names else "BAL"
        transformed_code = (
            f"if (BAL > 0 && {mapping_name} >= {amount_var} ) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"}}"
        )
        return transformed_code

    def replace_send(match):
        amount_var = match.group(2)
        if mapping_names:
            mapping_name = mapping_names[0] 
            transformed_code = (
                f"        \n if (BAL > 0 && {mapping_name} >= {amount_var} ) {{\n"
                f"            BAL = BAL - {amount_var};\n"
                f"        }}\n"
            )
            return transformed_code 
        else: 
            return match.group(0)

    def replace_transfer(match):
        amount_var = match.group(1)
        mapping_name = mapping_names[0] if mapping_names else "BAL"
        return (
            f"if (BAL > 0 && {mapping_name} >= {amount_var}) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"}}"
        )

    def replace_bare_call(match):
        amount_var = match.group(1)
        mapping_name = mapping_names[0] if mapping_names else "BAL"
        return (
            f"if (BAL > 0 && {mapping_name} >= {amount_var}) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"}}\n"
        )

    def replace_generic_require_call(match):
        address_var = match.group(1).strip()
        amount_var = match.group(2).strip()
        call_args = match.group(3).strip()
        mapping_name = mapping_names[0] if mapping_names else "BAL"
        return (
            f"if (BAL > 0 && {mapping_name} >= {amount_var}) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"    attacker_bal = attacker_bal + {amount_var};\n"
            f"}}"
        )

    def replace_mapping_decrement(match):
        mapping_name = match.group(1)
        amount_var = match.group(3)
        if mapping_name in mapping_names:
            return f"{mapping_name} = {mapping_name} - {amount_var};"
        return match.group(0)
      
    def replace_call(match):
        res_var = match.group(1)
        amount_var = match.group(2)
        mapping_name = mapping_names[0] if mapping_names else "mappingName"
        transformed_code = (
            f"bool {res_var} = false;\n"
            f"if (BAL > {amount_var} && {mapping_name} >= {amount_var} ) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"    attacker_bal = attacker_bal + {amount_var};\n"
            f"    {res_var} = true;\n"
            f"}} else {{\n"
            f"    {res_var} = false;\n"
            f"}}"
        )
        return transformed_code
    
    def replace_direct_call(match):
        recipient = match.group(1)
        amount_var = match.group(2)
        call_args = match.group(3).strip()
        mapping_name = mapping_names[0] if mapping_names else "BAL"
        return (
            f"if (BAL > 0 && {mapping_name} >= {amount_var}) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"}}"
        )

    def replace_negated_call_if(match):
        address_var = match.group(1)
        amount_var = match.group(2)
        false_block = match.group(3).strip()
        true_block = match.group(4).strip()
        mapped_amount = amount_var.replace("msg.value", "msgvalue")
        mapping_name = mapping_names[0] if mapping_names else "BAL"
        return (
            f"if (BAL > 0 && {mapping_name} >= {mapped_amount}) {{\n"
            f"    BAL = BAL - {mapped_amount};\n"
            f"    {true_block}\n"
            f"}} else {{\n"
            f"    {false_block}\n"
            f"}}"
        )
    
    def replace_if_call_value(match):
        original = match.group(0)       
        recipient_match = re.search(r'if\s*\(\s*(\w+)\.call', original)
        recipient = recipient_match.group(1) if recipient_match else "recipient"        
        value_expr = "balances[msg.sender]"        
        return (
            f"if (BAL >= {value_expr}) {{\n"
            f"    BAL = BAL - {value_expr};\n"
            f"}}"
        )
    
    def replace_negated_revert_call(match):
        address_var = match.group(1)
        amount_var = match.group(2)
        mapping_name = mapping_names[0] if mapping_names else "BAL"
        return (
            f"if (BAL > 0 && {mapping_name} >= {amount_var}) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"}}"
        )

    def replace_token_balance_assignment(match):
        lhs = match.group(1)
        token_var = match.group(2)
        return f"uint simulated_token_balance = 60; /* call to {token_var}.balanceOf(this) */\n{lhs} = simulated_token_balance;"

    def replace_generic_transfer(match):
        recipient = match.group(1)
        amount_var = match.group(2)
        mapping_name = mapping_names[0] if mapping_names else "BAL"
        return (
            f"if (BAL > 0 && {mapping_name} >= {amount_var}) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"}}"
        )

    _transformed_bool_vars = set()

    def strip_require_for_transformed_bools(source):
        """Remove require(<var>, ...) statements where <var> was a"""
        for var in _transformed_bool_vars:
            pat = re.compile(
                rf'require\s*\(\s*{re.escape(var)}\s*(?:,\s*"[^"]*")?\s*\)\s*;'
            )
            source = pat.sub('// require(' + var + ') removed (transformed)', source)
        return source

    def replace_sol08_call_and_track(match):
        """Wrapper around replace_sol08_tuple_call that also records"""
        res_var = match.group(1)
        _transformed_bool_vars.add(res_var)
        return replace_sol08_tuple_call(match)

    struct_definitions = extract_struct_definitions(solidity_source)

    def track_mappings(match):
        key_type, value_type, _, mapping_name = match.groups()
        mapping_names.append(mapping_name)
        mapping_types[mapping_name] = value_type
        return match.group(0)
    
    transformed_source = re.sub(contract_declaration_pattern, inject_bal_variable, solidity_source)
    transformed_source = re.sub(mapping_pattern, track_mappings, transformed_source)
    transformed_source = re.sub(mapping_pattern, lambda match: replace_mapping(match, struct_definitions), transformed_source)
    transformed_source = replace_struct_references(transformed_source, struct_definitions)
    mapped_struct_names = set(
        vt for vt in mapping_types.values() if vt in struct_definitions
    )
    if mapped_struct_names:
        for sname in mapped_struct_names:
            mapped_struct_pattern = re.compile(
                rf'struct\s+{re.escape(sname)}\s*\{{[^}}]+\}}'
            )
            transformed_source = mapped_struct_pattern.sub("", transformed_source).strip()
    transformed_source = re.sub(mapping_access_pattern, replace_access, transformed_source)

    transformed_source = re.sub(sol08_tuple_call_bytes_pattern, replace_sol08_call_and_track, transformed_source)
    transformed_source = re.sub(sol08_tuple_call_pattern, replace_sol08_call_and_track, transformed_source)
    transformed_source = re.sub(sol08_payable_call_pattern, replace_sol08_payable_call, transformed_source)
    transformed_source = re.sub(sol08_call_gas_pattern, replace_sol08_call_gas, transformed_source)
    transformed_source = re.sub(sol08_tuple_call_data_pattern, replace_sol08_call_and_track, transformed_source)
    transformed_source = re.sub(sol08_payable_transfer_pattern, replace_sol08_payable_transfer, transformed_source)
    transformed_source = re.sub(sol08_bool_assign_send_pattern, replace_sol08_bool_assign_send, transformed_source)
    transformed_source = re.sub(sol08_payable_send_pattern, replace_sol08_payable_send, transformed_source)

    transformed_source = re.sub(call_pattern1, replace_call, transformed_source)
    transformed_source = re.sub(call_pattern2, replace_call, transformed_source)
    transformed_source = re.sub(call_pattern3, replace_call, transformed_source)
    transformed_source = re.sub(call_pattern4, replace_call, transformed_source)
    transformed_source = re.sub(if_call_pattern, replace_if_call, transformed_source)
    transformed_source = re.sub(if_call_pattern1, replace_if_call, transformed_source)
    transformed_source = re.sub(if_not_call_pattern, replace_if_not_call, transformed_source)
    transformed_source = re.sub(require_call_pattern, replace_require_call, transformed_source)
    transformed_source = re.sub(call_pattern5, replace_send, transformed_source)
    transformed_source = re.sub(call_pattern6, replace_transfer, transformed_source)
    transformed_source = re.sub(if_throw_call_pattern, replace_if_throw_call, transformed_source)
    transformed_source = re.sub(if_call_value_pattern, replace_if_call_value, transformed_source)
    transformed_source = re.sub(call_value_pattern, replace_call_value_expr, transformed_source)
    transformed_source = re.sub(simple_call_value_pattern, replace_simple_call_value, transformed_source)
    transformed_source = re.sub(if_call_value_block_pattern, replace_if_call_value_block, transformed_source)
    transformed_source = re.sub(call_pattern7, replace_assert_call, transformed_source)
    transformed_source = re.sub(call_pattern8, replace_bare_call, transformed_source)
    transformed_source = re.sub(mapping_decrement_pattern, replace_mapping_decrement, transformed_source)
    transformed_source = re.sub(negated_call_if_pattern, replace_negated_call_if, transformed_source)   
    transformed_source = re.sub(generic_require_call_pattern, replace_generic_require_call, transformed_source)
    transformed_source = re.sub(call_pattern_direct, replace_direct_call, transformed_source)
    transformed_source = re.sub(generic_send_pattern, replace_generic_send, transformed_source)
    transformed_source = re.sub(negated_throw_call_pattern, replace_negated_throw_call, transformed_source)
    transformed_source = re.sub(if_negated_call_throw_pattern, replace_if_negated_call_throw, transformed_source)
    transformed_source = re.sub(if_call_pattern2, replace_if_call1, transformed_source)
    transformed_source = re.sub(negated_revert_call_pattern, replace_negated_revert_call, transformed_source)
    transformed_source = re.sub(token_balance_assignment_pattern, replace_token_balance_assignment, transformed_source)
    transformed_source = re.sub(generic_transfer_pattern, replace_generic_transfer, transformed_source)

    _delegatecall_bool_vars = set()
    for dm in delegatecall_stmt_pattern.finditer(transformed_source):
        bm = re.search(r'\(\s*bool\s+(\w+)\s*,', dm.group(0))
        if bm:
            _delegatecall_bool_vars.add(bm.group(1))
    transformed_source = re.sub(delegatecall_stmt_pattern, '// delegatecall removed (transformed)', transformed_source)

    for dvar in _delegatecall_bool_vars:
        transformed_source = re.sub(
            rf'require\s*\(\s*{re.escape(dvar)}\s*(?:,\s*"[^"]*")?\s*\)\s*;',
            f'// require({dvar}) removed (transformed)',
            transformed_source
        )

    transformed_source = strip_require_for_transformed_bools(transformed_source)

    transformed_source = re.sub(
        r'require\s*\(\s*delegateSuccess\s*(?:,\s*"[^"]*")?\s*\)\s*;',
        '// require(delegateSuccess) removed (transformed)',
        transformed_source
    )

    if mapped_struct_names:
        for struct_name in mapped_struct_names:
            storage_decl_pattern = re.compile(
                rf'\b{re.escape(struct_name)}\s+(?:storage|memory)\s+\w+\s*=[^;]*;'
            )
            transformed_source = re.sub(
                storage_decl_pattern,
                f'// {struct_name} storage declaration removed (struct flattened)',
                transformed_source
            )

    if mapping_names:
        _stz = re.compile(
            r'(?:' + re.escape(mapping_names[0]) + r')'
            r'\s*\[\s*[\w.\[\]]+\s*\]\s*=\s*0\s*;'
        )
        transformed_source = _stz.sub(
            mapping_names[0] + ' = 0;', transformed_source
        )

    credit_var_name = mapping_names[0] if mapping_names else None

    if credit_var_name is not None:
        import re as _re
        bare_ref = _re.search(
            rf'\b{_re.escape(credit_var_name)}\s*(?:=|-=|\+=)',
            transformed_source
        )
        if not bare_ref:
            credit_var_name = None

    if credit_var_name is None:
        has_bal_encoding = 'BAL = BAL -' in transformed_source
        if has_bal_encoding:
            transformed_source = transformed_source.replace(
                'uint public BAL = 100;uint public attacker_bal = 10;',
                'uint public BAL = 100;uint public attacker_bal = 10;uint public credit_a = 40;',
                1
            )
            credit_dec_pattern = re.compile(r'(BAL = BAL - ([\w\.]+);)')
            def _inject_credit_dec(m):
                return m.group(1) + f'\n    credit_a = credit_a - {m.group(2)};'
            transformed_source = re.sub(credit_dec_pattern, _inject_credit_dec, transformed_source)
            credit_var_name = 'credit_a'

    return transformed_source, credit_var_name

if __name__ == "__main__":
    source = ''' '''      
    transformed_source = transform_mappings(source)

    print("Transformed Solidity Source Code:")
    print(transformed_source)