import os
import json
import gradio as gr
from google import genai
from google.genai import types

# =====================================================================
# 1. MOCK ENTERPRISE DATABASES & APIs
# =====================================================================

# Simulated SQL Database for User Profiles
USER_DB = {
    "U102": {
        "monthly_budget": 8000.0,
        "expenses": {"food": 12000.0, "fuel": 0.0, "utilities": 2500.0},
        "savings_goals": {"trip_to_goa": 20000.0},
        "liquid_cash": 18000.0
    }
}

# =====================================================================
# 2. DEFINE AGENT TOOLS (Function Calling)
# =====================================================================

def get_financial_profile(user_id: str = "U102") -> str:
    """Retrieves the user's current budget, liquid cash, and expenses from the database."""
    return json.dumps(USER_DB.get(user_id, {"error": "User not found"}))

def log_expense(category: str, amount: float, user_id: str = "U102") -> str:
    """Logs a new expense, deducts from liquid cash, and checks for budget overruns."""
    if user_id not in USER_DB:
        return "User not found"

    cat = category.lower()
    USER_DB[user_id]["expenses"][cat] = USER_DB[user_id]["expenses"].get(cat, 0.0) + amount
    USER_DB[user_id]["liquid_cash"] -= amount

    total_spent = sum(USER_DB[user_id]["expenses"].values())
    budget = USER_DB[user_id]["monthly_budget"]

    if total_spent > budget:
        alert = f"CRITICAL: Budget overrun! Total spent (₹{total_spent}) exceeds budget (₹{budget})."
    else:
        alert = f"Status normal. Total spent (₹{total_spent}) is within budget (₹{budget})."

    return json.dumps({"status": "Expense logged", "new_balance": USER_DB[user_id]["liquid_cash"], "alert": alert})

def fetch_market_data(asset_name: str) -> str:
    """Simulates a live web search API to fetch current market prices and risk levels."""
    asset = asset_name.lower()
    if "apple" in asset:
        return json.dumps({"asset": "Apple (AAPL)", "price_usd": 175.0, "volatility": "Medium", "analyst_rating": "Buy"})
    elif "techcorp" in asset or "ipo" in asset:
        return json.dumps({"asset": "TechCorp IPO", "status": "Launching Today", "oversubscribed": "7x", "risk_level": "High"})
    elif "flight" in asset or "goa" in asset:
        return json.dumps({"asset": "Flight to Goa", "average_price_inr": 4500, "availability": "Limited"})
    else:
        return json.dumps({"error": "Market data unavailable for this asset."})

def calculate_confidence_score(liquid_cash: float, allocated_amount: float, asset_risk: str) -> str:
    """Calculates a financial recommendation confidence score (0-100) based on liquidity and risk."""
    score = 100
    liquidity_ratio = liquid_cash / allocated_amount if allocated_amount > 0 else 10

    if liquidity_ratio < 2.0:
        score -= 40  # Heavy penalty if asset consumes more than 50% of liquid cash
    if asset_risk.lower() == "high":
        score -= 25
    elif asset_risk.lower() == "medium":
        score -= 10

    verdict = "RECOMMENDED" if score >= 65 else "NOT RECOMMENDED"
    return json.dumps({"confidence_score": f"{score}%", "verdict": verdict})

# List of tools to provide to the LLM
financial_tools = [get_financial_profile, log_expense, fetch_market_data, calculate_confidence_score]


# =====================================================================
# 3. LLM ORCHESTRATOR
# =====================================================================

# REPLACE WITH YOUR ACTUAL API KEY OR SET IT IN YOUR TERMINAL ENVIRONMENT VARIABLES
API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
client = genai.Client(api_key=API_KEY)

# Config for the chat: current model, tools, and a strict system prompt.
# Automatic function calling is the default behavior in the google-genai SDK
# whenever plain Python functions are passed in as tools.
chat_config = types.GenerateContentConfig(
    tools=financial_tools,
    system_instruction=(
        "You are an Intelligent Financial Decision Agent. "
        "When a user asks a financial question, you must autonomously use the provided tools to gather data before answering. "
        "1. If logging an expense, use log_expense. "
        "2. If asked about adjusting spending, use get_financial_profile. "
        "3. If asked 'Should I buy/invest/book?', use get_financial_profile to check their cash, then use fetch_market_data, "
        "and finally use calculate_confidence_score. "
        "Always present the final answer clearly with the Confidence Score and Verdict if applicable."
    )
)

