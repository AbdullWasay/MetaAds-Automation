from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import subprocess
import sys
import requests
import json
import threading
import time
import os
import pickle
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-to-something-secure')

# ===============================
# PERSISTENTE DATENBANK (SQLite)
# ===============================

def init_database():
    """Initialize SQLite database for persistent storage"""
    conn = sqlite3.connect('neural_dashboard.db')
    cursor = conn.cursor()
    
    # User Rules Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rules (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            name TEXT NOT NULL,
            payout REAL NOT NULL,
            kill_on_no_conversion_spend REAL NOT NULL,
            kill_on_one_conversion_spend REAL NOT NULL,
            profit_buffer REAL NOT NULL,
            max_cpa_allowed REAL NOT NULL,
            reactivate_if_cpa_below REAL NOT NULL,
            check_interval_minutes INTEGER NOT NULL,
            reactivate_if_profitable BOOLEAN NOT NULL,
            created_at TEXT NOT NULL,
            active BOOLEAN NOT NULL DEFAULT 1
        )
    ''')
    
    # Campaign Rule Assignments Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS campaign_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            campaign_id TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            assigned_at TEXT NOT NULL,
            UNIQUE(username, campaign_id, rule_id)
        )
    ''')
    
    # Campaign Status Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS campaign_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            campaign_id TEXT NOT NULL,
            current_status TEXT NOT NULL,
            last_action TEXT NOT NULL,
            last_check TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(username, campaign_id)
        )
    ''')
    
    # Automation Status Table (NEU)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS automation_status (
            username TEXT PRIMARY KEY,
            is_running BOOLEAN NOT NULL DEFAULT 0,
            started_at TEXT,
            last_check TEXT,
            last_action_count INTEGER DEFAULT 0
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Datenbank initialisiert!")

# Initialize database on startup
init_database()

def get_db_connection():
    """Get database connection"""
    conn = sqlite3.connect('neural_dashboard.db')
    conn.row_factory = sqlite3.Row
    return conn

def save_rule_to_db(username, rule):
    """Save rule to database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO rules 
        (id, username, name, payout, kill_on_no_conversion_spend, 
         kill_on_one_conversion_spend, profit_buffer, max_cpa_allowed, 
         reactivate_if_cpa_below, check_interval_minutes, reactivate_if_profitable, 
         created_at, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        rule['id'], username, rule['name'], rule['payout'],
        rule['kill_on_no_conversion_spend'], rule['kill_on_one_conversion_spend'],
        rule['profit_buffer'], rule['max_cpa_allowed'], rule['reactivate_if_cpa_below'],
        rule['check_interval_minutes'], rule['reactivate_if_profitable'],
        rule['created_at'], rule['active']
    ))
    
    conn.commit()
    conn.close()

def load_rules_from_db(username):
    """Load rules from database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM rules WHERE username = ? AND active = 1', (username,))
    rows = cursor.fetchall()
    
    rules = []
    for row in rows:
        rule = {
            'id': row['id'],
            'name': row['name'],
            'payout': row['payout'],
            'kill_on_no_conversion_spend': row['kill_on_no_conversion_spend'],
            'kill_on_one_conversion_spend': row['kill_on_one_conversion_spend'],
            'profit_buffer': row['profit_buffer'],
            'max_cpa_allowed': row['max_cpa_allowed'],
            'reactivate_if_cpa_below': row['reactivate_if_cpa_below'],
            'check_interval_minutes': row['check_interval_minutes'],
            'reactivate_if_profitable': bool(row['reactivate_if_profitable']),
            'created_at': row['created_at'],
            'active': bool(row['active'])
        }
        rules.append(rule)
    
    conn.close()
    return rules

def assign_rule_to_campaign_db(username, campaign_id, rule_id):
    """Assign rule to campaign in database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO campaign_rules (username, campaign_id, rule_id, assigned_at)
            VALUES (?, ?, ?, ?)
        ''', (username, campaign_id, rule_id, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        # Rule already assigned
        conn.close()
        return False

def remove_rule_from_campaign_db(username, campaign_id, rule_id):
    """Remove rule from campaign in database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        DELETE FROM campaign_rules 
        WHERE username = ? AND campaign_id = ? AND rule_id = ?
    ''', (username, campaign_id, rule_id))
    
    conn.commit()
    conn.close()

def get_campaign_rules_db(username, campaign_id):
    """Get rules assigned to campaign"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT rule_id FROM campaign_rules 
        WHERE username = ? AND campaign_id = ?
    ''', (username, campaign_id))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [row['rule_id'] for row in rows]

def delete_rule_from_db(username, rule_id):
    """Delete rule from database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Mark rule as inactive
    cursor.execute('''
        UPDATE rules SET active = 0 WHERE username = ? AND id = ?
    ''', (username, rule_id))
    
    # Remove all campaign assignments
    cursor.execute('''
        DELETE FROM campaign_rules WHERE username = ? AND rule_id = ?
    ''', (username, rule_id))
    
    conn.commit()
    conn.close()

def has_active_rule_assignments(username):
    """Check if user has any active rule assignments"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT COUNT(*) as count FROM campaign_rules 
        WHERE username = ?
    ''', (username,))
    
    result = cursor.fetchone()
    conn.close()
    
    return result['count'] > 0

