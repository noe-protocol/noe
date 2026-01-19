
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
from noe.noe_parser import NoeEvaluator

class TestSpatialOperators(unittest.TestCase):
    def setUp(self):
        """Setup context with entities that have position and velocity."""
        self.context = {
            "literals": {
                "@robot": True,
                "@goal": True,
                "@obstacle": True,
                "@target_north": True
            },
            "entities": {
                "@robot": {
                    "position": [0.0, 0.0],
                    "velocity": [1.0, 0.0]  # Moving right (+x direction)
                },
                "@goal": {
                    "position": [5.0, 0.0]  # 5 units to the right
                },
                "@obstacle": {
                    "position": [-3.0, 0.0]  # 3 units to the left
                },
                "@target_north": {
                    "position": [0.0, 5.0]  # 5 units up
                }
            },
            "spatial": {
                "thresholds": {
                    "near": 2.0,
                    "far": 10.0
                }
            }
        }
        self.evaluator = NoeEvaluator(self.context, mode="strict")

    def test_tra_towards_positive(self):
        """
        Robot at (0,0) with vel=[1,0] moving towards goal at (5,0).
        Dot product: vel·(goal-robot) = [1,0]·[5,0] = 5 > 0 → True
        """
        result = self.evaluator._apply_binary_op("@robot", "tra", "@goal")
        self.assertTrue(result, "Robot moving towards goal should return True")

    def test_tra_away_negative(self):
        """
        Robot at (0,0) with vel=[1,0] moving, obstacle at (-3,0).
        Dot product: vel·(obstacle-robot) = [1,0]·[-3,0] = -3 < 0 → False
        """
        result = self.evaluator._apply_binary_op("@robot", "tra", "@obstacle")
        self.assertFalse(result, "Robot moving away from obstacle should return False")

    def test_fra_away_positive(self):
        """
        Robot at (0,0) with vel=[1,0] moving away from obstacle at (-3,0).
        Dot product: vel·(obstacle-robot) = [1,0]·[-3,0] = -3 < 0 → True (away)
        """
        result = self.evaluator._apply_binary_op("@robot", "fra", "@obstacle")
        self.assertTrue(result, "Robot moving away from obstacle should return True")

    def test_fra_towards_negative(self):
        """
        Robot at (0,0) with vel=[1,0] moving towards goal at (5,0).
        Dot product: vel·(goal-robot) = [1,0]·[5,0] = 5 > 0 → False (not away)
        """
        result = self.evaluator._apply_binary_op("@robot", "fra", "@goal")
        self.assertFalse(result, "Robot moving towards goal should not be 'away'")

    def test_tra_perpendicular(self):
        """
        Robot at (0,0) with vel=[1,0] (moving right), target_north at (0,5).
        Dot product: vel·(target-robot) = [1,0]·[0,5] = 0 → False (perpendicular)
        """
        result = self.evaluator._apply_binary_op("@robot", "tra", "@target_north")
        self.assertFalse(result, "Perpendicular movement should return False")

    def test_tra_no_velocity(self):
        """
        Entity without velocity should return 'undefined'.
        """
        result = self.evaluator._apply_binary_op("@goal", "tra", "@obstacle")
        self.assertEqual(result, "undefined", "Missing velocity should return undefined")

    def test_tra_missing_entity(self):
        """
        Non-existent entity should return 'undefined'.
        """
        result = self.evaluator._apply_binary_op("@robot", "tra", "@ghost")
        self.assertEqual(result, "undefined", "Missing entity should return undefined")

    def test_tra_2d_diagonal(self):
        """
        Test diagonal movement (both x and y components).
        Robot at (0,0) with vel=[1,1] moving northeast.
        Target at (3,3) northeast → dot = [1,1]·[3,3] = 6 > 0 → True
        """
        self.context["entities"]["@robot"]["velocity"] = [1.0, 1.0]
        self.context["entities"]["@diagonal"] = {"position": [3.0, 3.0]}
        
        evaluator = NoeEvaluator(self.context, mode="strict")
        result = evaluator._apply_binary_op("@robot", "tra", "@diagonal")
        self.assertTrue(result, "Diagonal movement towards target should return True")

    def test_fra_2d_diagonal(self):
        """
        Robot at (0,0) with vel=[1,1] moving northeast.
        Obstacle at (-2,-2) southwest → dot = [1,1]·[-2,-2] = -4 < 0 → True (away)
        """
        self.context["entities"]["@robot"]["velocity"] = [1.0, 1.0]
        self.context["entities"]["@southwest"] = {"position": [-2.0, -2.0]}
        
        evaluator = NoeEvaluator(self.context, mode="strict")
        result = evaluator._apply_binary_op("@robot", "fra", "@southwest")
        self.assertTrue(result, "Diagonal movement away from target should return True")

    def test_integration_spatial_guard(self):
        """
        Integration test: Use tra in a guarded expression.
        '@robot tra @goal khi true' should evaluate to True (guard passes).
        """
        # Manually test the guard logic
        tra_result = self.evaluator._apply_binary_op("@robot", "tra", "@goal")
        self.assertTrue(tra_result)
        
        # Now test khi (guard)
        guard_result = self.evaluator._apply_binary_op(tra_result, "khi", True)
        self.assertTrue(guard_result, "Guard with valid tra condition should pass")

if __name__ == "__main__":
    unittest.main()
