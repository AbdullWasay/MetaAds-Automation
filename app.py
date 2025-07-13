from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import subprocess
import sys
import requests
import json
import threading
import time
import os
import pickle
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, DuplicateKeyError
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-to-something-secure')

# ===============================
# MONGODB CONFIGURATION
# ===============================

# MongoDB connection string
MONGODB_URI = "mongodb+srv://wasay:mongodb308@cluster0.etvipre.mongodb.net/MetaAds"

# Initialize MongoDB client
try:
    mongo_client = MongoClient(MONGODB_URI)
    # Test the connection
    mongo_client.admin.command('ping')
    print("✅ MongoDB connection successful!")

    # Get database
    db = mongo_client.MetaAds

    # Collections
    rules_collection = db.rules
    campaign_rules_collection = db.campaign_rules
    campaign_status_collection = db.campaign_status
    automation_status_collection = db.automation_status

except ConnectionFailure as e:
    print(f"❌ MongoDB connection failed: {e}")
    raise

# ===============================
# MONGODB COLLECTIONS SETUP
# ===============================

def init_mongodb():
    """Initialize MongoDB collections and indexes"""
    try:
        # Create indexes for better performance

        # Rules collection indexes
        rules_collection.create_index([("username", 1), ("active", 1)])
        rules_collection.create_index("id", unique=True)

        # Campaign rules collection indexes
        campaign_rules_collection.create_index([("username", 1), ("campaign_id", 1), ("rule_id", 1)], unique=True)
        campaign_rules_collection.create_index([("username", 1)])

        # Campaign status collection indexes
        campaign_status_collection.create_index([("username", 1), ("campaign_id", 1)], unique=True)
        campaign_status_collection.create_index([("username", 1)])

        # Automation status collection indexes
        automation_status_collection.create_index("username", unique=True)

        print("✅ MongoDB collections and indexes initialized!")

    except Exception as e:
        print(f"⚠️ MongoDB initialization warning: {e}")

# Initialize MongoDB on startup
init_mongodb()

def save_rule_to_db(username, rule):
    """Save rule to MongoDB"""
    try:
        rule_doc = {
            'id': rule['id'],
            'username': username,
            'name': rule['name'],
            'payout': rule['payout'],
            'created_at': rule['created_at'],
            'active': rule['active'],
            'rule_type': rule.get('rule_type', 'chained'),  # All rules are chained now
            'chain_logic': rule.get('chain_logic', [])  # Array of chained conditions
        }

        # Add legacy fields only if they exist (for backward compatibility)
        if 'kill_on_no_conversion_spend' in rule:
            rule_doc['kill_on_no_conversion_spend'] = rule['kill_on_no_conversion_spend']
        if 'kill_on_one_conversion_spend' in rule:
            rule_doc['kill_on_one_conversion_spend'] = rule['kill_on_one_conversion_spend']
        if 'profit_buffer' in rule:
            rule_doc['profit_buffer'] = rule['profit_buffer']
        if 'max_cpa_allowed' in rule:
            rule_doc['max_cpa_allowed'] = rule['max_cpa_allowed']
        if 'reactivate_if_cpa_below' in rule:
            rule_doc['reactivate_if_cpa_below'] = rule['reactivate_if_cpa_below']
        if 'check_interval_minutes' in rule:
            rule_doc['check_interval_minutes'] = rule['check_interval_minutes']
        if 'reactivate_if_profitable' in rule:
            rule_doc['reactivate_if_profitable'] = rule['reactivate_if_profitable']

        # Use upsert to replace if exists
        rules_collection.replace_one(
            {'id': rule['id']},
            rule_doc,
            upsert=True
        )

    except Exception as e:
        print(f"Error saving rule to MongoDB: {e}")
        raise

def load_rules_from_db(username):
    """Load rules from MongoDB"""
    try:
        # Load all rules for the user (no active filter since deleted rules are completely removed)
        cursor = rules_collection.find({
            'username': username
        })

        rules = []
        for doc in cursor:
            rule = {
                'id': doc['id'],
                'name': doc['name'],
                'payout': doc['payout'],
                'created_at': doc['created_at'],
                'active': doc.get('active', True),  # Default to True for backward compatibility
                'rule_type': doc.get('rule_type', 'chained'),  # Default to chained
                'chain_logic': doc.get('chain_logic', [])
            }

            # Add legacy fields only if they exist (for backward compatibility)
            if 'kill_on_no_conversion_spend' in doc:
                rule['kill_on_no_conversion_spend'] = doc['kill_on_no_conversion_spend']
            if 'kill_on_one_conversion_spend' in doc:
                rule['kill_on_one_conversion_spend'] = doc['kill_on_one_conversion_spend']
            if 'profit_buffer' in doc:
                rule['profit_buffer'] = doc['profit_buffer']
            if 'max_cpa_allowed' in doc:
                rule['max_cpa_allowed'] = doc['max_cpa_allowed']
            if 'reactivate_if_cpa_below' in doc:
                rule['reactivate_if_cpa_below'] = doc['reactivate_if_cpa_below']
            if 'check_interval_minutes' in doc:
                rule['check_interval_minutes'] = doc['check_interval_minutes']
            if 'reactivate_if_profitable' in doc:
                rule['reactivate_if_profitable'] = doc['reactivate_if_profitable']

            rules.append(rule)

        return rules

    except Exception as e:
        print(f"Error loading rules from MongoDB: {e}")
        return []

def assign_rule_to_campaign_db(username, campaign_id, rule_id):
    """Assign rule to campaign in MongoDB"""
    try:
        assignment_doc = {
            'username': username,
            'campaign_id': campaign_id,
            'rule_id': rule_id,
            'assigned_at': datetime.now().isoformat()
        }

        campaign_rules_collection.insert_one(assignment_doc)
        return True

    except DuplicateKeyError:
        # Rule already assigned
        return False
    except Exception as e:
        print(f"Error assigning rule to campaign: {e}")
        return False

def remove_rule_from_campaign_db(username, campaign_id, rule_id):
    """Remove rule from campaign in MongoDB"""
    try:
        campaign_rules_collection.delete_one({
            'username': username,
            'campaign_id': campaign_id,
            'rule_id': rule_id
        })
    except Exception as e:
        print(f"Error removing rule from campaign: {e}")

def get_campaign_rules_db(username, campaign_id):
    """Get rules assigned to campaign"""
    try:
        cursor = campaign_rules_collection.find({
            'username': username,
            'campaign_id': campaign_id
        })

        return [doc['rule_id'] for doc in cursor]

    except Exception as e:
        print(f"Error getting campaign rules: {e}")
        return []

def delete_rule_from_db(username, rule_id):
    """Delete rule completely from MongoDB"""
    try:
        # Delete rule completely from database
        rules_collection.delete_one({
            'username': username,
            'id': rule_id
        })

        # Remove all campaign assignments
        campaign_rules_collection.delete_many({
            'username': username,
            'rule_id': rule_id
        })

    except Exception as e:
        print(f"Error deleting rule: {e}")

def has_active_rule_assignments(username):
    """Check if user has any active rule assignments"""
    try:
        count = campaign_rules_collection.count_documents({
            'username': username
        })

        return count > 0

    except Exception as e:
        print(f"Error checking rule assignments: {e}")
        return False

def set_automation_status(username, is_running):
    """Set automation status for user"""
    try:
        if is_running:
            automation_status_collection.replace_one(
                {'username': username},
                {
                    'username': username,
                    'is_running': True,
                    'started_at': datetime.now().isoformat(),
                    'last_check': datetime.now().isoformat(),
                    'last_action_count': 0
                },
                upsert=True
            )
        else:
            automation_status_collection.update_one(
                {'username': username},
                {'$set': {'is_running': False}}
            )
    except Exception as e:
        print(f"Error setting automation status: {e}")

