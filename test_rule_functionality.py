#!/usr/bin/env python3
"""
Test script to verify rule functionality
Creates test rules and checks if they work correctly on campaigns
"""

import sys
import json
import time
from datetime import datetime

# Import the app modules
try:
    from app import AutomationEngine, save_rule_to_db, load_rules_from_db
    print("✅ Successfully imported app modules")
except ImportError as e:
    print(f"❌ Failed to import app modules: {e}")
    sys.exit(1)

def create_test_rules():
    """Create test rules for verification"""
    print("\n🔧 Creating test rules...")
    
    username = "test_user"
    
    # Test Rule 1: Basic Protection Rule
    rule1 = {
        "id": f"rule_test1_{int(time.time())}_{username}",
        "name": "Basic Protection Rule",
        "payout": 75.0,
        "created_at": datetime.now().isoformat(),
        "active": True,
        "rule_type": "chained",
        "chain_logic": [
            {
                "type": "conversions_and_spend",
                "conversions": 0,
                "spend_threshold": 50.0,
                "action": "kill",
                "description": "Kill at $50 with 0 conversions",
                "reason": "Kill at $50 with 0 conversions"
            },
            {
                "type": "conversions_and_spend", 
                "conversions": 1,
                "spend_threshold": 75.0,
                "action": "kill",
                "description": "Kill at $75 with 1 conversion",
                "reason": "Kill at $75 with 1 conversion"
            },
            {
                "type": "cpa_threshold",
                "operator": ">",
                "cpa_threshold": 60.0,
                "action": "kill",
                "description": "Kill if CPA > $60",
                "reason": "Kill if CPA > $60"
            }
        ]
    }
    
    # Test Rule 2: Aggressive Rule
    rule2 = {
        "id": f"rule_test2_{int(time.time())}_{username}",
        "name": "Aggressive Killer Rule",
        "payout": 100.0,
        "created_at": datetime.now().isoformat(),
        "active": True,
        "rule_type": "chained",
        "chain_logic": [
            {
                "type": "conversions_and_spend",
                "conversions": 0,
                "spend_threshold": 30.0,
                "action": "kill",
                "description": "Kill at $30 with 0 conversions",
                "reason": "Kill at $30 with 0 conversions"
            },
            {
                "type": "cpa_threshold",
                "operator": ">=",
                "cpa_threshold": 80.0,
                "action": "kill",
                "description": "Kill if CPA >= $80",
                "reason": "Kill if CPA >= $80"
            }
        ]
    }
    
    # Test Rule 3: Conservative Rule with Reactivation
    rule3 = {
        "id": f"rule_test3_{int(time.time())}_{username}",
        "name": "Conservative Rule",
        "payout": 120.0,
        "created_at": datetime.now().isoformat(),
        "active": True,
        "rule_type": "chained",
        "chain_logic": [
            {
                "type": "conversions_and_spend",
                "conversions": 0,
                "spend_threshold": 100.0,
                "action": "kill",
                "description": "Kill at $100 with 0 conversions",
                "reason": "Kill at $100 with 0 conversions"
            },
            {
                "type": "cpa_threshold",
                "operator": "<",
                "cpa_threshold": 90.0,
                "action": "reactivate",
                "description": "Reactivate if CPA < $90",
                "reason": "Reactivate if CPA < $90"
            }
        ]
    }
    
    # Save rules to database
    try:
        save_rule_to_db(username, rule1)
        print(f"✅ Created rule: {rule1['name']}")
        
        save_rule_to_db(username, rule2)
        print(f"✅ Created rule: {rule2['name']}")
        
        save_rule_to_db(username, rule3)
        print(f"✅ Created rule: {rule3['name']}")
        
        return [rule1, rule2, rule3]
        
    except Exception as e:
        print(f"❌ Failed to save rules: {e}")
        return []

