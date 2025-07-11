#!/usr/bin/env python3
"""
Test script for chained rule logic
"""

def test_chained_rule_logic():
    """Test the chained rule evaluation logic"""
    
    # Mock rule engine class
    class MockRuleEngine:
        def check_condition(self, condition, conversions, spend, cpa, payout, campaign):
            """Check if a condition matches current campaign state"""
            condition_type = condition.get("type", "")
            
            if condition_type == "conversions_and_spend":
                # e.g., "0 conversions and spend >= $50"
                target_conversions = condition.get("conversions", 0)
                spend_threshold = condition.get("spend_threshold", 0)
                return conversions == target_conversions and spend >= spend_threshold
                
            elif condition_type == "conversions_exact":
                # e.g., "exactly 1 conversion"
                target_conversions = condition.get("conversions", 0)
                return conversions == target_conversions
                
            elif condition_type == "cpa_threshold":
                # e.g., "CPA > payout - buffer"
                cpa_threshold = condition.get("cpa_threshold", 0)
                operator = condition.get("operator", ">")
                
                if operator == ">":
                    return cpa > cpa_threshold
                elif operator == ">=":
                    return cpa >= cpa_threshold
                elif operator == "<":
                    return cpa < cpa_threshold
                elif operator == "<=":
                    return cpa <= cpa_threshold
                elif operator == "==":
                    return abs(cpa - cpa_threshold) < 0.01
                    
            elif condition_type == "status":
                # e.g., "campaign is PAUSED"
                target_status = condition.get("status", "")
                return campaign.get("status") == target_status
                
            return False

        def evaluate_chained_rule(self, rule, campaign_data, campaign_id, campaign):
            """Evaluate chained logic rule"""
            conversions = campaign_data["conversions"]
            spend = campaign_data.get("spend", campaign.get("spend", 0))
            cpa = campaign_data["cpa"]
            payout = rule["payout"]
            
            print(f"🔗 Evaluating chained rule with {len(rule['chain_logic'])} conditions")
            
            # Process each condition in the chain
            for i, condition in enumerate(rule['chain_logic']):
                print(f"   🔍 Condition {i+1}: {condition.get('description', 'No description')}")
                
                # Check if this condition matches
                if self.check_condition(condition, conversions, spend, cpa, payout, campaign):
                    action = condition.get("action", "no_action")
                    if action != "continue":
                        return {
                            "action": action,
                            "reason": f"{condition.get('reason', 'Chained rule triggered')} [Conv: {conversions}, Spend: ${spend}, CPA: ${cpa}, Payout: ${payout}]",
                            "campaign_id": campaign_id,
                            "rule_id": rule["id"],
                            "rule_name": rule["name"]
                        }
            
            # If no conditions matched, return no action
            return {"action": "no_action", "reason": "No chained conditions matched"}

    # Test scenarios
    engine = MockRuleEngine()
    
    # Test Rule: Kill at $50 & 0 conv → if 1 conv, kill at $60 → else guard with CPA ≤ $60
    test_rule = {
        "id": "test_rule_1",
        "name": "Advanced Protection Rule",
        "payout": 75,
        "rule_type": "chained",
        "chain_logic": [
            {
                "type": "conversions_and_spend",
                "conversions": 0,
                "spend_threshold": 50,
                "action": "kill",
                "reason": "Kill at $50 with 0 conversions",
                "description": "Kill at $50 with 0 conversions"
            },
            {
                "type": "conversions_and_spend",
                "conversions": 1,
                "spend_threshold": 60,
                "action": "kill",
                "reason": "Kill at $60 with 1 conversion",
                "description": "Kill at $60 with 1 conversion"
            },
            {
                "type": "cpa_threshold",
                "operator": ">",
                "cpa_threshold": 60,
                "action": "kill",
                "reason": "Kill if CPA > $60",
                "description": "Kill if CPA > $60"
            }
        ]
    }
    
    # Test scenarios
    test_scenarios = [
        {
            "name": "Scenario 1: 0 conversions, $55 spend",
            "campaign_data": {"conversions": 0, "spend": 55, "cpa": 0},
            "campaign": {"id": "camp1", "status": "ACTIVE", "spend": 55},
            "expected_action": "kill",
            "expected_reason": "Kill at $50 with 0 conversions"
        },
        {
            "name": "Scenario 2: 0 conversions, $40 spend",
            "campaign_data": {"conversions": 0, "spend": 40, "cpa": 0},
            "campaign": {"id": "camp2", "status": "ACTIVE", "spend": 40},
            "expected_action": "no_action",
            "expected_reason": "No chained conditions matched"
        },
        {
            "name": "Scenario 3: 1 conversion, $65 spend",
            "campaign_data": {"conversions": 1, "spend": 65, "cpa": 65},
            "campaign": {"id": "camp3", "status": "ACTIVE", "spend": 65},
            "expected_action": "kill",
            "expected_reason": "Kill at $60 with 1 conversion"
        },
        {
            "name": "Scenario 4: 2 conversions, CPA $70",
            "campaign_data": {"conversions": 2, "spend": 140, "cpa": 70},
            "campaign": {"id": "camp4", "status": "ACTIVE", "spend": 140},
            "expected_action": "kill",
            "expected_reason": "Kill if CPA > $60"
        },
        {
            "name": "Scenario 5: 3 conversions, CPA $50",
            "campaign_data": {"conversions": 3, "spend": 150, "cpa": 50},
            "campaign": {"id": "camp5", "status": "ACTIVE", "spend": 150},
            "expected_action": "no_action",
            "expected_reason": "No chained conditions matched"
        }
    ]
    
    print("🧪 Testing Chained Rule Logic")
    print("=" * 50)
    
    all_passed = True
    
    for scenario in test_scenarios:
        print(f"\n📋 {scenario['name']}")
        print(f"   Data: {scenario['campaign_data']}")
        
        result = engine.evaluate_chained_rule(
            test_rule, 
            scenario['campaign_data'], 
            scenario['campaign']['id'], 
            scenario['campaign']
        )
        
        action_match = result['action'] == scenario['expected_action']
        reason_contains = scenario['expected_reason'] in result['reason']
        
        if action_match and reason_contains:
            print(f"   ✅ PASS: Action={result['action']}, Reason={result['reason']}")
        else:
            print(f"   ❌ FAIL: Expected action={scenario['expected_action']}, got={result['action']}")
            print(f"          Expected reason to contain='{scenario['expected_reason']}'")
            print(f"          Got reason='{result['reason']}'")
            all_passed = False
    
    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 ALL TESTS PASSED! Chained rule logic is working correctly.")
    else:
        print("❌ SOME TESTS FAILED! Please check the rule logic.")
    
    return all_passed

if __name__ == "__main__":
    test_chained_rule_logic()
