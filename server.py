import os
import httpx
from typing import Optional
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict

# Initialize MCP server
mcp = FastMCP("meta_ads_mcp")

# Meta API base URL
META_API_BASE = "https://graph.facebook.com/v19.0"

def get_token():
    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        raise ValueError("META_ACCESS_TOKEN environment variable not set")
    return token

def get_ad_account():
    account = os.environ.get("META_AD_ACCOUNT_ID")
    if not account:
        raise ValueError("META_AD_ACCOUNT_ID environment variable not set")
    if not account.startswith("act_"):
        account = f"act_{account}"
    return account

async def meta_get(endpoint: str, params: dict = {}) -> dict:
    """Make a GET request to Meta Graph API."""
    token = get_token()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{META_API_BASE}/{endpoint}",
            params={"access_token": token, **params}
        )
        data = response.json()
        if "error" in data:
            raise Exception(f"Meta API Error: {data['error'].get('message', str(data['error']))}")
        return data

async def meta_post(endpoint: str, data: dict = {}) -> dict:
    """Make a POST request to Meta Graph API."""
    token = get_token()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{META_API_BASE}/{endpoint}",
            data={"access_token": token, **data}
        )
        result = response.json()
        if "error" in result:
            raise Exception(f"Meta API Error: {result['error'].get('message', str(result['error']))}")
        return result


# ─── TOOL MODELS ─────────────────────────────────────────────────────────────

class CampaignInsightsInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    campaign_id: str = Field(..., description="Campaign ID to get insights for")
    date_preset: str = Field(default="last_7d", description="Date range: today, yesterday, last_7d, last_30d, this_month, last_month")

class AdSetInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    campaign_id: str = Field(..., description="Campaign ID to list ad sets for")

class UpdateCampaignInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    campaign_id: str = Field(..., description="Campaign ID to update")
    status: str = Field(..., description="New status: ACTIVE or PAUSED")

class UpdateBudgetInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ad_set_id: str = Field(..., description="Ad Set ID to update budget for")
    daily_budget: int = Field(..., description="New daily budget in cents (e.g. 1000 = $10.00)")

class CreateCampaignInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(..., description="Campaign name")
    objective: str = Field(default="OUTCOME_SALES", description="Campaign objective: OUTCOME_SALES, OUTCOME_TRAFFIC, OUTCOME_ENGAGEMENT, OUTCOME_LEADS")
    status: str = Field(default="PAUSED", description="Initial status: ACTIVE or PAUSED")
    daily_budget: int = Field(..., description="Daily budget in cents (e.g. 1000 = $10.00)")

class GetAdInsightsInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ad_set_id: str = Field(..., description="Ad Set ID to get insights for")
    date_preset: str = Field(default="last_7d", description="Date range: today, yesterday, last_7d, last_30d")


# ─── TOOLS ───────────────────────────────────────────────────────────────────

@mcp.tool(
    name="meta_list_campaigns",
    annotations={"readOnlyHint": True, "destructiveHint": False}
)
async def meta_list_campaigns() -> str:
    """
    List all campaigns in the Meta Ads account with their status, objective, and budget.
    Returns campaign IDs needed for other tools.
    """
    account = get_ad_account()
    data = await meta_get(
        f"{account}/campaigns",
        {
            "fields": "id,name,status,objective,daily_budget,budget_remaining,start_time,stop_time,effective_status",
            "limit": 20
        }
    )
    campaigns = data.get("data", [])
    if not campaigns:
        return "No campaigns found in this ad account."

    lines = ["📊 **CAMPAIGNS IN YOUR AD ACCOUNT**\n"]
    for c in campaigns:
        budget = int(c.get('daily_budget', 0)) / 100
        remaining = int(c.get('budget_remaining', 0)) / 100
        lines.append(
            f"🎯 **{c['name']}**\n"
            f"   ID: {c['id']}\n"
            f"   Status: {c.get('effective_status', c.get('status'))}\n"
            f"   Objective: {c.get('objective', 'N/A')}\n"
            f"   Daily Budget: ${budget:.2f}\n"
            f"   Budget Remaining: ${remaining:.2f}\n"
        )
    return "\n".join(lines)


