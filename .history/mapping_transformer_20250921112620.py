import re

def transform_mappings(solidity_source):
    """
    Transforms Solidity code by injecting BAL into contract declarations and modifying mappings.
    """
    # Regular expression to match contract declarations
    contract_declaration_pattern = re.compile(r'(contract\s+\w+\s*{)')

    # Function to inject `BAL` variable into contract declarations
    def inject_bal_variable(match):
        contract_declaration = match.group(1)
        injected_line = "   uint public BAL = 100;\n"
        return f"{contract_declaration}\n{injected_line}"
    
    # Regular expression to match any mapping declaration
    mapping_pattern = re.compile(
        r'mapping\s*\(\s*([\w\[\]]+)\s*=>\s*([\w\[\]]+)\s*\)\s*(public|private|internal)?\s*(\w+)\s*;'
    )

    # Function to extract struct definitions and their attributes
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
        for struct_name, attributes in struct_definitions.items():
            for attr_name in attributes.keys():
                # Replace all references to the struct attribute
                attribute_pattern = re.compile(rf'\b\w+\.{attr_name}\b')  # Matches `object.attribute`
                code = attribute_pattern.sub(attr_name, code)
        return code 

    def replace_mapping(match, struct_definitions):
        value_type = match.group(2)
        visibility = match.group(3) if match.group(3) else "public"  # Default to public if not specified
        mapping_name = match.group(4)
        
        # Handle basic types
        if value_type in ["uint", "uint256", "uint8","int"]:
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
                elif attr_type == "string":
                    init_value = '"default"'
                elif attr_type == "address":
                    init_value = 'address(0)'
                else:
                    init_value = f"{attr_type}()"  # Fallback to default constructor

                init_lines.append(f"{attr_type} {attr_name} = {init_value};  // from struct {value_type}")
            return "\n".join(init_lines)

        return f"// Unable to transform mapping for {mapping_name}"
    # Regular expression to match specific mapping accesses (e.g., `<mapping_name>[msg.sender]` or `<mapping_name>[recipient]`)
    mapping_access_pattern = re.compile(r'(\w+)\s*\[\s*(msg\.sender|recipient|_addr|_to|_from|_h|from|owner|_owner|to|_participant|investor|_pd|0x[a-fA-F0-9]{40}|\w+)\s*\]')

    # Function to replace specific mapping accesses with the mapping name
    mapping_names = []  # Collect mapping names to use later
    def replace_access(match):
        mapping_name = match.group(1)
        if mapping_name in mapping_names:  # Only transform if the mapping name is in the collected list
            return f"{mapping_name}"
        return match.group(0)
    
    # # Regular expression to match the pattern bool <var> = msg.sender.call.value(<amount>)();
    call_pattern1 = re.compile(r'bool\s+(\w+)\s*=\s*msg\.sender\.call\.value\(([\w\.]+)\)\(\);')
    call_pattern2 = re.compile(r'\(\s*bool\s+(\w+)\s*,\s*\)\s*=\s*msg\.sender\.call\.value\(([\w\.]+)\)\(""\);')
    call_pattern3 = re.compile(r'bool\s+(\w+)\s*=\s*recipient\.call\.value\(([\w\.]+)\)\(\);')
    call_pattern4 = re.compile(r'\(\s*bool\s+(\w+)\s*,\s*\)\s*=\s*recipient\.call\.value\(([\w\.]+)\)\(""\);')
    call_pattern5 = re.compile(r'(\s*msg\.sender\.send\(([\w\.]+)\)\s*;)')
    call_pattern6 = re.compile(r'(?:\s*msg\.sender\.transfer\(\s*([\w\.]+)\s*\)\s*;)|(?:msg\.sender\.transfer\(\s*([\w\.]+)\s*\)\s*;)')
    require_call_pattern = re.compile(r'require\s*\(\s*msg\.sender\.call\.value\(([\w\.]+)\)\(\)\s*\);')
    # Pattern to match `if (msg.sender.call.value(_am)())` with inner curly braces
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
    generic_send_pattern = re.compile(r'(\s*\w+\.send\(([^)]+)\)\s*;)')
    negated_throw_call_pattern = re.compile(r'if\s*\(\s*!\s*\(?\s*([\w\d_]+)\.call\.value\(\s*([\w\d_\.]+)\s*\)\(\s*\)\s*\)?\s*\)\s*\{\s*throw\s*;\s*\}')
    negated_revert_call_pattern = re.compile(r'if\s*\(\s*!\s*\(?\s*([\w\d_\.]+)\.call\.value\(\s*([\w\d_\.]+)\s*\)\s*\(\s*\)\s*\)?\s*\)\s*revert\s*\(\s*\)\s*;')
    token_balance_assignment_pattern = re.compile(r'(\w+)\s*=\s*(\w+)\.balanceOf\s*\(\s*this\s*\)\s*;')


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


    # Replace the risky call pattern
    def replace_if_call(match):
        amount_var = match.group(1)
        mapping_name = mapping_names[0] if mapping_names else "mappingName"
        inner_statements = match.group(2).strip()  # Extract content inside the braces

        # Construct the transformed code
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
                balance_attr = next(
                    (attr for attr, attr_type in struct_attributes.items() if attr_type == "uint"), "balance"
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
        inner_statements = match.group(2).strip()  # Extract content inside the braces

        # Construct the transformed code
        transformed_code = (
            f"if (BAL > {amount_var} && {mapping_name} >= {amount_var} ) {{\n"
            f"    BAL = BAL - {amount_var};\n"
            f"}}\n"
        )
        return transformed_code
    
    def replace_require_call(match):
        amount_var = match.group(1)  # Amount being transferred
        mapping_name = mapping_names[0] if mapping_names else "mappingName"

        # Construct the transformed code
        transformed_code = (
            f"if (BAL > 0 && {mapping_name} >= {amount_var} ) {{\n"
            f"    BAL = BAL - {amount_var};\n"
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
        amount_var = match.group(2)  # Amount being transferred
        if mapping_names:
            mapping_name = mapping_names[0] 
            # Construct the transformed code
            transformed_code = (
                f"        \n if (BAL > 0 && {mapping_name} >= {amount_var} ) {{\n"
                f"            BAL = BAL - {amount_var};\n"
                f"        }}\n"
            )
            return transformed_code 
        else : 
            return match.group(0)  # Return the original `msg.sender.send(...)` statement without replacement

    def replace_transfer(match):
        amount_var = match.group(1) if match.group(1) else match.group(2)
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
            f"}}"
        )

    def replace_mapping_decrement(match):
        mapping_name = match.group(1)
        amount_var = match.group(3)
        # Only transform if it's a known mapping
        if mapping_name in mapping_names:
            return f"{mapping_name} = {mapping_name} - {amount_var};"
        return match.group(0)
      
    def replace_call(match):
        res_var = match.group(1)
        amount_var = match.group(2)
        mapping_name = mapping_names[0] if mapping_names else "mappingName"
        transformed_code = (
            f"bool {res_var} = false;\n"
            f"if (BAL >  && {mapping_name} >= {amount_var} ) {{\n"
            f"    BAL = BAL - {amount_var};\n"
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
        # Substitute msg.value or other values as needed
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


    struct_definitions = extract_struct_definitions(solidity_source)
    mapping_names = []
    mapping_types = {}

    def track_mappings(match):
        key_type, value_type, _, mapping_name = match.groups()
        mapping_names.append(mapping_name)
        mapping_types[mapping_name] = value_type
        return match.group(0)
    
    # Apply the BAL injection
    transformed_source = re.sub(contract_declaration_pattern, inject_bal_variable, solidity_source)
    transformed_source = re.sub(mapping_pattern, track_mappings, transformed_source)
    transformed_source = re.sub(mapping_pattern, lambda match: replace_mapping(match, struct_definitions), transformed_source)
    # Replace struct attribute references
    transformed_source = replace_struct_references(transformed_source, struct_definitions)
    struct_definition_pattern = re.compile(r'struct\s+\w+\s*{\s*[^}]+}')
    transformed_source = re.sub(mapping_access_pattern,replace_access, transformed_source)
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
    transformed_source = struct_definition_pattern.sub("", transformed_source).strip()
    transformed_source = re.sub(if_throw_call_pattern, replace_if_throw_call, transformed_source)
    transformed_source = re.sub(if_call_value_pattern,replace_if_call_value,transformed_source)
    transformed_source = re.sub(call_value_pattern, replace_call_value_expr, transformed_source)
    transformed_source = re.sub(simple_call_value_pattern, replace_simple_call_value, transformed_source)
    transformed_source = re.sub(if_call_value_block_pattern,replace_if_call_value_block,transformed_source)
    transformed_source = re.sub(call_pattern7, replace_assert_call, transformed_source)
    transformed_source = re.sub(call_pattern8, replace_bare_call, transformed_source)
    transformed_source = re.sub(mapping_decrement_pattern, replace_mapping_decrement, transformed_source)
    transformed_source = re.sub(negated_call_if_pattern, replace_negated_call_if, transformed_source)   
    transformed_source = re.sub(generic_require_call_pattern, replace_generic_require_call, transformed_source)
    transformed_source =re.sub(call_pattern_direct, replace_direct_call, transformed_source)
    transformed_source = re.sub(generic_send_pattern, replace_generic_send, transformed_source)
    transformed_source = re.sub(negated_throw_call_pattern, replace_negated_throw_call, transformed_source)
    transformed_source = re.sub(if_negated_call_throw_pattern, replace_if_negated_call_throw, transformed_source)
    transformed_source = re.sub(if_call_pattern2, replace_if_call1, transformed_source)
    transformed_source = re.sub(negated_revert_call_pattern, replace_negated_revert_call, transformed_source)
    transformed_source = re.sub(token_balance_assignment_pattern, replace_token_balance_assignment, transformed_source)


    return transformed_source

# Example usage
if __name__ == "__main__":
    source = ''' '''      
    transformed_source = transform_mappings(source)

    print("Transformed Solidity Source Code:")
    print(transformed_source)