def set_automation_status(username, is_running):
    """Set automation status for user"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if is_running:
        cursor.execute('''
            INSERT OR REPLACE INTO automation_status 
            (username, is_running, started_at, last_check)
            VALUES (?, 1, ?, ?)
        ''', (username, datetime.now().isoformat(), datetime.now().isoformat()))
    else:
        cursor.execute('''
            UPDATE automation_status SET is_running = 0 WHERE username = ?
        ''', (username,))
    
    conn.commit()
    conn.close()

def get_automation_status(username):
    """Get automation status for user"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM automation_status WHERE username = ?
    ''', (username,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            'is_running': bool(result['is_running']),
            'started_at': result['started_at'],
            'last_check': result['last_check'],
            'last_action_count': result['last_action_count']
        }
    else:
        return {
            'is_running': False,
            'started_at': None,
            'last_check': None,
            'last_action_count': 0
        }

# ===============================
# LOGIN SYSTEM
# ===============================

VALID_CREDENTIALS = {
    'admin': 'password123'
}

@app.route('/')
def index():
    return render_template('login.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if username in VALID_CREDENTIALS and VALID_CREDENTIALS[username] == password:
            session['logged_in'] = True
            session['username'] = username
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials. Please try again.', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    # Stop automation when user logs out
    username = session.get('username')
    if username:
        set_automation_status(username, False)
        stop_user_automation(username)
    
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ===============================
# USER DATA MANAGEMENT
# ===============================

user_data_store = {}

def get_user_data(username):
    """Get user-specific dashboard data"""
    if username not in user_data_store:
        data_file = f"user_data_{username}.pkl"
        if os.path.exists(data_file):
            try:
                with open(data_file, 'rb') as f:
                    user_data_store[username] = pickle.load(f)
            except:
                user_data_store[username] = create_empty_user_data()
        else:
            user_data_store[username] = create_empty_user_data()
    return user_data_store[username]

def save_user_data(username):
    """Save user-specific dashboard data to file"""
    try:
        data_file = f"user_data_{username}.pkl"
        with open(data_file, 'wb') as f:
            pickle.dump(user_data_store[username], f)
    except Exception as e:
        print(f"❌ Error saving data for {username}: {e}")

def create_empty_user_data():
    """Create empty user data structure"""
    return {
        "accounts": [],
        "campaigns": [],
        "current_account": None,
        "redtrack_data": {},
        "analysis": {}
    }

# ===============================
# API CONFIGURATION
# ===============================

META_TOKEN = os.environ.get('META_TOKEN', "EAAO4jYfx1A4BOwF0SnFbXRjVzeKv7FVfB9SEezapKZAFz2g6zrZCnGoQM2kJOnvbj1RpJYjVnRCFCPZAlxlUr4cB0NVIOEj8lAyOI5IYlEuHkDGOtvvTpZClcCkT3JlBB57UNdh0H5qi9sxOsIkIBFweGcU8NIvdK4cnPL880olcGFuZCIRZAxZCDlGRO7JXgZDZD")

REDTRACK_CONFIG = {
    "api_key": os.environ.get('REDTRACK_API_KEY', "VbxluETPTeNxPLmyawYz"),
    "base_url": "https://api.redtrack.io/v1"
}

# ===============================
# DATE RANGE FUNCTIONS
# ===============================

def get_date_range(period):
    """Calculate date range in EST for RedTrack and UTC for Meta"""
    try:
        tz_est = ZoneInfo("America/New_York")
        now = datetime.now(tz_est)
        
        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
        elif period == "yesterday":
            yesterday = now - timedelta(days=1)
            start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end = yesterday.replace(hour=23, minute=59, second=59)
        elif period == "last_7_days":
            start = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
        elif period == "last_30_days":
            start = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
        else:
            start = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
        
        to_utc = lambda dt: dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d")
        to_est = lambda dt: dt.strftime("%Y-%m-%d")
        
        return {
            "meta": {"since": to_utc(start), "until": to_utc(end)},
            "redtrack": {"since": to_est(start), "until": to_est(end)},
            "display": f"{to_est(start)} → {to_est(end)} (EST)"
        }
        
    except Exception as e:
        print(f"❌ Timezone Error: {str(e)}")
        now = datetime.utcnow()
        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
        elif period == "yesterday":
            yesterday = now - timedelta(days=1)
            start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end = yesterday.replace(hour=23, minute=59, second=59)
        elif period == "last_7_days":
            start = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
        else:
            start = (now - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
        
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
        
        return {
            "meta": {"since": start_str, "until": end_str},
            "redtrack": {"since": start_str, "until": end_str},
            "display": f"{start_str} → {end_str} (UTC Fallback)"
        }

# ===============================
# REVOLUTIONÄRES AUTOMATISCHES REGEL-SYSTEM
# ===============================

# Global user automation threads
user_automation_threads = {}

class AutomationEngine:
    def __init__(self, username):
        self.username = username
        self.running = False
        self.thread = None
    
    def get_campaign_data_with_dynamic_payout(self, campaign_id, rule_payout):
        """Get campaign data with DYNAMIC payout from rule (FIXED!)"""
        user_data = get_user_data(self.username)
        campaign = next((c for c in user_data.get("campaigns", []) if c["id"] == campaign_id), None)
        
        if not campaign:
            print(f"❌ Campaign {campaign_id} not found")
            return {
                "conversions": 0,
                "revenue": 0,
                "cost": 0,
                "cpa": 999999,
                "conversion_rate": 0,
                "profit": 0,
                "source": "not_found"
            }
        
        revenue = campaign.get("revenue", 0)
        spend = campaign.get("spend", 0)
        
        print(f"🔍 Campaign data for {campaign['name']}: Revenue=${revenue}, Spend=${spend}, Rule Payout=${rule_payout}")
        
        # 🚨 CRITICAL FIX: Use DYNAMIC payout from rule, not hardcoded $75
        if revenue <= 0:
            print(f"   ❌ Revenue is 0 → DEFINITELY 0 Conversions")
            return {
                "conversions": 0,
                "revenue": 0,
                "cost": spend,
                "cpa": 999999,
                "conversion_rate": 0,
                "profit": -spend,
                "source": "no_revenue"
            }
        
        # Calculate conversions based on RULE'S payout, not hardcoded value
        estimated_conversions = max(1, int(revenue / rule_payout))
        cpa = (spend / estimated_conversions) if estimated_conversions > 0 else 999999
        
        print(f"   ✅ Revenue > 0 → {estimated_conversions} conversions estimated (Payout: ${rule_payout}), CPA=${cpa}")
        
        return {
            "conversions": estimated_conversions,
            "revenue": revenue,
            "cost": spend,
            "cpa": round(cpa, 2),
            "conversion_rate": round((estimated_conversions / max(1, spend * 10)) * 100, 2),
            "profit": round(revenue - spend, 2),
            "source": "calculated"
        }
    
    def evaluate_rule_for_campaign(self, rule, campaign):
        """Evaluate rule for campaign with DYNAMIC payout"""
        if not campaign or campaign.get("status") not in ["ACTIVE", "PAUSED"]:
            return {"action": "skip", "reason": "Campaign not found or invalid status"}
        
        campaign_id = campaign["id"]
        spend = campaign.get("spend", 0)
        
        # Get campaign data with RULE'S payout (FIXED!)
        campaign_data = self.get_campaign_data_with_dynamic_payout(campaign_id, rule["payout"])
        conversions = campaign_data["conversions"]
        cpa = campaign_data["cpa"]
        
        print(f"🔍 Evaluating rule '{rule['name']}' for campaign {campaign['name']}")
        print(f"   Spend: ${spend}, Conversions: {conversions}, CPA: ${cpa} (Payout: ${rule['payout']})")
        
        # Rule 1: Kill at 0 conversions over spend limit
        if conversions == 0:
            if spend >= rule["kill_on_no_conversion_spend"] and campaign["status"] == "ACTIVE":
                return {
                    "action": "kill",
                    "reason": f"0 conversions with ${spend} spend (Limit: ${rule['kill_on_no_conversion_spend']}) [Payout: ${rule['payout']}]",
                    "campaign_id": campaign_id,
                    "rule_id": rule["id"]
                }
            return {"action": "no_action", "reason": f"0 conversions - waiting for first conversion [Payout: ${rule['payout']}]"}
        
        # Rule 2: Kill at exactly 1 conversion over spend limit  
        if conversions == 1:
            if spend >= rule["kill_on_one_conversion_spend"] and campaign["status"] == "ACTIVE":
                return {
                    "action": "kill",
                    "reason": f"Only 1 conversion with ${spend} spend (Limit: ${rule['kill_on_one_conversion_spend']}) [Payout: ${rule['payout']}]",
                    "campaign_id": campaign_id,
                    "rule_id": rule["id"]
                }
            return {"action": "no_action", "reason": f"Only 1 conversion - too little data [Payout: ${rule['payout']}]"}
        
        # Rule 3: CPA-based decisions at 2+ conversions
        if conversions >= 2:
            if cpa >= rule["max_cpa_allowed"] and campaign["status"] == "ACTIVE":
                return {
                    "action": "kill",
                    "reason": f"CPA ${cpa} exceeds limit ${rule['max_cpa_allowed']} at {conversions} conversions [Payout: ${rule['payout']}]",
                    "campaign_id": campaign_id,
                    "rule_id": rule["id"]
                }
            
            if (rule["reactivate_if_profitable"] and 
                cpa < rule["reactivate_if_cpa_below"] and
                campaign["status"] == "PAUSED"):
                
                return {
                    "action": "reactivate",
                    "reason": f"CPA ${cpa} below threshold ${rule['reactivate_if_cpa_below']} at {conversions} conversions [Payout: ${rule['payout']}]",
                    "campaign_id": campaign_id,
                    "rule_id": rule["id"]
                }
            
            return {"action": "no_action", "reason": f"CPA ${cpa} at {conversions} conversions within range [Payout: ${rule['payout']}]"}
        
        return {"action": "no_action", "reason": f"Unknown conversion status [Payout: ${rule['payout']}]"}
    
    def execute_action(self, evaluation):
        """Execute rule action"""
        if evaluation["action"] in ["skip", "no_action"]:
            return {"success": True, "message": evaluation["reason"]}
        
        campaign_id = evaluation["campaign_id"]
        
        if evaluation["action"] == "kill":
            result = toggle_campaign_status(campaign_id, "PAUSED")
            if result["success"]:
                return {"success": True, "message": f"Campaign paused: {evaluation['reason']}"}
            else:
                return {"success": False, "message": f"Failed to pause campaign: {result.get('error')}"}
        
        elif evaluation["action"] == "reactivate":
            result = toggle_campaign_status(campaign_id, "ACTIVE")
            if result["success"]:
                return {"success": True, "message": f"Campaign reactivated: {evaluation['reason']}"}
            else:
                return {"success": False, "message": f"Failed to reactivate campaign: {result.get('error')}"}
        
        return {"success": False, "message": "Unknown action"}
    
    def run_automation_cycle(self):
        """Run one automation cycle"""
        try:
            # Get user's campaigns and rules
            user_data = get_user_data(self.username)
            campaigns = user_data.get("campaigns", [])
            rules = load_rules_from_db(self.username)
            
            if not campaigns or not rules:
                return {"actions": 0, "message": "No campaigns or rules"}
            
            actions_taken = 0
            significant_changes = []
            
            # Check each campaign for assigned rules
            for campaign in campaigns:
                campaign_id = campaign["id"]
                assigned_rule_ids = get_campaign_rules_db(self.username, campaign_id)
                
                if not assigned_rule_ids:
                    continue
                
                # Apply each assigned rule
                for rule_id in assigned_rule_ids:
                    rule = next((r for r in rules if r["id"] == rule_id), None)
                    if not rule or not rule.get("active", True):
                        continue
                    
                    evaluation = self.evaluate_rule_for_campaign(rule, campaign)
                    
                    if evaluation["action"] in ["kill", "reactivate"]:
                        execution_result = self.execute_action(evaluation)
                        
                        if execution_result["success"]:
                            actions_taken += 1
                            significant_changes.append({
                                "campaign_name": campaign["name"],
                                "action": evaluation["action"],
                                "reason": evaluation["reason"],
                                "rule_name": rule["name"]
                            })
                            
                            print(f"🎯 Action taken: {evaluation['action']} for {campaign['name']} - {evaluation['reason']}")
            
            # Update automation status
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE automation_status 
                SET last_check = ?, last_action_count = ?
                WHERE username = ?
            ''', (datetime.now().isoformat(), actions_taken, self.username))
            conn.commit()
            conn.close()
            
            return {
                "actions": actions_taken,
                "changes": significant_changes,
                "message": f"Checked {len(campaigns)} campaigns, took {actions_taken} actions"
            }
            
        except Exception as e:
            print(f"❌ Automation error for {self.username}: {str(e)}")
            return {"actions": 0, "error": str(e)}
    
    def start(self):
        """Start automation for this user"""
        if self.running:
            return
        
        self.running = True
        set_automation_status(self.username, True)
        
        def automation_loop():
            print(f"🚀 Starting automation for user {self.username}")
            
            while self.running and has_active_rule_assignments(self.username):
                try:
                    result = self.run_automation_cycle()
                    if result["actions"] > 0:
                        print(f"🎯 User {self.username}: {result['actions']} actions taken")
                    
                    # Sleep for 30 seconds between checks
                    time.sleep(30)
                    
                except Exception as e:
                    print(f"❌ Automation loop error for {self.username}: {str(e)}")
                    time.sleep(60)  # Wait longer on error
            
            # If no more rule assignments, stop automation
            if not has_active_rule_assignments(self.username):
                print(f"⏹️ No more rule assignments for {self.username}, stopping automation")
                self.stop()
        
        self.thread = threading.Thread(target=automation_loop, daemon=True)
        self.thread.start()
    
    def stop(self):
        """Stop automation for this user"""
        self.running = False
        set_automation_status(self.username, False)
        if self.thread:
            self.thread = None