@mcp.tool(
    name="meta_get_campaign_insights",
    annotations={"readOnlyHint": True, "destructiveHint": False}
)
async def meta_get_campaign_insights(params: CampaignInsightsInput) -> str:
    """
    Get detailed performance metrics for a specific campaign: impressions, clicks, CTR, CPC, spend, conversions, ROAS.
    """
    data = await meta_get(
        f"{params.campaign_id}/insights",
        {
            "fields": "campaign_name,impressions,clicks,ctr,cpc,cpm,spend,actions,action_values,purchase_roas,reach,frequency",
            "date_preset": params.date_preset
        }
    )
    insights = data.get("data", [])
    if not insights:
        return f"No insights data available for campaign {params.campaign_id} in the selected date range."

    i = insights[0]
    spend = float(i.get('spend', 0))
    impressions = int(i.get('impressions', 0))
    clicks = int(i.get('clicks', 0))
    ctr = float(i.get('ctr', 0))
    cpc = float(i.get('cpc', 0))
    cpm = float(i.get('cpm', 0))
    reach = int(i.get('reach', 0))

    # Extract purchases
    purchases = 0
    purchase_value = 0
    actions = i.get('actions', [])
    action_values = i.get('action_values', [])
    for a in actions:
        if a['action_type'] == 'purchase':
            purchases = int(a['value'])
    for av in action_values:
        if av['action_type'] == 'purchase':
            purchase_value = float(av['value'])

    roas_data = i.get('purchase_roas', [])
    roas = float(roas_data[0]['value']) if roas_data else 0
    cost_per_purchase = spend / purchases if purchases > 0 else 0

    result = f"""📈 **CAMPAIGN INSIGHTS** ({params.date_preset})
Campaign: {i.get('campaign_name', params.campaign_id)}

💰 **SPEND & REACH**
   Total Spend: ${spend:.2f}
   Reach: {reach:,}
   Impressions: {impressions:,}
   Frequency: {float(i.get('frequency', 0)):.2f}

🖱️ **CLICKS**
   Link Clicks: {clicks:,}
   CTR: {ctr:.2f}%
   CPC: ${cpc:.2f}
   CPM: ${cpm:.2f}

🛒 **CONVERSIONS**
   Purchases: {purchases}
   Revenue: ${purchase_value:.2f}
   ROAS: {roas:.2f}x
   Cost per Purchase: ${cost_per_purchase:.2f}

📊 **ASSESSMENT**
{"✅ Profitable - ROAS > 2x" if roas > 2 else "⚠️ Break-even zone" if roas > 1 else "❌ Not profitable - needs optimization" if spend > 0 else "⏸️ No spend yet"}
"""
    return result


@mcp.tool(
    name="meta_list_ad_sets",
    annotations={"readOnlyHint": True, "destructiveHint": False}
)
async def meta_list_ad_sets(params: AdSetInput) -> str:
    """
    List all ad sets within a campaign with targeting, budget, and status info.
    """
    data = await meta_get(
        f"{params.campaign_id}/adsets",
        {
            "fields": "id,name,status,daily_budget,targeting,optimization_goal,billing_event,bid_amount,effective_status",
            "limit": 20
        }
    )
    ad_sets = data.get("data", [])
    if not ad_sets:
        return "No ad sets found for this campaign."

    lines = [f"📋 **AD SETS FOR CAMPAIGN**\n"]
    for ad_set in ad_sets:
        budget = int(ad_set.get('daily_budget', 0)) / 100
        targeting = ad_set.get('targeting', {})
        age_min = targeting.get('age_min', 'N/A')
        age_max = targeting.get('age_max', 'N/A')
        geo = targeting.get('geo_locations', {}).get('countries', [])
        interests = targeting.get('flexible_spec', [{}])

        lines.append(
            f"📌 **{ad_set['name']}**\n"
            f"   ID: {ad_set['id']}\n"
            f"   Status: {ad_set.get('effective_status', ad_set.get('status'))}\n"
            f"   Daily Budget: ${budget:.2f}\n"
            f"   Optimization: {ad_set.get('optimization_goal', 'N/A')}\n"
            f"   Age: {age_min}-{age_max}\n"
            f"   Countries: {', '.join(geo) if geo else 'N/A'}\n"
        )
    return "\n".join(lines)


@mcp.tool(
    name="meta_get_ad_set_insights",
    annotations={"readOnlyHint": True, "destructiveHint": False}
)
async def meta_get_ad_set_insights(params: GetAdInsightsInput) -> str:
    """
    Get performance insights for a specific ad set: spend, clicks, CTR, conversions.
    """
    data = await meta_get(
        f"{params.ad_set_id}/insights",
        {
            "fields": "adset_name,impressions,clicks,ctr,cpc,spend,actions,action_values,reach",
            "date_preset": params.date_preset
        }
    )
    insights = data.get("data", [])
    if not insights:
        return f"No insights available for ad set {params.ad_set_id}."

    i = insights[0]
    spend = float(i.get('spend', 0))
    clicks = int(i.get('clicks', 0))
    ctr = float(i.get('ctr', 0))
    cpc = float(i.get('cpc', 0))

    purchases = 0
    add_to_carts = 0
    for a in i.get('actions', []):
        if a['action_type'] == 'purchase':
            purchases = int(a['value'])
        if a['action_type'] == 'add_to_cart':
            add_to_carts = int(a['value'])

    return f"""📊 **AD SET INSIGHTS** ({params.date_preset})
Ad Set: {i.get('adset_name', params.ad_set_id)}

Spend: ${spend:.2f} | Reach: {int(i.get('reach', 0)):,}
Clicks: {clicks} | CTR: {ctr:.2f}% | CPC: ${cpc:.2f}
Add to Carts: {add_to_carts} | Purchases: {purchases}
Cost per Purchase: ${spend/purchases:.2f if purchases > 0 else 'N/A'}
"""