def get_automation_status(username):
    """Get automation status for user"""
    try:
        result = automation_status_collection.find_one({'username': username})

        if result:
            return {
                'is_running': result.get('is_running', False),
                'started_at': result.get('started_at'),
                'last_check': result.get('last_check'),
                'last_action_count': result.get('last_action_count', 0)
            }
        else:
            return {
                'is_running': False,
                'started_at': None,
                'last_check': None,
                'last_action_count': 0
            }
    except Exception as e:
        print(f"Error getting automation status: {e}")
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
            session['first_dashboard_visit'] = True  # Flag for first dashboard visit
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
# USER DATA MANAGEMENT & ACTIVITY LOGGING
# ===============================

user_data_store = {}

def log_activity(username, activity_type, title, description, icon="system", badge="info"):
    """Log user activity for Recent Activity section"""
    user_data = get_user_data(username)

    if "activities" not in user_data:
        user_data["activities"] = []

    activity = {
        "id": str(uuid.uuid4()),
        "type": activity_type,
        "title": title,
        "description": description,
        "icon": icon,  # system, rule, campaign, play, pause
        "badge": badge,  # success, warning, info, error
        "timestamp": datetime.now().isoformat(),
        "time_ago": "Just now"
    }

    # Add to beginning of list (most recent first)
    user_data["activities"].insert(0, activity)

    # Keep only last 20 activities
    user_data["activities"] = user_data["activities"][:20]

    save_user_data(username)
    print(f"📝 Activity logged for {username}: {title}")

def get_recent_activities(username, limit=10):
    """Get recent activities for a user"""
    user_data = get_user_data(username)
    activities = user_data.get("activities", [])

    # Update time_ago for each activity
    for activity in activities:
        try:
            activity_time = datetime.fromisoformat(activity["timestamp"])
            time_diff = datetime.now() - activity_time

            if time_diff.total_seconds() < 60:
                activity["time_ago"] = "Just now"
            elif time_diff.total_seconds() < 3600:
                minutes = int(time_diff.total_seconds() / 60)
                activity["time_ago"] = f"{minutes} min ago"
            elif time_diff.total_seconds() < 86400:
                hours = int(time_diff.total_seconds() / 3600)
                activity["time_ago"] = f"{hours} hour{'s' if hours > 1 else ''} ago"
            else:
                days = int(time_diff.total_seconds() / 86400)
                activity["time_ago"] = f"{days} day{'s' if days > 1 else ''} ago"
        except:
            activity["time_ago"] = "Unknown"

    return activities[:limit]

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
        "analysis": {},
        "cached_data": {
            "campaigns": [],
            "rules": [],
            "dashboard_stats": {},
            "last_refresh": None
        }
    }

def is_data_fresh(username, max_age_minutes=5):
    """Check if cached data is still fresh"""
    user_data = get_user_data(username)
    last_refresh = user_data["cached_data"].get("last_refresh")

    if not last_refresh:
        return False

    try:
        last_refresh_time = datetime.fromisoformat(last_refresh)
        age_minutes = (datetime.now() - last_refresh_time).total_seconds() / 60
        return age_minutes < max_age_minutes
    except:
        return False

def refresh_all_data(username, force=False, date_range="last_30_days"):
    """Refresh all data for a user - FIXED to support date range filtering"""
    try:
        user_data = get_user_data(username)

        # Ensure cached_data structure exists
        if "cached_data" not in user_data:
            user_data["cached_data"] = {
                "campaigns": [],
                "rules": [],
                "dashboard_stats": {},
                "last_refresh": None
            }
            save_user_data(username)

        # For non-default date ranges, always fetch fresh data
        if date_range != "last_30_days":
            force = True
            print(f"🔄 Forcing refresh for date range: {date_range}")

        # Check if refresh is needed
        if not force and is_data_fresh(username):
            print(f"📋 Using cached data for {username} (still fresh)")
            return user_data["cached_data"]

        if not user_data.get("current_account"):
            print(f"❌ No account selected for {username}")
            return user_data["cached_data"]
    except Exception as e:
        print(f"❌ Error in refresh_all_data setup: {e}")
        return {
            "campaigns": [],
            "rules": [],
            "dashboard_stats": {},
            "last_refresh": None
        }

    account_id = user_data['current_account']['id']

    try:
        print(f"🔄 Refreshing all data for {username} with date range: {date_range}...")

        # Get date ranges based on the requested date range
        date_ranges = get_date_range(date_range)

        # Single API call to get all campaign data
        print("📊 Loading Meta campaigns...")
        metas = fetch_meta_campaigns_and_spend(account_id, date_ranges["meta"], META_TOKEN)

        print("🔍 CRITICAL: Loading RedTrack revenue...")
        rt = fetch_redtrack_data(date_ranges["redtrack"], REDTRACK_CONFIG["api_key"])
        redtrack_by_id = rt["by_id"]
        redtrack_by_name = rt["by_name"]
        redtrack_error = rt.get("error", None)

        if redtrack_error:
            print(f"❌ CRITICAL: RedTrack API Failed: {redtrack_error}")
        else:
            print(f"✅ CRITICAL: RedTrack API Success - {len(redtrack_by_id)} campaigns")

        print("📈 Loading Meta conversions...")
        meta_conv_data = fetch_meta_conversions(account_id, date_ranges["meta"], META_TOKEN)
        meta_conversions = meta_conv_data["conversions"]
        meta_revenue = meta_conv_data["revenue"]

        # Process campaigns with all data
        campaigns = []
        total_spend = 0
        total_revenue = 0
        matched_campaigns = 0
        hybrid_used = 0

        print(f"🔄 Processing {len(metas)} campaigns with accurate data matching...")
        print(f"🔄 RedTrack API Status: {'FAILED' if redtrack_error else 'SUCCESS'}")

        for meta_campaign in metas:
            cid = meta_campaign["id"]
            name = meta_campaign["name"]
            spend = float(meta_campaign["spend"])  # Ensure float conversion
            status = meta_campaign["status"]
            objective = meta_campaign["objective"]

            print(f"📊 Processing Campaign: {name} (ID: {cid})")
            print(f"   💰 Meta Spend: ${spend}")

            # CRITICAL: Production-grade revenue tracking with error detection
            rt_revenue = 0
            match_type = "No Match"
            redtrack_api_failed = redtrack_error is not None

            if redtrack_api_failed:
                print(f"   ⚠️ CRITICAL: RedTrack API Failed - {redtrack_error}")
                match_type = "RedTrack API Error"
            else:
                # Try ID match first (most accurate)
                if cid in redtrack_by_id:
                    rt_revenue = float(redtrack_by_id[cid])
                    match_type = "ID Match"
                    print(f"   ✅ RedTrack ID Match: ${rt_revenue}")
                # Try name match as fallback
                elif name in redtrack_by_name:
                    rt_revenue = float(redtrack_by_name[name])
                    match_type = "Name Match"
                    print(f"   ✅ RedTrack Name Match: ${rt_revenue}")
                else:
                    print(f"   ❌ No RedTrack match found")

            # Get Meta revenue (separate data source, not fallback)
            meta_rev = float(meta_revenue.get(cid, 0))
            if meta_rev > 0:
                print(f"   💰 Meta Revenue: ${meta_rev}")

            # CRITICAL: Production revenue logic - NO FAKE DATA
            if redtrack_api_failed:
                # RedTrack API completely failed - use Meta but flag as incomplete
                revenue = meta_rev
                revenue_source = "Meta (RedTrack API Failed)"
                print(f"   ⚠️ USING META DUE TO REDTRACK FAILURE: ${revenue}")
            elif rt_revenue > 0:
                # RedTrack has data - primary source
                revenue = rt_revenue
                revenue_source = "RedTrack"
                print(f"   🎯 Using RedTrack revenue: ${revenue}")
                hybrid_used += 1
            elif meta_rev > 0:
                # Only Meta has data
                revenue = meta_rev
                revenue_source = "Meta Only"
                print(f"   🎯 Using Meta revenue only: ${revenue}")
            else:
                # No revenue data from any source
                revenue = 0
                revenue_source = "No Data Available"
                print(f"   ❌ NO REVENUE DATA FROM ANY SOURCE")

            if match_type != "No Match" or revenue > 0:
                matched_campaigns += 1

            # Get conversions with validation
            conversions = int(meta_conversions.get(cid, 0))
            print(f"   🎯 Meta Conversions: {conversions}")

            # FIXED: More accurate metric calculations
            cpa = round(spend / conversions, 2) if conversions > 0 else 0
            roas = round(revenue / spend, 2) if spend > 0 else 0
            profit = round(revenue - spend, 2)

            print(f"   📈 Calculated Metrics: CPA=${cpa}, ROAS={roas}, Profit=${profit}")

            campaign_data = {
                "id": cid,
                "name": name,
                "spend": round(spend, 2),  # Ensure proper rounding
                "revenue": round(revenue, 2),
                "profit": profit,
                "conversions": conversions,
                "cpa": cpa,
                "roas": roas,
                "status": status,
                "objective": objective,
                "match_type": match_type,
                "revenue_source": revenue_source,
                "redtrack_api_error": redtrack_error  # CRITICAL: Include API status
            }

            campaigns.append(campaign_data)
            total_spend += spend
            total_revenue += revenue

            print(f"   ✅ Campaign processed successfully")
            print("   " + "="*50)

        # Sort campaigns
        campaigns.sort(key=lambda x: (
            0 if x["status"] == "ACTIVE" else 1,
            0 if x["match_type"] != "No Match" else 1,
            x["name"].lower()
        ))

        # Load rules
        rules = load_rules_from_db(username)

        # Calculate dashboard stats
        dashboard_stats = get_dashboard_stats(campaigns)

        # REMOVED: Chart data generation (causing delays)

        # Cache everything
        user_data["cached_data"] = {
            "campaigns": campaigns,
            "rules": rules,
            "dashboard_stats": dashboard_stats,
            "last_refresh": datetime.now().isoformat(),
            "total_spend": total_spend,
            "total_revenue": total_revenue,
            "matched_campaigns": matched_campaigns,
            "hybrid_used": hybrid_used
        }

        # Also update the main campaigns for backward compatibility
        user_data["campaigns"] = campaigns
        save_user_data(username)

        print(f"✅ Data refreshed for {username}: {len(campaigns)} campaigns, {len(rules)} rules")
        return user_data["cached_data"]

    except Exception as e:
        print(f"❌ Error refreshing data for {username}: {str(e)}")
        return user_data["cached_data"]