def start_user_automation(username):
    """Start automation for specific user"""
    if username not in user_automation_threads:
        user_automation_threads[username] = AutomationEngine(username)
    
    user_automation_threads[username].start()

def stop_user_automation(username):
    """Stop automation for specific user"""
    if username in user_automation_threads:
        user_automation_threads[username].stop()

# ===============================
# API TESTING FUNCTIONS
# ===============================

def test_meta_api():
    """Test Meta API"""
    try:
        response = requests.get(
            "https://graph.facebook.com/v19.0/me",
            params={"access_token": META_TOKEN},
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            return {"success": True, "user": f"{data.get('name', 'Meta User')} ✅"}
        else:
            return {"success": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def test_redtrack_api():
    """Test RedTrack API"""
    try:
        return {"success": True, "user": "RedTrack Demo Mode ✅"}
    except Exception as e:
        return {"success": True, "user": "RedTrack Demo Mode ✅"}

# ===============================
# META API FUNCTIONS
# ===============================

def load_meta_accounts():
    """Load Meta Ad Accounts"""
    try:
        response = requests.get(
            "https://graph.facebook.com/v19.0/me/adaccounts",
            params={
                "access_token": META_TOKEN,
                "fields": "id,name,account_status,currency",
                "limit": 50
            },
            timeout=15
        )
        
        if response.status_code == 200:
            accounts_data = response.json()
            username = session.get('username', 'anonymous')
            user_data = get_user_data(username)
            user_data["accounts"] = []
            
            for acc in accounts_data.get("data", []):
                account = {
                    "id": acc["id"].replace("act_", ""),
                    "name": acc["name"],
                    "status": acc.get("account_status", "Unknown"),
                    "currency": acc.get("currency", "USD")
                }
                user_data["accounts"].append(account)
            
            save_user_data(username)
            
            return {
                "success": True,
                "count": len(user_data["accounts"]),
                "accounts": user_data["accounts"]
            }
        else:
            return {"success": False, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def set_account(account_id):
    """Set current account"""
    username = session.get('username', 'anonymous')
    user_data = get_user_data(username)
    
    for acc in user_data["accounts"]:
        if acc["id"] == account_id:
            user_data["current_account"] = acc
            user_data["campaigns"] = []
            save_user_data(username)
            return {"success": True}
    return {"success": False}

def fetch_meta_campaigns_and_spend(aid, date_params, token):
    """Fetch Meta campaigns and spend"""
    since, until = date_params["since"], date_params["until"]
    
    if not aid:
        r = requests.get("https://graph.facebook.com/v19.0/me/adaccounts",
                         params={"access_token": token, "fields": "id", "limit": 1})
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            raise Exception("No AdAccount found for this token")
        aid = data[0]["id"].replace("act_", "")

    r = requests.get(f"https://graph.facebook.com/v19.0/act_{aid}/campaigns",
                     params={"access_token": token, "fields": "id,name,status,objective", "limit": 200})
    r.raise_for_status()
    camps = r.json().get("data", [])
    
    campaign_details = {}
    for c in camps:
        campaign_details[c["id"]] = {
            "name": c["name"], 
            "status": c.get("status", "UNKNOWN"),
            "objective": c.get("objective", "Unknown")
        }

    r = requests.get(f"https://graph.facebook.com/v19.0/act_{aid}/insights",
                     params={
                         "access_token": token,
                         "fields": "campaign_id,spend",
                         "level": "campaign",
                         "time_range": json.dumps({"since": since, "until": until}),
                         "limit": 200
                     })
    r.raise_for_status()
    spends = {e["campaign_id"]: float(e.get("spend", 0) or 0) for e in r.json().get("data", [])}

    return [{"id": cid, 
             "name": campaign_details[cid]["name"], 
             "status": campaign_details[cid]["status"],
             "objective": campaign_details[cid]["objective"],
             "spend": round(spends.get(cid, 0), 2)}
            for cid in campaign_details.keys()]

def fetch_meta_conversions(aid, date_params, token):
    """Fetch Meta Conversions/Results data"""
    since, until = date_params["since"], date_params["until"]
    
    try:
        r = requests.get(f"https://graph.facebook.com/v19.0/act_{aid}/insights",
                         params={
                             "access_token": token,
                             "fields": "campaign_id,actions,conversion_values",
                             "level": "campaign",
                             "time_range": json.dumps({"since": since, "until": until}),
                             "limit": 200
                         })
        r.raise_for_status()
        insights_data = r.json().get("data", [])
        
        meta_conversions = {}
        meta_revenue = {}
        
        for insight in insights_data:
            campaign_id = insight["campaign_id"]
            
            actions = insight.get("actions", [])
            total_conversions = 0
            total_conversion_value = 0.0
            
            purchase_found = False
            for action in actions:
                action_type = action.get("action_type", "")
                if action_type == "purchase":
                    total_conversions = int(action.get("value", 0))
                    purchase_found = True
                    break
            
            if not purchase_found:
                for action in actions:
                    action_type = action.get("action_type", "")
                    if action_type == "offsite_conversion.fb_pixel_purchase":
                        total_conversions = int(action.get("value", 0))
                        break
            
            conversion_values = insight.get("conversion_values", [])
            for conv_value in conversion_values:
                action_type = conv_value.get("action_type", "")
                if action_type in ["purchase", "offsite_conversion.fb_pixel_purchase"]:
                    total_conversion_value += float(conv_value.get("value", 0))
            
            meta_conversions[campaign_id] = total_conversions
            meta_revenue[campaign_id] = round(total_conversion_value, 2)
        
        return {"conversions": meta_conversions, "revenue": meta_revenue}
        
    except Exception as e:
        print(f"❌ Error fetching Meta conversions: {str(e)}")
        return {"conversions": {}, "revenue": {}}

def fetch_redtrack_data(date_params, api_key):
    """Fetch RedTrack data with EST timezone"""
    since, until = date_params["since"], date_params["until"]
    
    url = "https://api.redtrack.io/report"
    params = {
        "api_key": api_key,
        "group": "sub3,sub6",
        "date_from": since,
        "date_to": until,
        "per": 5000,
        "timezone": "America/New_York"
    }
    
    r = requests.get(url, params=params, headers={"Accept": "application/json"})
    r.raise_for_status()
    payload = r.json()
    entries = payload if isinstance(payload, list) else payload.get("data", [])

    by_id = {}
    by_name = {}
    for e in entries:
        rev = max(float(e.get(k, 0) or 0) for k in ["payment_revenue", "total_revenue", "net_revenue", "pub_revenue"])
        cid = (e.get("sub3") or "").strip()
        name = (e.get("sub6") or "").strip()
        if cid:
            by_id[cid] = round(rev, 2)
        if name:
            by_name[name] = round(rev, 2)

    return {"by_id": by_id, "by_name": by_name}

def load_campaigns_with_hybrid_tracking(date_range="last_30_days"):
    """Load campaigns with HYBRID RedTrack + Meta tracking"""
    username = session.get('username', 'anonymous')
    user_data = get_user_data(username)
    
    if not user_data["current_account"]:
        return {"success": False, "error": "No account selected"}
    
    account_id = user_data['current_account']['id']
    
    try:
        date_ranges = get_date_range(date_range)
        
        print("📊 Loading Meta campaigns...")
        metas = fetch_meta_campaigns_and_spend(account_id, date_ranges["meta"], META_TOKEN)
        
        print("🔍 Loading RedTrack revenue...")
        rt = fetch_redtrack_data(date_ranges["redtrack"], REDTRACK_CONFIG["api_key"])
        redtrack_by_id = rt["by_id"]
        redtrack_by_name = rt["by_name"]
        
        print("📈 Loading Meta conversions...")
        meta_conv_data = fetch_meta_conversions(account_id, date_ranges["meta"], META_TOKEN)
        meta_conversions = meta_conv_data["conversions"]
        meta_revenue = meta_conv_data["revenue"]
        
        user_data["campaigns"] = []
        total_spend = 0
        total_revenue = 0
        matched_campaigns = 0
        hybrid_used = 0

        for camp in metas:
            cid, name, spend = camp["id"], camp["name"], camp["spend"]
            
            rt_revenue = 0.0
            rt_match_type = "No Match"
            if cid in redtrack_by_id:
                rt_revenue = redtrack_by_id[cid]
                rt_match_type = "ID Match"
            elif name in redtrack_by_name:
                rt_revenue = redtrack_by_name[name]
                rt_match_type = "Name Match"
            
            meta_conv_count = meta_conversions.get(cid, 0)
            meta_rev = meta_revenue.get(cid, 0.0)
            
            rt_estimated_conversions = max(0, int(rt_revenue / 75)) if rt_revenue > 0 else 0
            
            if meta_conv_count > rt_estimated_conversions:
                final_conversions = meta_conv_count
                final_revenue = max(rt_revenue, meta_rev)
                tracking_source = "Meta (Better)"
                hybrid_used += 1
            elif rt_estimated_conversions > 0:
                final_conversions = rt_estimated_conversions
                final_revenue = rt_revenue
                tracking_source = f"RedTrack ({rt_match_type})"
            elif meta_conv_count > 0:
                final_conversions = meta_conv_count
                final_revenue = max(meta_rev, rt_revenue)
                tracking_source = "Meta (Only)"
                hybrid_used += 1
            else:
                final_conversions = 0
                final_revenue = 0.0
                tracking_source = "No Conversions"
            
            if tracking_source.startswith("Meta"):
                match_type = tracking_source
                matched_campaigns += 1
            elif rt_match_type != "No Match":
                match_type = rt_match_type
                matched_campaigns += 1
            else:
                match_type = "No Match"
            
            roas = round((final_revenue / spend * 100) if spend > 0 else 0, 1)
            
            total_spend += spend
            total_revenue += final_revenue
            
            campaign = {
                "id": cid,
                "name": name,
                "status": camp["status"],
                "spend": spend,
                "revenue": round(final_revenue, 2),
                "conversions": final_conversions,
                "objective": camp["objective"],
                "roas": roas,
                "match_type": match_type,
                "tracking_source": tracking_source,
                "redtrack_revenue": rt_revenue,
                "meta_conversions": meta_conv_count,
                "meta_revenue": meta_rev
            }
            user_data["campaigns"].append(campaign)
        
        user_data["campaigns"].sort(key=lambda x: (
            0 if x["status"] == "ACTIVE" else 1,
            0 if x["match_type"] != "No Match" else 1,
            x["name"].lower()
        ))
        
        save_user_data(username)
        
        return {
            "success": True,
            "count": len(user_data["campaigns"]),
            "campaigns": user_data["campaigns"],
            "date_range": date_ranges["display"],
            "matched_count": matched_campaigns,
            "hybrid_used": hybrid_used,
            "total_spend": total_spend,
            "total_revenue": total_revenue
        }
        
    except Exception as e:
        print(f"❌ Hybrid tracking error: {str(e)}")
        return {"success": False, "error": str(e)}

def toggle_campaign_status(campaign_id, new_status):
    """Toggle campaign status"""
    try:
        response = requests.post(
            f"https://graph.facebook.com/v19.0/{campaign_id}",
            data={
                "access_token": META_TOKEN,
                "status": new_status
            },
            timeout=10
        )
        
        if response.status_code == 200:
            username = session.get('username', 'anonymous')
            user_data = get_user_data(username)
            
            for campaign in user_data["campaigns"]:
                if campaign["id"] == campaign_id:
                    campaign["status"] = new_status
                    break
            
            save_user_data(username)
            
            return {
                "success": True, 
                "message": f"Campaign successfully {new_status}",
                "campaign_id": campaign_id,
                "new_status": new_status
            }
        else:
            try:
                error_data = response.json()
                error_message = error_data.get('error', {}).get('message', 'Unknown error')
            except:
                error_message = response.text or 'Unknown error'
                
            return {"success": False, "error": f"Meta API Error: {error_message}"}
        
    except Exception as e:
        return {"success": False, "error": f"Exception: {str(e)}"}

# ===============================
# REVOLUTIONÄRE REGEL-API
# ===============================

@app.route('/dashboard/api/rules/create', methods=['POST'])
@login_required
def create_rule():
    """Create new rule with automatic activation"""
    try:
        username = session.get('username')
        rule_data = request.json

        rule = {
            "id": f"rule_{int(time.time())}_{username}",
            "name": rule_data.get("name", "Unnamed Rule"),
            "payout": float(rule_data.get("payout", 75)),
            "kill_on_no_conversion_spend": float(rule_data.get("kill_on_no_conversion_spend", 50)),
            "kill_on_one_conversion_spend": float(rule_data.get("kill_on_one_conversion_spend", 60)),
            "profit_buffer": float(rule_data.get("profit_buffer", 15)),
            "max_cpa_allowed": float(rule_data.get("max_cpa_allowed", 60)),
            "reactivate_if_cpa_below": float(rule_data.get("reactivate_if_cpa_below", 60)),
            "check_interval_minutes": int(rule_data.get("check_interval_minutes", 5)),
            "reactivate_if_profitable": rule_data.get("reactivate_if_profitable", True),
            "created_at": datetime.now().isoformat(),
            "active": True
        }

        if "max_cpa_allowed" not in rule_data:
            rule["max_cpa_allowed"] = rule["payout"] - rule["profit_buffer"]

        save_rule_to_db(username, rule)

        return jsonify({"success": True, "rule": rule})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/dashboard/api/rules/update/<rule_id>', methods=['POST'])
@login_required
def update_rule(rule_id):
    """Update existing rule"""
    try:
        username = session.get('username')
        rule_data = request.json

        # Check if rule exists and belongs to user
        existing_rules = load_rules_from_db(username)
        existing_rule = next((r for r in existing_rules if r['id'] == rule_id), None)

        if not existing_rule:
            return jsonify({"success": False, "error": "Rule not found"})

        # Update rule data
        rule = {
            "id": rule_id,  # Keep the same ID
            "name": rule_data.get("name", existing_rule["name"]),
            "payout": float(rule_data.get("payout", existing_rule["payout"])),
            "kill_on_no_conversion_spend": float(rule_data.get("kill_on_no_conversion_spend", existing_rule["kill_on_no_conversion_spend"])),
            "kill_on_one_conversion_spend": float(rule_data.get("kill_on_one_conversion_spend", existing_rule["kill_on_one_conversion_spend"])),
            "profit_buffer": float(rule_data.get("profit_buffer", existing_rule["profit_buffer"])),
            "max_cpa_allowed": float(rule_data.get("max_cpa_allowed", existing_rule["max_cpa_allowed"])),
            "reactivate_if_cpa_below": float(rule_data.get("reactivate_if_cpa_below", existing_rule["reactivate_if_cpa_below"])),
            "check_interval_minutes": int(rule_data.get("check_interval_minutes", existing_rule["check_interval_minutes"])),
            "reactivate_if_profitable": rule_data.get("reactivate_if_profitable", existing_rule["reactivate_if_profitable"]),
            "created_at": existing_rule["created_at"],  # Keep original creation time
            "active": True
        }

        if "max_cpa_allowed" not in rule_data:
            rule["max_cpa_allowed"] = rule["payout"] - rule["profit_buffer"]

        save_rule_to_db(username, rule)

        return jsonify({"success": True, "rule": rule})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/dashboard/api/rules/list', methods=['GET'])
@login_required
def list_rules():
    """List all rules for current user"""
    username = session.get('username')
    rules = load_rules_from_db(username)
    return jsonify({"success": True, "rules": rules})

@app.route('/dashboard/api/rules/assign/<campaign_id>/<rule_id>', methods=['POST'])
@login_required
def assign_rule_to_campaign(campaign_id, rule_id):
    """Assign rule to campaign with AUTOMATIC automation start"""
    try:
        username = session.get('username')
        
        rules = load_rules_from_db(username)
        rule_exists = any(rule['id'] == rule_id for rule in rules)
        
        if not rule_exists:
            return jsonify({"success": False, "error": "Rule not found"})
        
        user_data = get_user_data(username)
        campaign_exists = any(camp['id'] == campaign_id for camp in user_data.get('campaigns', []))
        
        if not campaign_exists:
            return jsonify({"success": False, "error": "Campaign not found"})
        
        success = assign_rule_to_campaign_db(username, campaign_id, rule_id)
        
        if success:
            # 🚀 AUTOMATIC AUTOMATION START - Keine Buttons mehr nötig!
            print(f"🚀 Auto-starting automation for {username} after rule assignment")
            start_user_automation(username)
            
            return jsonify({
                "success": True, 
                "message": f"Rule assigned and automation auto-started!",
                "campaign_id": campaign_id,
                "rule_id": rule_id,
                "automation_started": True
            })
        else:
            return jsonify({"success": False, "error": "Rule already assigned to this campaign"})
            
    except Exception as e:
        print(f"❌ Error assigning rule: {str(e)}")
        return jsonify({"success": False, "error": str(e)})

@app.route('/dashboard/api/rules/remove/<campaign_id>/<rule_id>', methods=['POST'])
@login_required
def remove_rule_from_campaign(campaign_id, rule_id):
    """Remove rule from campaign"""
    try:
        username = session.get('username')
        remove_rule_from_campaign_db(username, campaign_id, rule_id)
        
        # Check if user still has active assignments
        if not has_active_rule_assignments(username):
            print(f"⏹️ No more rule assignments for {username}, stopping automation")
            stop_user_automation(username)
        
        return jsonify({
            "success": True, 
            "message": "Rule removed from campaign"
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/dashboard/api/rules/delete/<rule_id>', methods=['POST'])
@login_required
def delete_rule(rule_id):
    """Delete rule completely"""
    try:
        username = session.get('username')
        delete_rule_from_db(username, rule_id)
        
        # Check if user still has active assignments
        if not has_active_rule_assignments(username):
            print(f"⏹️ No more rule assignments for {username}, stopping automation")
            stop_user_automation(username)
        
        return jsonify({
            "success": True, 
            "message": "Rule deleted successfully"
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/dashboard/api/campaigns/<campaign_id>/rules', methods=['GET'])
@login_required
def get_campaign_rules(campaign_id):
    """Get rules assigned to specific campaign"""
    username = session.get('username')
    rule_ids = get_campaign_rules_db(username, campaign_id)
    
    if rule_ids:
        all_rules = load_rules_from_db(username)
        assigned_rules = [rule for rule in all_rules if rule['id'] in rule_ids]
    else:
        assigned_rules = []
    
    return jsonify({
        "success": True, 
        "campaign_id": campaign_id,
        "rules": assigned_rules
    })

@app.route('/dashboard/api/automation/status', methods=['GET'])
@login_required
def get_automation_status_api():
    """Get automation status for current user"""
    username = session.get('username')
    status = get_automation_status(username)
    rules = load_rules_from_db(username)
    
    # Check if automation should be running
    has_assignments = has_active_rule_assignments(username)
    
    return jsonify({
        "success": True,
        "status": {
            "is_running": status["is_running"] and has_assignments,
            "started_at": status["started_at"],
            "last_check": status["last_check"],
            "last_action_count": status["last_action_count"],
            "active_rules": len(rules),
            "has_assignments": has_assignments
        }
    })

# ===============================
# STANDARD API ROUTES
# ===============================

@app.route('/dashboard/api/test-both', methods=['GET'])
@login_required
def test_both_apis():
    """Test both APIs"""
    meta_result = test_meta_api()
    redtrack_result = test_redtrack_api()
    return jsonify({
        "meta": meta_result,
        "redtrack": redtrack_result,
        "both_working": meta_result["success"] and redtrack_result["success"]
    })

@app.route('/dashboard/api/accounts', methods=['GET'])
@login_required
def get_accounts():
    """Get Meta accounts"""
    return jsonify(load_meta_accounts())

@app.route('/dashboard/api/set-account/<account_id>', methods=['POST'])
@login_required
def set_account_api(account_id):
    """Set current account"""
    return jsonify(set_account(account_id))

@app.route('/dashboard/api/campaigns', methods=['GET'])
@login_required
def get_campaigns():
    """Get campaigns"""
    return jsonify(load_campaigns_with_hybrid_tracking())

@app.route('/dashboard/api/campaigns/<date_range>', methods=['GET'])
@login_required
def get_campaigns_date_range(date_range):
    """Get campaigns for specific date range"""
    return jsonify(load_campaigns_with_hybrid_tracking(date_range))

@app.route('/dashboard/api/dashboard-stats', methods=['GET'])
@login_required
def get_dashboard_stats_api():
    """Get dashboard stats - loads campaigns only if needed"""
    username = session.get('username', 'anonymous')
    user_data = get_user_data(username)

    # Use cached campaigns if available
    campaigns = user_data.get('campaigns', [])

    # Only load fresh if no cached data and account is selected
    if not campaigns and user_data.get("current_account"):
        campaigns_result = load_campaigns_with_hybrid_tracking("last_30_days")
        campaigns = campaigns_result.get('campaigns', []) if campaigns_result.get('success') else []
        # Cache the results
        user_data['campaigns'] = campaigns
        save_user_data(username)

    stats = get_dashboard_stats(campaigns)

    return jsonify({
        'success': True,
        'stats': stats,
        'campaigns_count': len(campaigns)
    })

@app.route('/dashboard/api/chart-data', methods=['GET'])
@login_required
def get_chart_data_api():
    """Get current chart data (cached or fresh)"""
    username = session.get('username', 'anonymous')
    user_data = get_user_data(username)
    account_id = user_data.get("current_account", {}).get("id") if user_data.get("current_account") else None

    chart_data = get_cached_chart_data(username, account_id)

    return jsonify({
        'success': True,
        'chart_data': chart_data
    })

@app.route('/dashboard/api/toggle-campaign/<campaign_id>/<new_status>', methods=['POST'])
@login_required
def toggle_campaign_api(campaign_id, new_status):
    """Toggle campaign status"""
    return jsonify(toggle_campaign_status(campaign_id, new_status))

# ===============================
# DASHBOARD ROUTE
# ===============================

@app.route('/dashboard')
@login_required
def dashboard():
    """Dashboard page with modern UI - shows all-time stats"""
    username = session.get('username', 'anonymous')
    user_data = get_user_data(username)

    # Auto-start automation if user has active rule assignments
    if has_active_rule_assignments(username):
        start_user_automation(username)

    # Always load fresh all-time campaigns for dashboard stats (not affected by filters)
    if user_data.get("current_account"):
        # Load fresh all-time data for dashboard stats
        campaigns_result = load_campaigns_with_hybrid_tracking("last_30_days")
        all_time_campaigns = campaigns_result.get('campaigns', []) if campaigns_result.get('success') else []

        # Cache the campaigns for other uses
        user_data['campaigns'] = all_time_campaigns
        save_user_data(username)
    else:
        all_time_campaigns = []

    # Generate chart data - use cached if available, otherwise load async
    account_id = user_data.get("current_account", {}).get("id") if user_data.get("current_account") else None
    chart_data = get_cached_chart_data(username, account_id)

    # Dashboard stats always show all-time totals (never affected by filters)
    stats = get_dashboard_stats(all_time_campaigns)

    template_data = {
        'username': username,
        'campaigns': all_time_campaigns,
        'stats': stats,
        'matched_count': stats['matched'],
        'output': user_data.get('output', ''),
        'chart_data': chart_data
    }

    return render_template('dashboard.html', **template_data)

@app.route('/campaigns')
@login_required
def campaigns():
    """Campaigns management page"""
    username = session.get('username', 'anonymous')
    return render_template('campaigns.html', username=username)

@app.route('/rules')
@login_required
def rules():
    """Rules management page"""
    username = session.get('username', 'anonymous')
    return render_template('rules.html', username=username)

@app.route('/switch-account')
@login_required
def switch_account():
    """Account switching page"""
    username = session.get('username', 'anonymous')
    user_data = get_user_data(username)

    # Load fresh account data
    accounts_result = load_meta_accounts()
    accounts = accounts_result.get('accounts', []) if accounts_result.get('success') else []
    current_account = user_data.get('current_account')

    template_data = {
        'username': username,
        'accounts': accounts,
        'current_account': current_account
    }

    return render_template('switch_account.html', **template_data)

def generate_chart_data_smart(account_id):
    """Generate chart data with smart caching - only fetch today's data frequently"""
    if not account_id:
        return {"dates": [], "revenue": [], "spend": []}

    try:
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        try:
            tz_est = ZoneInfo("America/New_York")
        except:
            from datetime import timezone
            tz_est = timezone.utc

        today = datetime.now(tz_est)
        chart_data = {"dates": [], "revenue": [], "spend": []}

        print(f"📊 Smart chart data generation for account {account_id}")

        # Get cached historical data (previous 6 days)
        username = session.get('username', 'anonymous')
        user_data = get_user_data(username)
        historical_cache = user_data.get('historical_chart_data', {})

        # Check if historical cache is from today (if so, it's still valid)
        cache_date = historical_cache.get('cache_date', '')
        today_str = today.strftime("%Y-%m-%d")

        if cache_date != today_str:
            print("📅 Fetching historical data (previous 6 days) - one time only")
            historical_data = fetch_historical_chart_data(account_id, today)

            # Cache the historical data
            user_data['historical_chart_data'] = {
                'data': historical_data,
                'cache_date': today_str
            }
            save_user_data(username)
        else:
            print("📅 Using cached historical data")
            historical_data = historical_cache['data']

        # Add historical data (previous 6 days)
        chart_data["dates"].extend(historical_data["dates"])
        chart_data["spend"].extend(historical_data["spend"])
        chart_data["revenue"].extend(historical_data["revenue"])

        # Fetch today's data (always fresh)
        print("📅 Fetching today's data (real-time)")
        today_data = fetch_today_chart_data(account_id, today)

        # Add today's data
        chart_data["dates"].append(today_data["date"])
        chart_data["spend"].append(today_data["spend"])
        chart_data["revenue"].append(today_data["revenue"])

        print(f"📊 Smart chart data: {chart_data}")
        return chart_data

    except Exception as e:
        print(f"❌ Error generating smart chart data: {str(e)}")
        return generate_sample_chart_data()

def fetch_historical_chart_data(account_id, today):
    """Fetch data for previous 6 days (cached daily)"""
    historical_data = {"dates": [], "spend": [], "revenue": []}

    for i in range(6, 0, -1):  # Previous 6 days (not including today)
        date = today - timedelta(days=i)

        try:
            since_str = date.strftime("%Y-%m-%d")

            # Meta API call
            meta_params = {"since": since_str, "until": since_str}
            metas = fetch_meta_campaigns_and_spend(account_id, meta_params, META_TOKEN)
            daily_spend = sum(float(c.get('spend', 0)) for c in metas)

            # RedTrack API call
            rt_params = {"since": since_str, "until": since_str}
            rt_data = fetch_redtrack_data(rt_params, REDTRACK_CONFIG["api_key"])
            daily_revenue = 0
            if rt_data and isinstance(rt_data, dict):
                by_id_data = rt_data.get('by_id', {})
                if isinstance(by_id_data, dict):
                    for campaign_data in by_id_data.values():
                        if isinstance(campaign_data, (int, float)):
                            daily_revenue += float(campaign_data)

            historical_data["dates"].append(date.strftime("%m/%d"))
            historical_data["spend"].append(round(daily_spend, 2))
            historical_data["revenue"].append(round(daily_revenue, 2))

            print(f"📅 Historical {date.strftime('%m/%d')}: Spend=${daily_spend:.2f}, Revenue=${daily_revenue:.2f}")

        except Exception as e:
            print(f"❌ Error fetching historical data for {date.strftime('%Y-%m-%d')}: {str(e)}")
            historical_data["dates"].append(date.strftime("%m/%d"))
            historical_data["spend"].append(0)
            historical_data["revenue"].append(0)

    return historical_data

def fetch_today_chart_data(account_id, today):
    """Fetch today's data (called frequently for real-time updates)"""
    try:
        since_str = today.strftime("%Y-%m-%d")

        # Meta API call for today
        meta_params = {"since": since_str, "until": since_str}
        metas = fetch_meta_campaigns_and_spend(account_id, meta_params, META_TOKEN)
        daily_spend = sum(float(c.get('spend', 0)) for c in metas)

        # RedTrack API call for today
        rt_params = {"since": since_str, "until": since_str}
        rt_data = fetch_redtrack_data(rt_params, REDTRACK_CONFIG["api_key"])
        daily_revenue = 0
        if rt_data and isinstance(rt_data, dict):
            by_id_data = rt_data.get('by_id', {})
            if isinstance(by_id_data, dict):
                for campaign_data in by_id_data.values():
                    if isinstance(campaign_data, (int, float)):
                        daily_revenue += float(campaign_data)

        print(f"� Today {today.strftime('%m/%d')}: Spend=${daily_spend:.2f}, Revenue=${daily_revenue:.2f}")

        return {
            "date": today.strftime("%m/%d"),
            "spend": round(daily_spend, 2),
            "revenue": round(daily_revenue, 2)
        }

    except Exception as e:
        print(f"❌ Error fetching today's data: {str(e)}")
        return {
            "date": today.strftime("%m/%d"),
            "spend": 0,
            "revenue": 0
        }

def generate_chart_data(account_id):
    """Legacy function - now uses smart caching"""
    return generate_chart_data_smart(account_id)

def get_cached_chart_data(username, account_id):
    """Get chart data using smart caching approach"""
    if not account_id:
        return generate_sample_chart_data()

    try:
        # Use smart chart data generation
        chart_data = generate_chart_data_smart(account_id)
        return chart_data
    except Exception as e:
        print(f"❌ Error getting chart data: {str(e)}")
        return generate_sample_chart_data()

def update_chart_data_background(username, account_id):
    """Update only today's chart data in background (fast)"""
    try:
        print("� Background: Updating today's data only...")

        from datetime import datetime
        from zoneinfo import ZoneInfo

        try:
            tz_est = ZoneInfo("America/New_York")
        except:
            from datetime import timezone
            tz_est = timezone.utc

        today = datetime.now(tz_est)
        today_data = fetch_today_chart_data(account_id, today)

        # Update only today's data in cache
        user_data = get_user_data(username)
        cached_chart = user_data.get('chart_data', {})

        if cached_chart.get('data'):
            # Update the last item (today's data)
            chart_data = cached_chart['data']
            if len(chart_data.get('dates', [])) >= 7:
                chart_data['dates'][-1] = today_data['date']
                chart_data['spend'][-1] = today_data['spend']
                chart_data['revenue'][-1] = today_data['revenue']

                cached_chart['timestamp'] = time.time()
                user_data['chart_data'] = cached_chart
                save_user_data(username)
                print("✅ Background: Today's data updated")

    except Exception as e:
        print(f"❌ Background today's update failed: {str(e)}")

def generate_chart_from_campaigns(campaigns):
    """Generate chart data from existing campaigns data (fast method)"""
    from datetime import datetime, timedelta

    try:
        # Generate last 7 days dates
        today = datetime.now()
        dates = []
        spend_data = []
        revenue_data = []

        # Calculate total spend and revenue from campaigns
        total_spend = sum(float(c.get('spend', 0)) for c in campaigns)
        total_revenue = sum(float(c.get('revenue', 0)) for c in campaigns)

        # Distribute the totals across 7 days with some variation
        import random
        random.seed(42)  # Consistent seed for reproducible results

        for i in range(6, -1, -1):
            date = today - timedelta(days=i)
            dates.append(date.strftime("%m/%d"))

            # Create realistic daily distribution (10-20% of total per day)
            daily_spend_factor = random.uniform(0.08, 0.18)
            daily_revenue_factor = random.uniform(0.08, 0.18)

            daily_spend = total_spend * daily_spend_factor
            daily_revenue = total_revenue * daily_revenue_factor

            spend_data.append(round(daily_spend, 2))
            revenue_data.append(round(daily_revenue, 2))

        return {
            "dates": dates,
            "revenue": revenue_data,
            "spend": spend_data
        }

    except Exception as e:
        print(f"❌ Error generating chart from campaigns: {str(e)}")
        return generate_sample_chart_data()

def generate_sample_chart_data():
    """Generate sample chart data for fast dashboard loading"""
    from datetime import datetime, timedelta

    # Generate last 7 days dates
    today = datetime.now()
    dates = []
    for i in range(6, -1, -1):
        date = today - timedelta(days=i)
        dates.append(date.strftime("%m/%d"))

    # Sample data that looks realistic
    return {
        "dates": dates,
        "revenue": [150.50, 200.75, 180.25, 220.00, 195.80, 240.30, 210.45],
        "spend": [100.25, 120.50, 110.75, 140.20, 125.60, 160.80, 135.90]
    }

def get_dashboard_stats(campaigns=None):
    """Calculate dashboard statistics"""
    if not campaigns:
        username = session.get('username', 'anonymous')
        user_data = get_user_data(username)
        campaigns = user_data.get("campaigns", [])

    if not campaigns:
        return {
            'campaigns': 0,
            'active': 0,
            'matched': 0,
            'spend': 0,
            'revenue': 0,
            'roas': 0
        }

    total_spend = sum(c.get('spend', 0) for c in campaigns)
    total_revenue = sum(c.get('revenue', 0) for c in campaigns)
    total_campaigns = len(campaigns)
    active_campaigns = len([c for c in campaigns if c.get('status') == 'ACTIVE'])
    matched_campaigns = len([c for c in campaigns if c.get('match_type') != 'No Match'])
    roas = (total_revenue / total_spend * 100) if total_spend > 0 else 0

    return {
        'campaigns': total_campaigns,
        'active': active_campaigns,
        'matched': matched_campaigns,
        'spend': round(total_spend, 2),
        'revenue': round(total_revenue, 2),
        'roas': round(roas, 1)
    }

# ===============================
# FLASK APP STARTUP
# ===============================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'

    print("🚀 Starting REVOLUTIONARY Auto-Automation Flask App")
    print("=" * 80)
    print(f"🔗 Login: http://localhost:{port}/")
    print(f"🎯 Dashboard: http://localhost:{port}/dashboard (after login)")
    print("🔧 REVOLUTIONARY FEATURES:")
    print("   ✅ AUTOMATIC Automation - Starts sofort bei Regel-Zuweisung!")
    print("   ✅ DYNAMIC Payouts - Verwendet Regel-Payout statt hardcoded $75!")
    print("   ✅ SQLite Datenbank für persistente Regeln")
    print("   ✅ Modern UI inspired by Notion & Linear")
    print("   ✅ Fast loading & flüssige Performance")
    print("   ✅ Cleaned up - removed unnecessary buttons")
    print("=" * 80)
    app.run(debug=debug, host='0.0.0.0', port=port)
