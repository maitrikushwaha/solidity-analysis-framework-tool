import re
# Use a relative import to load the invariant templates
from .invariant_templates import check_invariants

# Function to extract variable names from the first line of the file
def extract_variable_names(analysis_output_file):
    with open(analysis_output_file, "r") as file:
        # Read the first line to get the variable names
        first_line = file.readline().strip()
        # Use regex to extract variable names from dict_keys(['a', 'c'])
        match = re.match(r"^dict_keys\(\[(.*)\]\)$", first_line)
        if match:
            # Extract variable names (e.g., 'a', 'c') and split them into a list
            variable_names = match.group(1).replace("'", "").split(", ")
            return variable_names
        else:
            raise ValueError("Could not extract variable names from the file")

# Function to extract variable states from the abstract interpretation output
def extract_variable_states(analysis_output_file, variable_names):
    variable_states = {}

    with open(analysis_output_file, "r") as file:
        # Skip the first line as it contains variable names, not states
        next(file)
        
        for line in file:
            # Use regex to capture entries like: ENTRY X FunctionEntry_0 [[a_state], [b_state]]
            match = re.match(r'^ENTRY \d+ \w+ \[\[([-\d.,]+),([-\d.,]+)\], \[([-\d.,]+),([-\d.,]+)\]\]', line)
            if match:
                # Extract the state bounds of two variables
                var1_min, var1_max, var2_min, var2_max = map(float, match.groups())
                # Map the states to the dynamically extracted variable names
                variable_states[variable_names[0]] = (var1_min, var1_max)
                variable_states[variable_names[1]] = (var2_min, var2_max)
    
    return variable_states

# Main function to generate invariants from the abstract interpretation output
def generate_invariants_from_file(analysis_output_file):
    # Extract variable names from the first line of the file
    variable_names = extract_variable_names(analysis_output_file)
    
    # Extract variable states from the subsequent lines using the variable names
    variable_states = extract_variable_states(analysis_output_file, variable_names)
    
    # Generate invariants using the extracted variable states
    invariants = check_invariants(variable_states)
    
    # Format the invariants to reflect the correct variable names
    formatted_invariants = []
    for invariant in invariants:
        # Replace placeholder variable names ('a', 'b') with the extracted ones
        formatted_invariants.append(invariant.format(var1=variable_names[0], var2=variable_names[1]))
    
    return formatted_invariants
