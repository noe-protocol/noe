import sys
import os
import random
import json
import traceback

# Add parent directory to path to import noe_parser
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from noe.noe_parser import run_noe_logic

# Fuzzer Configuration
MAX_DEPTH = 5
MAX_LENGTH = 10
ITERATIONS = 1000

# Grammar Primitives
OPERATORS = ["|", "an", "ur", "noq", "shi", "sha", "vek", "nel", "tel", "xel", "en", "tra", "fra"]
LITERALS = ["true", "false", "@agent", "@target", "@obj", "123", "0.5", "dia", "dai"]
TERMINATOR = "nek"
SEPARATORS = [" ", "  ", "\n", "\t"]

def generate_random_context():
    """Generates a random, potentially valid or invalid context."""
    return {
        "root": {
            "literals": {
                "@agent": True,
                "@target": {"type": "action", "verb": "dummy", "target": "something"},
                "@obj": {"pos": [random.random()*10, random.random()*10, 0]},
                "@missing": None # Explicitly None to test handling
            },
            "modal": {
                "knowledge": {"@fact": True},
                "belief": {"@belief": True},
                "certainty": {"@high_conf": 0.9, "@low_conf": 0.1}
            },
            "spatial": {
                "unit": "generic",
                "thresholds": {
                    "near": random.uniform(0.1, 5.0),
                    "far": random.uniform(5.1, 20.0),
                    "direction": 0.1
                },
                "orientation": {
                    "target": random.uniform(0, 360),
                    "tolerance": 0.1
                }
            },
            "delivery": {
                "status": {}
            },
            "audit": {},
            "axioms": {},
            "rel": {},
            "demonstratives": {}
        }
    }

def generate_random_chain(depth=0):
    """Generates a random chain string."""
    if depth > MAX_DEPTH:
        return random.choice(LITERALS)
    
    choice = random.random()
    if choice < 0.4:
        # Simple literal
        return random.choice(LITERALS)
    elif choice < 0.7:
        # Unary op
        op = random.choice(["shi", "sha", "vek", "mek", "sek"])
        operand = generate_random_chain(depth + 1)
        return f"{op} {operand}"
    else:
        # Binary op
        op = random.choice(OPERATORS)
        left = generate_random_chain(depth + 1)
        right = generate_random_chain(depth + 1)
        return f"{left} {op} {right}"

def fuzz():
    print(f"Starting fuzzer for {ITERATIONS} iterations...")
    
    crashes = 0
    
    for i in range(ITERATIONS):
        chain_body = generate_random_chain()
        # Sometimes forget termination, sometimes double it
        term_choice = random.random()
        if term_choice < 0.8:
            chain = f"{chain_body} {TERMINATOR}"
        elif term_choice < 0.9:
            chain = chain_body # Missing termination
        else:
            chain = f"{chain_body} {TERMINATOR} {TERMINATOR}"
            
        context = generate_random_context()
        
        try:
            # Run logic
            run_noe_logic(chain, context, mode="strict")
                
        except Exception as e:
            # We expect some errors (ParseError, etc.), but we want to catch UNHANDLED exceptions
            error_type = type(e).__name__
            
            # Filter out expected parsing errors if they are just "NoMatch" or similar
            # But for now, let's log everything that looks like a crash
            if error_type in ["AttributeError", "TypeError", "IndexError", "ValueError", "KeyError", "ZeroDivisionError"]:
                crashes += 1
                print(f"CRASH detected at iteration {i}!")
                print(f"Input: {chain}")
                print(f"Error: {e}")
                traceback.print_exc()
                
                with open("fuzz_failures.txt", "a") as f:
                    f.write(f"Iteration {i}\nInput: {chain}\nError: {e}\nTraceback:\n{traceback.format_exc()}\n\n")

    print(f"Fuzzing complete. Crashes found: {crashes}")

if __name__ == "__main__":
    fuzz()