# Start a chat session that maintains tool history
chat = client.chats.create(model='gemini-3.6-flash', config=chat_config)


# =====================================================================
# 4. DASHBOARD RENDERING HELPERS
# =====================================================================

def _fmt(amount: float) -> str:
    return f"₹{amount:,.2f}"

def render_dashboard(user_id: str = "U102") -> str:
    """Builds an HTML snapshot card of the live backend state."""
    profile = USER_DB.get(user_id)
    if not profile:
        return "<div class='dash-card'><p>No profile found.</p></div>"

    budget = profile["monthly_budget"]
    total_spent = sum(profile["expenses"].values())
    liquid_cash = profile["liquid_cash"]
    pct = min((total_spent / budget) * 100, 100) if budget else 0
    over_budget = total_spent > budget

    bar_color = "#f43f5e" if over_budget else ("#f59e0b" if pct > 75 else "#22c55e")
    status_badge = (
        "<span class='badge badge-danger'>⚠ Over Budget</span>"
        if over_budget else
        "<span class='badge badge-ok'>✓ On Track</span>"
    )

    expense_rows = "".join(
        f"<div class='exp-row'><span class='exp-cat'>{cat.title()}</span>"
        f"<span class='exp-amt'>{_fmt(amt)}</span></div>"
        for cat, amt in profile["expenses"].items()
    )

    goal_rows = "".join(
        f"<div class='exp-row'><span class='exp-cat'>🎯 {name.replace('_', ' ').title()}</span>"
        f"<span class='exp-amt'>{_fmt(amt)}</span></div>"
        for name, amt in profile["savings_goals"].items()
    )

    return f"""
    <div class="dash-card">
      <div class="dash-title">💼 Live Financial Snapshot <span class="dash-user">#{user_id}</span></div>

      <div class="metric-grid">
        <div class="metric-box">
          <div class="metric-label">Liquid Cash</div>
          <div class="metric-value">{_fmt(liquid_cash)}</div>
        </div>
        <div class="metric-box">
          <div class="metric-label">Monthly Budget</div>
          <div class="metric-value">{_fmt(budget)}</div>
        </div>
      </div>

      <div class="progress-block">
        <div class="progress-top">
          <span>Spent {_fmt(total_spent)}</span>
          {status_badge}
        </div>
        <div class="progress-track">
          <div class="progress-fill" style="width:{pct:.1f}%; background:{bar_color};"></div>
        </div>
      </div>

      <div class="section-label">Expense Breakdown</div>
      {expense_rows}

      <div class="section-label">Savings Goals</div>
      {goal_rows}
    </div>
    """


CUSTOM_CSS = """
.gradio-container { background: linear-gradient(160deg, #0f172a 0%, #1e1b4b 45%, #0f172a 100%) !important; }

#hero-banner {
    background: linear-gradient(120deg, #6366f1 0%, #8b5cf6 50%, #ec4899 100%);
    border-radius: 18px;
    padding: 22px 28px;
    margin-bottom: 14px;
    box-shadow: 0 10px 30px rgba(99, 102, 241, 0.35);
}
#hero-banner h1 {
    color: white; margin: 0; font-size: 26px; font-weight: 800;
}
#hero-banner p {
    color: rgba(255,255,255,0.9); margin: 6px 0 0 0; font-size: 14px;
}

.dash-card {
    background: rgba(30, 27, 75, 0.55);
    border: 1px solid rgba(139, 92, 246, 0.35);
    border-radius: 16px;
    padding: 18px 20px;
    color: #e5e7eb;
    font-family: inherit;
}
.dash-title {
    font-size: 16px; font-weight: 700; color: #f9fafb; margin-bottom: 14px;
    display: flex; align-items: center; gap: 6px;
}
.dash-user { color: #a78bfa; font-size: 12px; font-weight: 600; }

.metric-grid { display: flex; gap: 12px; margin-bottom: 16px; }
.metric-box {
    flex: 1; background: rgba(99, 102, 241, 0.15);
    border: 1px solid rgba(99, 102, 241, 0.3);
    border-radius: 12px; padding: 10px 12px;
}
.metric-label { font-size: 11px; color: #a5b4fc; text-transform: uppercase; letter-spacing: 0.04em; }
.metric-value { font-size: 19px; font-weight: 700; color: #ffffff; margin-top: 2px; }

.progress-block { margin-bottom: 16px; }
.progress-top {
    display: flex; justify-content: space-between; align-items: center;
    font-size: 12px; color: #cbd5e1; margin-bottom: 6px;
}
.progress-track {
    height: 9px; background: rgba(255,255,255,0.08); border-radius: 999px; overflow: hidden;
}
.progress-fill { height: 100%; border-radius: 999px; transition: width 0.4s ease; }

.badge {
    font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 999px;
}
.badge-ok { background: rgba(34, 197, 94, 0.2); color: #4ade80; }
.badge-danger { background: rgba(244, 63, 94, 0.2); color: #fb7185; }

.section-label {
    font-size: 11px; font-weight: 700; color: #c4b5fd; text-transform: uppercase;
    letter-spacing: 0.05em; margin: 14px 0 6px 0;
}
.exp-row {
    display: flex; justify-content: space-between; padding: 6px 2px;
    border-bottom: 1px dashed rgba(255,255,255,0.08); font-size: 13px;
}
.exp-cat { color: #d1d5db; }
.exp-amt { color: #f9fafb; font-weight: 600; }

#quick-actions .gr-button { border-radius: 999px !important; }
"""