@mcp.tool(
    name="meta_update_campaign_status",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True}
)
async def meta_update_campaign_status(params: UpdateCampaignInput) -> str:
    """
    Activate or pause a campaign. Use status ACTIVE to start or PAUSED to stop.
    """
    if params.status not in ["ACTIVE", "PAUSED"]:
        return "Error: status must be ACTIVE or PAUSED"

    result = await meta_post(
        params.campaign_id,
        {"status": params.status}
    )
    success = result.get("success", False)
    emoji = "▶️" if params.status == "ACTIVE" else "⏸️"
    if success:
        return f"{emoji} Campaign {params.campaign_id} successfully set to {params.status}"
    return f"⚠️ Unexpected response: {result}"


@mcp.tool(
    name="meta_update_ad_set_budget",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True}
)
async def meta_update_ad_set_budget(params: UpdateBudgetInput) -> str:
    """
    Update the daily budget of an ad set. Budget is in cents (1000 = $10.00).
    """
    result = await meta_post(
        params.ad_set_id,
        {"daily_budget": str(params.daily_budget)}
    )
    success = result.get("success", False)
    budget_dollars = params.daily_budget / 100
    if success:
        return f"💰 Ad Set {params.ad_set_id} budget updated to ${budget_dollars:.2f}/day"
    return f"⚠️ Unexpected response: {result}"


@mcp.tool(
    name="meta_create_campaign",
    annotations={"readOnlyHint": False, "destructiveHint": False}
)
async def meta_create_campaign(params: CreateCampaignInput) -> str:
    """
    Create a new Meta Ads campaign. Starts as PAUSED by default for safety.
    Objectives: OUTCOME_SALES (recommended for ecommerce), OUTCOME_TRAFFIC, OUTCOME_ENGAGEMENT.
    """
    account = get_ad_account()
    result = await meta_post(
        f"{account}/campaigns",
        {
            "name": params.name,
            "objective": params.objective,
            "status": params.status,
            "daily_budget": str(params.daily_budget),
            "special_ad_categories": "[]"
        }
    )
    campaign_id = result.get("id")
    if campaign_id:
        budget_dollars = params.daily_budget / 100
        return (
            f"✅ **Campaign Created Successfully!**\n"
            f"   Name: {params.name}\n"
            f"   ID: {campaign_id}\n"
            f"   Objective: {params.objective}\n"
            f"   Budget: ${budget_dollars:.2f}/day\n"
            f"   Status: {params.status}\n\n"
            f"Next step: Create ad sets with targeting for this campaign."
        )
    return f"⚠️ Unexpected response: {result}"


@mcp.tool(
    name="meta_get_account_summary",
    annotations={"readOnlyHint": True, "destructiveHint": False}
)
async def meta_get_account_summary() -> str:
    """
    Get a full summary of the Meta Ads account: total spend, active campaigns, and overall performance.
    """
    account = get_ad_account()

    # Get account info
    account_data = await meta_get(
        account,
        {"fields": "name,account_status,currency,spend_cap,amount_spent,balance"}
    )

    # Get recent insights
    insights_data = await meta_get(
        f"{account}/insights",
        {
            "fields": "impressions,clicks,ctr,spend,actions,action_values,purchase_roas",
            "date_preset": "last_7d"
        }
    )

    name = account_data.get('name', 'Unknown')
    spent = float(account_data.get('amount_spent', 0)) / 100
    currency = account_data.get('currency', 'USD')

    insights = insights_data.get('data', [{}])
    i = insights[0] if insights else {}
    week_spend = float(i.get('spend', 0))
    impressions = int(i.get('impressions', 0))
    clicks = int(i.get('clicks', 0))
    ctr = float(i.get('ctr', 0))

    purchases = 0
    for a in i.get('actions', []):
        if a['action_type'] == 'purchase':
            purchases = int(a['value'])

    roas_data = i.get('purchase_roas', [])
    roas = float(roas_data[0]['value']) if roas_data else 0

    return f"""🏪 **PUPINO.PL - META ADS ACCOUNT SUMMARY**

Account: {name} ({currency})
Total Spent (All Time): ${spent:.2f}

📊 **LAST 7 DAYS**
   Spend: ${week_spend:.2f}
   Impressions: {impressions:,}
   Clicks: {clicks:,}
   CTR: {ctr:.2f}%
   Purchases: {purchases}
   ROAS: {roas:.2f}x

{'✅ Account performing well!' if roas > 2 else '⚠️ Account needs optimization - low ROAS' if week_spend > 0 else '📭 No recent activity'}
"""


if __name__ == "__main__":
    import sys
    import uvicorn

    transport = sys.argv[1] if len(sys.argv) > 1 else "streamable-http"
    port = int(os.environ.get("PORT", 8000))

    if transport == "streamable-http":
        # Get the ASGI app from FastMCP and serve with uvicorn
        app = mcp.get_asgi_app()
        uvicorn.run(app, host="0.0.0.0", port=port)
    else:
        mcp.run(transport="stdio")
