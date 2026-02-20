
import unittest
import threading
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from noe.noe_parser import run_noe_logic, NoeEvaluator

class TestParserConcurrency(unittest.TestCase):
    """
    Verify thread safety of the Noe parser, specifically the AST cache.
    """
    
    def test_concurrent_parsing(self):
        now_us = time.time_ns() // 1_000
        ctx = {
            "literals": {
                "@agent": {"value": True, "timestamp_us": now_us},
                "@target": {"value": "MOVE_FWD", "type": "action", "timestamp_us": now_us}
            },
            "modal": {"knowledge": {"@agent": True}, "belief": {}, "certainty": {}},
            "temporal": {"now_us": now_us},
            "axioms": {},
            "delivery": {"status": "ready"},
            "audit": {"enabled": True},
            "spatial": {"thresholds": {"near": 1.0, "far": 10.0}, "orientation": {}}
        }
        
        # Use proper guard syntax: shi @agent khi sek mek @target sek nek
        chain = "shi @agent khi sek mek @target sek nek"
        
        exceptions = []
        results = []
        
        def runner():
            try:
                # Use fresh evaluator to test shared AST cache contention
                res = run_noe_logic(chain, ctx, mode="strict")
                results.append(res)
            except Exception as e:
                exceptions.append(e)

        threads = []
        for _ in range(20):
            t = threading.Thread(target=runner)
            threads.append(t)
            t.start()
            
        for t in threads:
            t.join()
            
        self.assertEqual(len(exceptions), 0, f"Exceptions occurred: {exceptions}")
        self.assertEqual(len(results), 20)
        
        # Verify all results are identical
        if not results:
            self.fail("No results")
            
        # Expecting domain=list with action
        if results[0].get("domain") == "error":
             self.fail(f"Parser returned error: {results[0]}")

        # Extract action_hash from the first action in results
        first_value = results[0]["value"]
        if isinstance(first_value, list) and len(first_value) > 0:
            first_action = first_value[0]
            if isinstance(first_action, dict):
                first_hash = first_action.get("action_hash")
            else:
                first_hash = None
        else:
            first_hash = None
            
        self.assertIsNotNone(first_hash, "No action_hash found in result")
        
        # Verify all concurrent results have identical hash
        for r in results:
            r_value = r["value"]
            if isinstance(r_value, list) and len(r_value) > 0:
                r_action = r_value[0]
                if isinstance(r_action, dict):
                    self.assertEqual(r_action.get("action_hash"), first_hash,
                                     "Concurrent parsing produced different action hashes!")

if __name__ == "__main__":
    unittest.main()