# =====================================================================
# 5. UI WITH GRADIO
# =====================================================================

def user_submit(message, history):
    if not message or not message.strip():
        return "", history
    history = history + [{"role": "user", "content": message}]
    return "", history

def bot_respond(history):
    if not API_KEY or API_KEY == "YOUR_GEMINI_API_KEY_HERE":
        history = history + [{
            "role": "assistant",
            "content": "⚠️ Please set your `GEMINI_API_KEY` environment variable before chatting."
        }]
        return history, render_dashboard(), json.dumps(USER_DB["U102"], indent=2)

    user_message = history[-1]["content"]
    try:
        response = chat.send_message(message=user_message)
        reply_text = response.text
    except Exception as e:
        reply_text = f"System Error: {str(e)}"

    history = history + [{"role": "assistant", "content": reply_text}]
    return history, render_dashboard(), json.dumps(USER_DB["U102"], indent=2)

QUICK_PROMPTS = [
    ("💸 Log ₹500 fuel expense", "I just spent ₹500 on fuel, please log it."),
    ("📊 Check my budget", "How is my budget looking this month?"),
    ("🍎 Buy Apple stock?", "Should I invest in Apple stock right now?"),
    ("🏖️ Book flight to Goa?", "Should I book a flight to Goa for my trip?"),
]

with gr.Blocks(title="Financial Decision Agent") as demo:

    gr.HTML("""
    <div id="hero-banner">
      <h1>🤖 Intelligent Financial Decision Agent</h1>
      <p>Agentic workflow with real tool calling — queries mock databases and market APIs autonomously before every answer.</p>
    </div>
    """)

    with gr.Row():
        with gr.Column(scale=4):
            dashboard_html = gr.HTML(render_dashboard())
            with gr.Accordion("🔍 Raw Backend State (Debug)", open=False):
                debug_json = gr.Code(json.dumps(USER_DB["U102"], indent=2), language="json")

        with gr.Column(scale=6):
            chatbot = gr.Chatbot(
                height=430,
                label="Chat with your Agent",
            )

            with gr.Row(elem_id="quick-actions"):
                quick_buttons = [gr.Button(label, size="sm") for label, _ in QUICK_PROMPTS]

            with gr.Row():
                txt = gr.Textbox(
                    placeholder="Ask about your budget, log an expense, or ask 'Should I invest in...?'",
                    show_label=False,
                    scale=8,
                    container=False,
                )
                send_btn = gr.Button("Send ➤", scale=1, variant="primary")

    # Wire up send (Enter key) and button click
    txt.submit(user_submit, [txt, chatbot], [txt, chatbot], queue=False).then(
        bot_respond, chatbot, [chatbot, dashboard_html, debug_json]
    )
    send_btn.click(user_submit, [txt, chatbot], [txt, chatbot], queue=False).then(
        bot_respond, chatbot, [chatbot, dashboard_html, debug_json]
    )

    # Wire up quick-action buttons: fill textbox then run the same submit chain
    for btn, (_, prompt_text) in zip(quick_buttons, QUICK_PROMPTS):
        btn.click(lambda p=prompt_text: p, None, txt, queue=False).then(
            user_submit, [txt, chatbot], [txt, chatbot], queue=False
        ).then(
            bot_respond, chatbot, [chatbot, dashboard_html, debug_json]
        )

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=10000,
        theme=gr.themes.Soft(primary_hue="violet", secondary_hue="pink"),
        css=CUSTOM_CSS,
    )