def create_test_campaigns():
    """Create test campaign scenarios"""
    print("\n📊 Creating test campaign scenarios...")
    
    campaigns = [
        {
            "id": "camp_test_1",
            "name": "Test Campaign 1 - No Conversions High Spend",
            "status": "ACTIVE",
            "spend": 60.0,
            "conversions": 0,
            "revenue": 0.0,
            "cpa": 999999
        },
        {
            "id": "camp_test_2", 
            "name": "Test Campaign 2 - One Conversion High Spend",
            "status": "ACTIVE",
            "spend": 80.0,
            "conversions": 1,
            "revenue": 75.0,
            "cpa": 80.0
        },
        {
            "id": "camp_test_3",
            "name": "Test Campaign 3 - Good Performance",
            "status": "ACTIVE", 
            "spend": 100.0,
            "conversions": 3,
            "revenue": 225.0,
            "cpa": 33.33
        },
        {
            "id": "camp_test_4",
            "name": "Test Campaign 4 - Paused Low CPA",
            "status": "PAUSED",
            "spend": 150.0,
            "conversions": 2,
            "revenue": 240.0,
            "cpa": 75.0
        },
        {
            "id": "camp_test_5",
            "name": "Test Campaign 5 - High CPA",
            "status": "ACTIVE",
            "spend": 200.0,
            "conversions": 2,
            "revenue": 150.0,
            "cpa": 100.0
        }
    ]
    
    for camp in campaigns:
        print(f"📋 {camp['name']}: Spend=${camp['spend']}, Conv={camp['conversions']}, CPA=${camp['cpa']}, Status={camp['status']}")
    
    return campaigns

def test_rule_engine():
    """Test the rule engine with test scenarios"""
    print("\n🔍 Testing Rule Engine...")
    
    # Create test data
    rules = create_test_rules()
    campaigns = create_test_campaigns()
    
    if not rules:
        print("❌ No rules created, cannot test")
        return
    
    # Initialize automation engine
    engine = AutomationEngine("test_user")
    
    print(f"\n🎯 Testing {len(rules)} rules against {len(campaigns)} campaigns...")
    
    # Test each rule against each campaign
    for rule in rules:
        print(f"\n🔧 Testing Rule: {rule['name']} (Payout: ${rule['payout']})")
        print(f"   Conditions: {len(rule['chain_logic'])}")
        
        for campaign in campaigns:
            print(f"\n   📊 Campaign: {campaign['name']}")
            print(f"      Spend: ${campaign['spend']}, Conversions: {campaign['conversions']}, CPA: ${campaign['cpa']}, Status: {campaign['status']}")
            
            try:
                # Test rule evaluation
                evaluation = engine.evaluate_rule_for_campaign(rule, campaign)
                
                action = evaluation.get("action", "unknown")
                reason = evaluation.get("reason", "No reason provided")
                
                if action == "kill":
                    print(f"      🔴 ACTION: KILL - {reason}")
                elif action == "reactivate":
                    print(f"      🟢 ACTION: REACTIVATE - {reason}")
                elif action == "no_action":
                    print(f"      ⚪ ACTION: NO ACTION - {reason}")
                else:
                    print(f"      ⚫ ACTION: {action.upper()} - {reason}")
                    
            except Exception as e:
                print(f"      ❌ ERROR: {e}")

def verify_database_storage():
    """Verify rules are stored correctly in database"""
    print("\n💾 Verifying database storage...")
    
    try:
        rules = load_rules_from_db("test_user")
        print(f"✅ Loaded {len(rules)} rules from database")
        
        for rule in rules:
            print(f"\n📋 Rule: {rule['name']}")
            print(f"   ID: {rule['id']}")
            print(f"   Payout: ${rule['payout']}")
            print(f"   Type: {rule['rule_type']}")
            print(f"   Conditions: {len(rule.get('chain_logic', []))}")
            
            # Check for unwanted legacy fields
            legacy_fields = ['kill_on_no_conversion_spend', 'kill_on_one_conversion_spend', 'max_cpa_allowed']
            has_legacy = any(field in rule for field in legacy_fields)
            
            if has_legacy:
                print(f"   ⚠️  Contains legacy fields (backward compatibility)")
            else:
                print(f"   ✅ Clean storage (no legacy fields)")
                
    except Exception as e:
        print(f"❌ Database verification failed: {e}")

if __name__ == "__main__":
    print("🚀 Starting Rule Functionality Test")
    print("=" * 50)
    
    # Run tests
    verify_database_storage()
    test_rule_engine()
    
    print("\n" + "=" * 50)
    print("✅ Rule functionality test completed!")