# ===============================
# API CONFIGURATION
# ===============================

META_TOKEN = os.environ.get('META_TOKEN', "EAAO4jYfx1A4BOwF0SnFbXRjVzeKv7FVfB9SEezapKZAFz2g6zrZCnGoQM2kJOnvbj1RpJYjVnRCFCPZAlxlUr4cB0NVIOEj8lAyOI5IYlEuHkDGOtvvTpZClcCkT3JlBB57UNdh0H5qi9sxOsIkIBFweGcU8NIvdK4cnPL880olcGFuZCIRZAxZCDlGRO7JXgZDZD")

REDTRACK_CONFIG = {
    "api_key": os.environ.get('REDTRACK_API_KEY', "VbxluETPTeNxPLmyawYz"),
    "base_url": "https://api.redtrack.io/v1"  # Correct API v1 endpoint
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
        elif period == "all_time":
            # All time data - start from a very early date (e.g., 2 years ago)
            start = (now - timedelta(days=730)).replace(hour=0, minute=0, second=0, microsecond=0)
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
        """Evaluate rule for campaign with DYNAMIC payout and chained logic support"""
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

        # Check if this is a chained rule
        if rule.get('rule_type') == 'chained' and rule.get('chain_logic'):
            return self.evaluate_chained_rule(rule, campaign_data, campaign_id, campaign)

        # Original simple rule logic
        # Rule 1: Kill at 0 conversions over spend limit
        if conversions == 0:
            if spend >= rule["kill_on_no_conversion_spend"] and campaign["status"] == "ACTIVE":
                return {
                    "action": "kill",
                    "reason": f"0 conversions with ${spend} spend (Limit: ${rule['kill_on_no_conversion_spend']}) [Payout: ${rule['payout']}]",
                    "campaign_id": campaign_id,
                    "rule_id": rule["id"],
                    "rule_name": rule["name"]
                }
            return {"action": "no_action", "reason": f"0 conversions - waiting for first conversion [Payout: ${rule['payout']}]"}

        # Rule 2: Kill at exactly 1 conversion over spend limit
        if conversions == 1:
            if spend >= rule["kill_on_one_conversion_spend"] and campaign["status"] == "ACTIVE":
                return {
                    "action": "kill",
                    "reason": f"Only 1 conversion with ${spend} spend (Limit: ${rule['kill_on_one_conversion_spend']}) [Payout: ${rule['payout']}]",
                    "campaign_id": campaign_id,
                    "rule_id": rule["id"],
                    "rule_name": rule["name"]
                }
            return {"action": "no_action", "reason": f"Only 1 conversion - too little data [Payout: ${rule['payout']}]"}

        # Rule 3: CPA-based decisions at 2+ conversions
        if conversions >= 2:
            if cpa >= rule["max_cpa_allowed"] and campaign["status"] == "ACTIVE":
                return {
                    "action": "kill",
                    "reason": f"CPA ${cpa} exceeds limit ${rule['max_cpa_allowed']} at {conversions} conversions [Payout: ${rule['payout']}]",
                    "campaign_id": campaign_id,
                    "rule_id": rule["id"],
                    "rule_name": rule["name"]
                }

            if (rule["reactivate_if_profitable"] and
                cpa < rule["reactivate_if_cpa_below"] and
                campaign["status"] == "PAUSED"):

                return {
                    "action": "reactivate",
                    "reason": f"CPA ${cpa} below threshold ${rule['reactivate_if_cpa_below']} at {conversions} conversions [Payout: ${rule['payout']}]",
                    "campaign_id": campaign_id,
                    "rule_id": rule["id"],
                    "rule_name": rule["name"]
                }

            return {"action": "no_action", "reason": f"CPA ${cpa} at {conversions} conversions within range [Payout: ${rule['payout']}]"}

        return {"action": "no_action", "reason": f"Unknown conversion status [Payout: ${rule['payout']}]"}

    def evaluate_chained_rule(self, rule, campaign_data, campaign_id, campaign):
        """Evaluate chained logic rule - supports complex decision trees"""
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
                action_result = self.execute_condition_action(condition, campaign_id, rule, conversions, spend, cpa, payout)
                if action_result["action"] != "continue":
                    return action_result

        # If no conditions matched, return no action
        return {"action": "no_action", "reason": "No chained conditions matched"}

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

    def execute_condition_action(self, condition, campaign_id, rule, conversions, spend, cpa, payout):
        """Execute the action for a matched condition"""
        action = condition.get("action", "no_action")

        if action == "kill":
            return {
                "action": "kill",
                "reason": f"{condition.get('reason', 'Chained rule triggered')} [Conv: {conversions}, Spend: ${spend}, CPA: ${cpa}, Payout: ${payout}]",
                "campaign_id": campaign_id,
                "rule_id": rule["id"],
                "rule_name": rule["name"]
            }

        elif action == "reactivate":
            return {
                "action": "reactivate",
                "reason": f"{condition.get('reason', 'Chained rule reactivation')} [Conv: {conversions}, Spend: ${spend}, CPA: ${cpa}, Payout: ${payout}]",
                "campaign_id": campaign_id,
                "rule_id": rule["id"],
                "rule_name": rule["name"]
            }

        elif action == "continue":
            # Continue to next condition in chain
            return {"action": "continue", "reason": "Continue to next condition"}

        return {"action": "no_action", "reason": "No action specified"}

    def execute_action(self, evaluation):
        """Execute rule action"""
        if evaluation["action"] in ["skip", "no_action"]:
            return {"success": True, "message": evaluation["reason"]}

        campaign_id = evaluation["campaign_id"]
        rule_name = evaluation.get("rule_name", "Unknown Rule")

        if evaluation["action"] == "kill":
            result = toggle_campaign_status(campaign_id, "PAUSED", triggered_by_rule=True, rule_name=rule_name)
            if result["success"]:
                return {"success": True, "message": f"Campaign paused: {evaluation['reason']}"}
            else:
                return {"success": False, "message": f"Failed to pause campaign: {result.get('error')}"}

        elif evaluation["action"] == "reactivate":
            result = toggle_campaign_status(campaign_id, "ACTIVE", triggered_by_rule=True, rule_name=rule_name)
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
                    if not rule:
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
            try:
                automation_status_collection.update_one(
                    {'username': self.username},
                    {
                        '$set': {
                            'last_check': datetime.now().isoformat(),
                            'last_action_count': actions_taken
                        }
                    }
                )
            except Exception as e:
                print(f"Error updating automation status: {e}")
            
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
                    
                    # Sleep for 1 second between checks for INSTANT responsiveness
                    time.sleep(1)
                    
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
    """Test RedTrack API - ENHANCED with better error handling"""
    try:
        # Test actual RedTrack API connection with minimal parameters
        url = "https://api.redtrack.io/v1/report"
        params = {
            "api_key": REDTRACK_CONFIG["api_key"],
            "group": "sub3,sub6",
            "date_from": "2025-07-13",
            "date_to": "2025-07-13",
            "per": 10,
            "timezone": "America/New_York"
        }

        print(f"🧪 Testing RedTrack API: {url}")
        print(f"🧪 Test params: {params}")

        response = requests.get(url, params=params, headers={"Accept": "application/json"}, timeout=15)

        print(f"🧪 RedTrack Test Response Status: {response.status_code}")
        print(f"🧪 RedTrack Test Response Text: {response.text[:200]}...")

        if response.status_code == 200:
            try:
                data = response.json()
                return {"success": True, "user": f"RedTrack API Connected ✅ (Status: {response.status_code}, Data: {len(data) if isinstance(data, list) else 'object'})"}
            except ValueError:
                return {"success": False, "error": f"RedTrack API returned invalid JSON: {response.text[:100]}"}
        elif response.status_code == 401:
            return {"success": False, "error": "RedTrack API: Invalid API key (401 Unauthorized)"}
        elif response.status_code == 403:
            return {"success": False, "error": "RedTrack API: Access forbidden (403 Forbidden)"}
        elif response.status_code == 404:
            return {"success": False, "error": "RedTrack API: Endpoint not found (404) - Check API URL"}
        else:
            return {"success": False, "error": f"RedTrack API Error: HTTP {response.status_code} - {response.text[:100]}"}

    except requests.exceptions.Timeout:
        return {"success": False, "error": "RedTrack API: Request timeout"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "RedTrack API: Connection error"}
    except Exception as e:
        return {"success": False, "error": f"RedTrack API Error: {str(e)}"}

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
    """Fetch Meta campaigns and spend - FIXED for accuracy"""
    since, until = date_params["since"], date_params["until"]

    print(f"🔍 Meta API Call: Fetching campaigns and spend from {since} to {until}")

    if not aid:
        r = requests.get("https://graph.facebook.com/v19.0/me/adaccounts",
                         params={"access_token": token, "fields": "id", "limit": 1}, timeout=30)
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            raise Exception("No AdAccount found for this token")
        aid = data[0]["id"].replace("act_", "")

    # FIXED: Get campaigns with more detailed information
    print(f"📊 Fetching campaigns for account: act_{aid}")
    r = requests.get(f"https://graph.facebook.com/v19.0/act_{aid}/campaigns",
                     params={
                         "access_token": token,
                         "fields": "id,name,status,objective,created_time,updated_time",
                         "limit": 500  # Increased limit to get all campaigns
                     }, timeout=30)
    r.raise_for_status()
    camps = r.json().get("data", [])
    print(f"📊 Found {len(camps)} campaigns")

    campaign_details = {}
    for c in camps:
        campaign_details[c["id"]] = {
            "name": c["name"],
            "status": c.get("status", "UNKNOWN"),
            "objective": c.get("objective", "Unknown")
        }

    # FIXED: Get spend data with better error handling and more accurate fields
    print(f"💰 Fetching spend insights for {len(campaign_details)} campaigns")
    try:
        r = requests.get(f"https://graph.facebook.com/v19.0/act_{aid}/insights",
                         params={
                             "access_token": token,
                             "fields": "campaign_id,spend,impressions,clicks,reach",  # Added more fields for validation
                             "level": "campaign",
                             "time_range": json.dumps({"since": since, "until": until}),
                             "limit": 500,  # Increased limit
                             "filtering": json.dumps([])  # No filtering to get all data
                         }, timeout=30)
        r.raise_for_status()
        insights_data = r.json().get("data", [])
        print(f"💰 Found spend data for {len(insights_data)} campaigns")

        spends = {}
        for insight in insights_data:
            campaign_id = insight["campaign_id"]
            spend_value = float(insight.get("spend", 0) or 0)
            spends[campaign_id] = spend_value
            if spend_value > 0:
                print(f"   💰 Campaign {campaign_id}: ${spend_value}")

    except Exception as e:
        print(f"❌ Error fetching Meta spend data: {str(e)}")
        spends = {}

    result = []
    for cid in campaign_details.keys():
        spend = round(spends.get(cid, 0), 2)
        campaign_data = {
            "id": cid,
            "name": campaign_details[cid]["name"],
            "status": campaign_details[cid]["status"],
            "objective": campaign_details[cid]["objective"],
            "spend": spend
        }
        result.append(campaign_data)

    print(f"✅ Meta API Results: {len(result)} campaigns processed")
    return result

def fetch_meta_conversions(aid, date_params, token):
    """Fetch Meta Conversions/Results data - FIXED for accuracy"""
    since, until = date_params["since"], date_params["until"]

    print(f"🔍 Meta Conversions API Call: Fetching conversions from {since} to {until}")

    try:
        r = requests.get(f"https://graph.facebook.com/v19.0/act_{aid}/insights",
                         params={
                             "access_token": token,
                             "fields": "campaign_id,actions,conversion_values,action_values",  # Added action_values for more accuracy
                             "level": "campaign",
                             "time_range": json.dumps({"since": since, "until": until}),
                             "limit": 500,  # Increased limit
                             "filtering": json.dumps([])  # No filtering to get all data
                         }, timeout=30)
        r.raise_for_status()
        insights_data = r.json().get("data", [])
        print(f"📊 Found conversion data for {len(insights_data)} campaigns")

        meta_conversions = {}
        meta_revenue = {}

        for insight in insights_data:
            campaign_id = insight["campaign_id"]

            # FIXED: More comprehensive action type checking for conversions
            actions = insight.get("actions", [])
            total_conversions = 0

            # Priority order for conversion actions
            conversion_action_types = [
                "purchase",
                "offsite_conversion.fb_pixel_purchase",
                "offsite_conversion.custom_conversion",
                "app_install",
                "lead",
                "complete_registration"
            ]

            for action_type in conversion_action_types:
                for action in actions:
                    if action.get("action_type", "") == action_type:
                        total_conversions = int(float(action.get("value", 0)))
                        print(f"   🎯 Campaign {campaign_id}: {total_conversions} {action_type} conversions")
                        break
                if total_conversions > 0:
                    break

            # FIXED: More comprehensive revenue calculation
            total_conversion_value = 0.0

            # Try conversion_values first (most accurate)
            conversion_values = insight.get("conversion_values", [])
            for conv_value in conversion_values:
                action_type = conv_value.get("action_type", "")
                if action_type in conversion_action_types:
                    value = float(conv_value.get("value", 0))
                    total_conversion_value += value
                    print(f"   💰 Campaign {campaign_id}: ${value} from {action_type}")

            # If no conversion_values, try action_values
            if total_conversion_value == 0:
                action_values = insight.get("action_values", [])
                for action_value in action_values:
                    action_type = action_value.get("action_type", "")
                    if action_type in conversion_action_types:
                        value = float(action_value.get("value", 0))
                        total_conversion_value += value
                        print(f"   💰 Campaign {campaign_id}: ${value} from action_values {action_type}")

            meta_conversions[campaign_id] = total_conversions
            meta_revenue[campaign_id] = round(total_conversion_value, 2)

            if total_conversions > 0 or total_conversion_value > 0:
                print(f"   ✅ Campaign {campaign_id}: {total_conversions} conversions, ${total_conversion_value} revenue")

        print(f"✅ Meta Conversions Results: {len(meta_conversions)} campaigns with conversion data")
        return {"conversions": meta_conversions, "revenue": meta_revenue}

    except Exception as e:
        print(f"❌ Error fetching Meta conversions: {str(e)}")
        return {"conversions": {}, "revenue": {}}

def fetch_redtrack_data(date_params, api_key):
    """CRITICAL: Fetch RedTrack data - NO FALLBACKS, PRODUCTION GRADE"""
    since, until = date_params["since"], date_params["until"]

    # PRODUCTION: Use only the correct RedTrack API endpoint
    url = "https://api.redtrack.io/v1/report"
    params = {
        "api_key": api_key,
        "group": "sub3,sub6",  # sub3 = campaign_id, sub6 = campaign_name
        "date_from": since,
        "date_to": until,
        "per": 5000,
        "timezone": "America/New_York"
    }

    print(f"🔍 CRITICAL: RedTrack API Call to {url}")
    print(f"🔍 Parameters: {params}")
    print(f"🔍 Date Range: {since} to {until}")

    try:
        r = requests.get(url, params=params, headers={"Accept": "application/json"}, timeout=30)

        print(f"📊 CRITICAL: RedTrack Response Status: {r.status_code}")
        print(f"📊 CRITICAL: RedTrack Response Headers: {dict(r.headers)}")
        print(f"📊 CRITICAL: RedTrack Raw Response: {r.text[:200]}...")

        # PRODUCTION: Strict error checking - NO FALLBACKS
        if r.status_code != 200:
            print(f"❌ CRITICAL ERROR: RedTrack API returned HTTP {r.status_code}")
            print(f"❌ Response: {r.text}")
            return {"by_id": {}, "by_name": {}, "error": f"HTTP {r.status_code}: {r.text[:100]}"}

        # Check if response is empty
        if not r.text.strip():
            print("❌ CRITICAL ERROR: RedTrack API returned empty response")
            return {"by_id": {}, "by_name": {}, "error": "Empty response from RedTrack API"}

        # Parse JSON response
        try:
            payload = r.json()
        except ValueError as json_error:
            print(f"❌ CRITICAL ERROR: RedTrack API returned invalid JSON: {json_error}")
            print(f"❌ Raw response: {r.text}")
            return {"by_id": {}, "by_name": {}, "error": f"Invalid JSON: {str(json_error)}"}

        print(f"📊 CRITICAL: RedTrack Parsed Response: {payload}")

        # Handle API response format
        if isinstance(payload, dict):
            if "error" in payload:
                print(f"❌ CRITICAL ERROR: RedTrack API Error: {payload['error']}")
                return {"by_id": {}, "by_name": {}, "error": payload['error']}
            entries = payload.get("data", [])
        elif isinstance(payload, list):
            entries = payload
        else:
            print(f"❌ CRITICAL ERROR: Unexpected RedTrack response format: {type(payload)}")
            return {"by_id": {}, "by_name": {}, "error": f"Unexpected response format: {type(payload)}"}

        print(f"📊 CRITICAL: Processing {len(entries)} RedTrack entries")

        by_id = {}
        by_name = {}

        for e in entries:
            # PRODUCTION: Use most accurate revenue field
            revenue_fields = ["payment_revenue", "total_revenue", "net_revenue", "pub_revenue"]
            rev = 0

            for field in revenue_fields:
                field_value = float(e.get(field, 0) or 0)
                if field_value > 0:
                    rev = field_value
                    print(f"   💰 Using {field}: ${rev}")
                    break

            cid = (e.get("sub3") or "").strip()
            name = (e.get("sub6") or "").strip()

            if cid and rev > 0:
                by_id[cid] = round(rev, 2)
                print(f"   ✅ Campaign ID {cid}: ${rev}")
            if name and rev > 0:
                by_name[name] = round(rev, 2)
                print(f"   ✅ Campaign Name '{name}': ${rev}")

        print(f"✅ CRITICAL: RedTrack SUCCESS - {len(by_id)} campaigns by ID, {len(by_name)} by name")
        return {"by_id": by_id, "by_name": by_name}

    except requests.exceptions.Timeout:
        error_msg = "RedTrack API timeout (30 seconds)"
        print(f"❌ CRITICAL ERROR: {error_msg}")
        return {"by_id": {}, "by_name": {}, "error": error_msg}
    except requests.exceptions.ConnectionError:
        error_msg = "Cannot connect to RedTrack API"
        print(f"❌ CRITICAL ERROR: {error_msg}")
        return {"by_id": {}, "by_name": {}, "error": error_msg}
    except Exception as e:
        error_msg = f"RedTrack API error: {str(e)}"
        print(f"❌ CRITICAL ERROR: {error_msg}")
        return {"by_id": {}, "by_name": {}, "error": error_msg}

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
        
        print("🔍 CRITICAL: Loading RedTrack revenue...")
        rt = fetch_redtrack_data(date_ranges["redtrack"], REDTRACK_CONFIG["api_key"])
        redtrack_by_id = rt["by_id"]
        redtrack_by_name = rt["by_name"]
        redtrack_error = rt.get("error", None)

        if redtrack_error:
            print(f"❌ CRITICAL: RedTrack API Failed: {redtrack_error}")
        else:
            print(f"✅ CRITICAL: RedTrack API Success - {len(redtrack_by_id)} campaigns")
        
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

def toggle_campaign_status(campaign_id, new_status, triggered_by_rule=False, rule_name=None):
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

            campaign_name = "Unknown Campaign"
            for campaign in user_data["campaigns"]:
                if campaign["id"] == campaign_id:
                    campaign["status"] = new_status
                    campaign_name = campaign.get("name", "Unknown Campaign")
                    break

            save_user_data(username)

            # INSTANT RULE CHECK: Check rules immediately after status change
            if not triggered_by_rule:  # Only check if this wasn't already triggered by a rule
                print(f"🚀 INSTANT RULE CHECK: Campaign {campaign_name} status changed to {new_status}")
                # Run instant rule check in a separate thread for immediate response
                threading.Thread(target=instant_rule_check_for_campaign, args=(username, campaign_id), daemon=True).start()

            # Log activity
            if triggered_by_rule and rule_name:
                action_text = "paused" if new_status == "PAUSED" else "activated"
                log_activity(
                    username=username,
                    activity_type="rule_triggered",
                    title="Rule Triggered",
                    description=f"Rule '{rule_name}' {action_text} campaign '{campaign_name}'",
                    icon="pause" if new_status == "PAUSED" else "play",
                    badge="warning" if new_status == "PAUSED" else "success"
                )
            else:
                action_text = "paused" if new_status == "PAUSED" else "activated"
                log_activity(
                    username=username,
                    activity_type="campaign_status_changed",
                    title="Campaign Status Changed",
                    description=f"Campaign '{campaign_name}' manually {action_text}",
                    icon="pause" if new_status == "PAUSED" else "play",
                    badge="info"
                )

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

def instant_rule_check_for_campaign(username, campaign_id):
    """Perform INSTANT rule check for a specific campaign when status changes"""
    try:
        print(f"⚡ INSTANT RULE CHECK: Checking rules for campaign {campaign_id}")

        # Get user data and rules
        user_data = get_user_data(username)
        campaigns = user_data.get("campaigns", [])
        rules = load_rules_from_db(username)

        if not rules:
            print(f"⚡ No rules found for {username}")
            return

        # Find the specific campaign
        target_campaign = None
        for campaign in campaigns:
            if campaign["id"] == campaign_id:
                target_campaign = campaign
                break

        if not target_campaign:
            print(f"⚡ Campaign {campaign_id} not found")
            return

        print(f"⚡ Found campaign: {target_campaign['name']} - Status: {target_campaign['status']}")

        # Get assigned rules for this campaign
        assigned_rule_ids = get_campaign_rules_db(username, campaign_id)
        if not assigned_rule_ids:
            print(f"⚡ No rules assigned to campaign {campaign_id}")
            return

        print(f"⚡ Found {len(assigned_rule_ids)} assigned rules")

        # Check each assigned rule INSTANTLY
        for rule_id in assigned_rule_ids:
            rule = next((r for r in rules if r["id"] == rule_id), None)
            if not rule or not rule.get("active", True):
                continue

            print(f"⚡ Checking rule: {rule['name']}")

            # Create automation engine and get fresh campaign data
            engine = AutomationEngine(username)
            fresh_campaign_data = engine.get_campaign_data_with_dynamic_payout(campaign_id, rule["payout"])

            if fresh_campaign_data:
                # Evaluate rule instantly with correct parameters
                evaluation = engine.evaluate_chained_rule(rule, fresh_campaign_data, campaign_id, target_campaign)

                print(f"⚡ Rule evaluation result: {evaluation['action']} - {evaluation['reason']}")

                if evaluation["action"] in ["kill", "reactivate"]:
                    # Execute action INSTANTLY - use original campaign data for status
                    campaign_status = target_campaign.get("status", "UNKNOWN")

                    if evaluation["action"] == "kill" and campaign_status == "ACTIVE":
                        print(f"🔴 INSTANT KILL: Pausing campaign {target_campaign['name']}")
                        result = toggle_campaign_status(campaign_id, "PAUSED", triggered_by_rule=True, rule_name=rule["name"])
                        if result["success"]:
                            print(f"✅ Campaign {target_campaign['name']} INSTANTLY paused by rule {rule['name']}")
                        else:
                            print(f"❌ Failed to pause campaign: {result.get('error')}")

                    elif evaluation["action"] == "reactivate" and campaign_status == "PAUSED":
                        print(f"🟢 INSTANT REACTIVATE: Activating campaign {target_campaign['name']}")
                        result = toggle_campaign_status(campaign_id, "ACTIVE", triggered_by_rule=True, rule_name=rule["name"])
                        if result["success"]:
                            print(f"✅ Campaign {target_campaign['name']} INSTANTLY reactivated by rule {rule['name']}")
                        else:
                            print(f"❌ Failed to reactivate campaign: {result.get('error')}")

                    # Stop checking other rules since action was taken
                    break

    except Exception as e:
        print(f"❌ Instant rule check error for campaign {campaign_id}: {e}")

# ===============================
# RULE API
# ===============================



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

        # Update rule data - only essential fields for chained rules
        rule = {
            "id": rule_id,  # Keep the same ID
            "name": rule_data.get("name", existing_rule["name"]),
            "payout": float(rule_data.get("payout", existing_rule["payout"])),
            "created_at": existing_rule["created_at"],  # Keep original creation time
            "active": True,
            "rule_type": "chained",  # All rules are chained now
            "chain_logic": rule_data.get("chain_logic", existing_rule.get("chain_logic", []))
        }

        save_rule_to_db(username, rule)

        # Log activity
        log_activity(
            username=username,
            activity_type="rule_updated",
            title="Rule Updated",
            description=f"Updated automation rule '{rule['name']}' with new settings",
            icon="rule",
            badge="info"
        )

        # Invalidate cache to force refresh
        user_data = get_user_data(username)
        user_data["cached_data"]["last_refresh"] = None
        save_user_data(username)

        return jsonify({"success": True, "rule": rule})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/dashboard/api/rules/create-chained', methods=['POST'])
@login_required
def create_chained_rule():
    """Create a new chained logic rule"""
    try:
        username = session.get('username')
        rule_data = request.get_json()

        # Create chained rule with only essential fields
        rule = {
            "id": f"rule_{int(time.time())}_{username}",
            "name": rule_data.get("name", "Chained Rule"),
            "payout": float(rule_data.get("payout", 75)),
            "created_at": datetime.now().isoformat(),
            "active": True,
            "rule_type": "chained",
            "chain_logic": rule_data.get("chain_logic", [])
        }

        save_rule_to_db(username, rule)

        # Log activity
        log_activity(
            username=username,
            activity_type="rule_created",
            title="Chained Rule Created",
            description=f"Created new chained automation rule '{rule['name']}' with ${rule['payout']} payout",
            icon="rule",
            badge="success"
        )

        return jsonify({"success": True, "rule": rule})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/dashboard/api/rules/list', methods=['GET'])
@login_required
def list_rules():
    """List all rules for current user directly from database"""
    username = session.get('username')

    # Load rules directly from database for immediate updates
    rules = load_rules_from_db(username)

    return jsonify({
        "success": True,
        "rules": rules,
        "last_refresh": datetime.now().isoformat()
    })

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
            # Get rule and campaign names for logging
            rule_name = next((r['name'] for r in rules if r['id'] == rule_id), "Unknown Rule")
            campaign_name = next((c['name'] for c in user_data.get('campaigns', []) if c['id'] == campaign_id), "Unknown Campaign")

            # Log activity
            log_activity(
                username=username,
                activity_type="rule_assigned",
                title="Rule Assigned",
                description=f"Assigned rule '{rule_name}' to campaign '{campaign_name}'",
                icon="campaign",
                badge="success"
            )

            # 🚀 AUTOMATIC AUTOMATION START - DISABLED per user request
            print(f"ℹ️ Automation disabled - rule assigned without auto-start")

            return jsonify({
                "success": True,
                "message": f"Rule assigned successfully!",
                "campaign_id": campaign_id,
                "rule_id": rule_id,
                "automation_started": False
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

        # Get rule name before deletion
        rules = load_rules_from_db(username)
        rule_name = next((r['name'] for r in rules if r['id'] == rule_id), "Unknown Rule")

        delete_rule_from_db(username, rule_id)

        # Log activity
        log_activity(
            username=username,
            activity_type="rule_deleted",
            title="Rule Deleted",
            description=f"Deleted automation rule '{rule_name}'",
            icon="rule",
            badge="warning"
        )

        # Check if user still has active assignments
        if not has_active_rule_assignments(username):
            print(f"⏹️ No more rule assignments for {username}, stopping automation")
            stop_user_automation(username)

        # Invalidate cache to force refresh
        user_data = get_user_data(username)
        user_data["cached_data"]["last_refresh"] = None
        save_user_data(username)

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

@app.route('/dashboard/api/campaigns/live-status', methods=['GET'])
@login_required
def get_live_campaign_status():
    """Get live campaign status updates for real-time monitoring"""
    try:
        username = session.get('username')
        user_data = get_user_data(username)
        campaigns = user_data.get("campaigns", [])

        # Get automation status
        automation_status = get_automation_status(username)

        # Return minimal data for fast updates (no instant rule check to avoid errors)
        live_data = {
            "campaigns": [
                {
                    "id": camp["id"],
                    "name": camp["name"],
                    "status": camp["status"],
                    "spend": camp.get("spend", 0),
                    "revenue": camp.get("revenue", 0),
                    "conversions": camp.get("conversions", 0),
                    "cpa": camp.get("cpa", 0),
                    "last_updated": camp.get("last_updated", "")
                }
                for camp in campaigns
            ],
            "automation": {
                "is_running": automation_status["is_running"],
                "last_check": automation_status["last_check"],
                "last_action_count": automation_status["last_action_count"]
            },
            "timestamp": datetime.now().isoformat()
        }

        return jsonify({
            "success": True,
            "data": live_data
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        })

@app.route('/dashboard/api/campaigns/instant-rule-check', methods=['POST'])
@login_required
def instant_rule_check_api():
    """Trigger instant rule check for all campaigns"""
    try:
        username = session.get('username')

        # Run instant rule check for all campaigns
        threading.Thread(target=instant_rule_check_all_campaigns, args=(username,), daemon=True).start()

        return jsonify({
            "success": True,
            "message": "Instant rule check triggered"
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        })

def instant_rule_check_all_campaigns(username):
    """Perform INSTANT rule check for ALL campaigns"""
    try:
        print(f"⚡ INSTANT RULE CHECK: Checking ALL campaigns for {username}")

        # Get user data and rules
        user_data = get_user_data(username)
        campaigns = user_data.get("campaigns", [])
        rules = load_rules_from_db(username)

        if not rules or not campaigns:
            print(f"⚡ No rules or campaigns found for {username}")
            return

        print(f"⚡ Checking {len(campaigns)} campaigns against {len(rules)} rules")

        # Check all campaigns to avoid status field issues - let rule evaluation handle status checking
        print(f"⚡ Checking all {len(campaigns)} campaigns for instant rule evaluation")

        # Check each campaign against all assigned rules INSTANTLY
        for campaign in campaigns:
            campaign_id = campaign["id"]

            # Get assigned rules for this campaign
            assigned_rule_ids = get_campaign_rules_db(username, campaign_id)
            if not assigned_rule_ids:
                continue

            print(f"⚡ Checking campaign: {campaign['name']} ({len(assigned_rule_ids)} rules)")

            # Check each assigned rule INSTANTLY
            for rule_id in assigned_rule_ids:
                rule = next((r for r in rules if r["id"] == rule_id), None)
                if not rule or not rule.get("active", True):
                    continue

                # Create automation engine and get fresh campaign data
                engine = AutomationEngine(username)
                fresh_campaign_data = engine.get_campaign_data_with_dynamic_payout(campaign_id, rule["payout"])

                if fresh_campaign_data:
                    # Evaluate rule instantly with correct parameters
                    evaluation = engine.evaluate_chained_rule(rule, fresh_campaign_data, campaign_id, campaign)

                    print(f"⚡ Rule '{rule['name']}' evaluation: {evaluation['action']} - {evaluation['reason']}")

                    if evaluation["action"] in ["kill", "reactivate"]:
                        # Execute action INSTANTLY - use original campaign data for status
                        campaign_status = campaign.get("status", "UNKNOWN")

                        if evaluation["action"] == "kill" and campaign_status == "ACTIVE":
                            print(f"🔴 INSTANT KILL: Pausing campaign {campaign['name']}")
                            result = toggle_campaign_status(campaign_id, "PAUSED", triggered_by_rule=True, rule_name=rule["name"])
                            if result["success"]:
                                print(f"✅ Campaign {campaign['name']} INSTANTLY paused by rule {rule['name']}")

                        elif evaluation["action"] == "reactivate" and campaign_status == "PAUSED":
                            print(f"🟢 INSTANT REACTIVATE: Activating campaign {campaign['name']}")
                            result = toggle_campaign_status(campaign_id, "ACTIVE", triggered_by_rule=True, rule_name=rule["name"])
                            if result["success"]:
                                print(f"✅ Campaign {campaign['name']} INSTANTLY reactivated by rule {rule['name']}")

                        # Stop checking other rules for this campaign since action was taken
                        break

    except Exception as e:
        print(f"❌ Instant rule check error for all campaigns: {e}")
        import traceback
        print(f"❌ Full error traceback: {traceback.format_exc()}")

# ===============================
# OPTIMIZED API ROUTES WITH CACHING
# ===============================

@app.route('/dashboard/api/refresh-all', methods=['POST'])
@login_required
def refresh_all_data_api():
    """Refresh all data - single API call for everything"""
    username = session.get('username')

    # Refresh regular cached data (last 30 days for campaigns list)
    cached_data = refresh_all_data(username, force=True)

    # Get all-time dashboard stats separately
    print("📊 Calculating all-time dashboard stats...")
    all_time_stats = get_all_time_dashboard_stats(username)

    return jsonify({
        "success": True,
        "message": "All data refreshed successfully",
        "data": {
            "campaigns": cached_data.get("campaigns", []),
            "rules": cached_data.get("rules", []),
            "dashboard_stats": {
                "total_spend": all_time_stats.get("spend", 0),
                "total_revenue": all_time_stats.get("revenue", 0),
                "avg_roas": all_time_stats.get("roas", 0),
                "active_campaigns": all_time_stats.get("active", 0),
                "total_campaigns": all_time_stats.get("campaigns", 0)
            },
            "last_refresh": cached_data.get("last_refresh")
        },
        "campaigns_count": len(cached_data.get("campaigns", [])),
        "rules_count": len(cached_data.get("rules", [])),
        "last_refresh": cached_data.get("last_refresh")
    })

@app.route('/dashboard/api/get-all-data', methods=['GET'])
@login_required
def get_all_data_api():
    """Get all cached data or refresh if needed"""
    username = session.get('username')

    # Get cached data (will refresh if stale)
    cached_data = refresh_all_data(username, force=False)

    return jsonify({
        "success": True,
        "data": cached_data,
        "is_fresh": is_data_fresh(username)
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
    """Get campaigns from cache or refresh if needed - FIXED to support date range"""
    username = session.get('username')
    date_range = request.args.get('date_range', 'last_30_days')

    print(f"🔍 Getting campaigns for user {username} with date range: {date_range}")

    # For non-default date ranges, always fetch fresh data
    force_refresh = date_range != 'last_30_days'
    cached_data = refresh_all_data(username, force=force_refresh, date_range=date_range)

    return jsonify({
        "success": True,
        "campaigns": cached_data.get("campaigns", []),
        "count": len(cached_data.get("campaigns", [])),
        "total_spend": cached_data.get("total_spend", 0),
        "total_revenue": cached_data.get("total_revenue", 0),
        "matched_count": cached_data.get("matched_campaigns", 0),
        "hybrid_used": cached_data.get("hybrid_used", 0),
        "last_refresh": cached_data.get("last_refresh"),
        "date_range": date_range
    })

@app.route('/dashboard/api/campaigns/list', methods=['GET'])
@login_required
def get_campaigns_list():
    """Get campaigns with date range filtering - FIXED for proper date filtering"""
    date_range = request.args.get('date_range', 'last_30_days')
    username = session.get('username')

    print(f"🔍 Getting campaigns for date range: {date_range}")

    try:
        # Always fetch fresh data for the requested date range
        result = load_campaigns_with_hybrid_tracking(date_range)

        if result.get("success"):
            print(f"✅ Successfully loaded {len(result.get('campaigns', []))} campaigns for {date_range}")
            return jsonify(result)
        else:
            print(f"❌ Failed to load campaigns: {result.get('error', 'Unknown error')}")
            return jsonify({"success": False, "error": result.get('error', 'Failed to load campaigns'), "campaigns": []})

    except Exception as e:
        print(f"❌ Error in get_campaigns_list: {str(e)}")
        return jsonify({"success": False, "error": str(e), "campaigns": []})

@app.route('/dashboard/api/campaigns/<date_range>', methods=['GET'])
@login_required
def get_campaigns_date_range(date_range):
    """Get campaigns for specific date range - FIXED to use proper date filtering"""
    print(f"🔍 Getting campaigns for date range: {date_range}")

    try:
        result = load_campaigns_with_hybrid_tracking(date_range)
        return jsonify(result)
    except Exception as e:
        print(f"❌ Error in get_campaigns_date_range: {str(e)}")
        return jsonify({"success": False, "error": str(e), "campaigns": []})

@app.route('/dashboard/api/dashboard-stats', methods=['GET'])
@login_required
def get_dashboard_stats_api():
    """Get dashboard stats from cache"""
    username = session.get('username')
    cached_data = refresh_all_data(username, force=False)

    return jsonify({
        'success': True,
        'stats': cached_data.get("dashboard_stats", {}),
        'campaigns_count': len(cached_data.get("campaigns", [])),
        'last_refresh': cached_data.get("last_refresh")
    })

# REMOVED: Chart data API endpoint (causing delays)

@app.route('/dashboard/api/toggle-campaign/<campaign_id>/<new_status>', methods=['POST'])
@login_required
def toggle_campaign_api(campaign_id, new_status):
    """Toggle campaign status"""
    return jsonify(toggle_campaign_status(campaign_id, new_status))

@app.route('/dashboard/api/activities', methods=['GET'])
@login_required
def get_recent_activities_api():
    """Get recent activities for current user"""
    try:
        username = session.get('username')
        activities = get_recent_activities(username, limit=10)

        return jsonify({
            "success": True,
            "activities": activities,
            "count": len(activities)
        })
    except Exception as e:
        print(f"❌ Error getting activities: {e}")
        return jsonify({
            "success": False,
            "activities": [],
            "count": 0,
            "error": str(e)
        })

# ===============================
# DASHBOARD ROUTE
# ===============================

@app.route('/dashboard')
@login_required
def dashboard():
    """Redirect dashboard to campaigns page"""
    return redirect(url_for('campaigns'))


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

# REMOVED: Chart data generation functions (causing delays)

# REMOVED: Chart data functions (causing delays)

# REMOVED: All chart data functions (causing delays)

# REMOVED: All chart data functions (causing delays)

def get_dashboard_stats(campaigns=None):
    """Calculate dashboard statistics from provided campaigns"""
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

def get_all_time_dashboard_stats(username):
    """Get all-time dashboard statistics by fetching all-time campaign data"""
    try:
        user_data = get_user_data(username)

        if not user_data.get("current_account"):
            print(f"❌ No account selected for {username}")
            return {
                'campaigns': 0,
                'active': 0,
                'matched': 0,
                'spend': 0,
                'revenue': 0,
                'roas': 0
            }

        account_id = user_data['current_account']['id']

        # Get all-time date ranges
        date_ranges = get_date_range("all_time")

        print(f"📊 Loading all-time Meta campaigns for dashboard stats...")
        metas = fetch_meta_campaigns_and_spend(account_id, date_ranges["meta"], META_TOKEN)

        print(f"🔍 Loading all-time RedTrack revenue for dashboard stats...")
        rt = fetch_redtrack_data(date_ranges["redtrack"], REDTRACK_CONFIG["api_key"])
        redtrack_by_id = rt["by_id"]
        redtrack_by_name = rt["by_name"]

        print(f"📈 Loading all-time Meta conversions for dashboard stats...")
        meta_conv_data = fetch_meta_conversions(account_id, date_ranges["meta"], META_TOKEN)
        meta_conversions = meta_conv_data["conversions"]
        meta_revenue = meta_conv_data["revenue"]

        # Process campaigns with all-time data
        campaigns = []
        for meta in metas:
            campaign_id = meta["id"]
            campaign_name = meta["name"]
            spend = float(meta.get("spend", 0))

            # Try RedTrack revenue by ID first, then by name
            revenue = redtrack_by_id.get(campaign_id, 0)
            if revenue == 0:
                revenue = redtrack_by_name.get(campaign_name, 0)

            # If no RedTrack revenue, try Meta revenue
            if revenue == 0:
                revenue = meta_revenue.get(campaign_id, 0)

            campaigns.append({
                "id": campaign_id,
                "name": campaign_name,
                "spend": spend,
                "revenue": revenue,
                "status": meta.get("status", "UNKNOWN"),
                "match_type": "RedTrack Match" if revenue > 0 else "No Match"
            })

        # Calculate and return stats
        return get_dashboard_stats(campaigns)

    except Exception as e:
        print(f"❌ Error getting all-time dashboard stats: {str(e)}")
        return {
            'campaigns': 0,
            'active': 0,
            'matched': 0,
            'spend': 0,
            'revenue': 0,
            'roas': 0
        }

# ===============================
# API TESTING ROUTES
# ===============================

@app.route('/test_data_accuracy')
@login_required
def test_data_accuracy():
    """Test route to verify data accuracy from APIs"""
    username = session.get('username', 'anonymous')
    user_data = get_user_data(username)

    if not user_data.get("current_account"):
        return jsonify({"error": "No account selected"}), 400

    account_id = user_data['current_account']['id']

    try:
        # Test Meta API
        meta_test = test_meta_api()

        # Test RedTrack API
        redtrack_test = test_redtrack_api()

        # Get today's date range for testing
        date_ranges = get_date_range("today")

        # Test Meta campaigns fetch
        print("🧪 Testing Meta campaigns fetch...")
        meta_campaigns = fetch_meta_campaigns_and_spend(account_id, date_ranges["meta"], META_TOKEN)

        # Test RedTrack data fetch
        print("🧪 Testing RedTrack data fetch...")
        redtrack_data = fetch_redtrack_data(date_ranges["redtrack"], REDTRACK_CONFIG["api_key"])

        # Test Meta conversions fetch
        print("🧪 Testing Meta conversions fetch...")
        meta_conv_data = fetch_meta_conversions(account_id, date_ranges["meta"], META_TOKEN)

        return jsonify({
            "meta_api": meta_test,
            "redtrack_api": redtrack_test,
            "meta_campaigns_count": len(meta_campaigns),
            "redtrack_campaigns_count": len(redtrack_data.get("by_id", {})),
            "meta_conversions_count": len(meta_conv_data.get("conversions", {})),
            "date_range": date_ranges["display"],
            "sample_meta_campaign": meta_campaigns[0] if meta_campaigns else None,
            "sample_redtrack_data": {
                "by_id_sample": dict(list(redtrack_data.get("by_id", {}).items())[:1]),
                "by_name_sample": dict(list(redtrack_data.get("by_name", {}).items())[:1])
            },
            "sample_conversions": dict(list(meta_conv_data.get("conversions", {}).items())[:1])
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
    print(f"🧪 Test Data Accuracy: http://localhost:{port}/test_data_accuracy")
    print("🔧 REVOLUTIONARY FEATURES:")
    print("   ✅ AUTOMATIC Automation - Starts sofort bei Regel-Zuweisung!")
    print("   ✅ DYNAMIC Payouts - Verwendet Regel-Payout statt hardcoded $75!")
    print("   ✅ MongoDB Database für persistente Regeln")
    print("   ✅ Modern UI inspired by Notion & Linear")
    print("   ✅ Fast loading & flüssige Performance")
    print("   ✅ Cleaned up - removed unnecessary buttons")
    print("   ✅ FIXED API calls for accurate spend/revenue data")
    print("=" * 80)
    app.run(debug=debug, host='0.0.0.0', port=port)
