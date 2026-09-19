import os
import json
import html
import inspect
import gradio as gr
from google import genai
from google.genai import types

# =====================================================================
# 1. MOCK ENTERPRISE DATABASES & APIs
# =====================================================================

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
        score -= 40
    if asset_risk.lower() == "high":
        score -= 25
    elif asset_risk.lower() == "medium":
        score -= 10

    verdict = "RECOMMENDED" if score >= 65 else "NOT RECOMMENDED"
    return json.dumps({"confidence_score": f"{score}%", "verdict": verdict})

financial_tools = [get_financial_profile, log_expense, fetch_market_data, calculate_confidence_score]

# =====================================================================
# 3. LLM ORCHESTRATOR
# =====================================================================

API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
SHOW_DEBUG = os.environ.get("SHOW_DEBUG", "0") == "1"   # set SHOW_DEBUG=1 to see raw data panel

client = genai.Client(api_key=API_KEY)

chat_config = types.GenerateContentConfig(
    tools=financial_tools,
    system_instruction=(
        "You are a friendly, plain-spoken personal finance assistant. "
        "When a user asks a financial question, you must autonomously use the provided tools to gather data before answering. "
        "1. If logging an expense, use log_expense. "
        "2. If asked about adjusting spending, use get_financial_profile. "
        "3. If asked 'Should I buy/invest/book?', use get_financial_profile to check their cash, then use fetch_market_data, "
        "and finally use calculate_confidence_score. "
        "Always present the final answer clearly with the Confidence Score and Verdict if applicable. "
        "Write for an everyday person, not a finance professional: start with a one-line answer (yes / no / not yet), "
        "then give 2-3 short reasons. Use Indian rupee amounts (₹). Keep replies under 120 words unless asked for more."
    )
)

chat = client.chats.create(model=MODEL_NAME, config=chat_config)

# =====================================================================
# 4. DASHBOARD RENDERING HELPERS
# =====================================================================

CATEGORY_COLORS = ["#0B6B57", "#C98305", "#3F5FA8", "#B5477A", "#6B7F3A", "#7A5CC4"]
EXPENSE_CATEGORIES = ["Food", "Fuel", "Utilities", "Shopping", "Travel", "Health", "Other"]


def inr(amount: float) -> str:
    """Format a number as rupees with Indian digit grouping, e.g. ₹1,25,000."""
    negative = amount < 0
    digits = str(int(round(abs(amount))))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return f"{'-' if negative else ''}₹{digits}"


def _label(text: str) -> str:
    return html.escape(text.replace("_", " ").strip().title())


def render_dashboard(user_id: str = "U102") -> str:
    profile = USER_DB.get(user_id)
    if not profile:
        return "<div class='card'><p>We couldn't find your profile.</p></div>"

    budget = profile["monthly_budget"]
    cash = profile["liquid_cash"]
    expenses = profile["expenses"]
    spent = sum(expenses.values())
    ratio = spent / budget if budget else 0

    # Tone drives the colour of the headline, pill and bar
    if spent > budget:
        tone, pill = "over", "Over budget"
        headline, caption = inr(spent - budget), "over your monthly budget"
    elif ratio > 0.75:
        tone, pill = "watch", "Getting close"
        headline, caption = inr(budget - spent), "left to spend this month"
    else:
        tone, pill = "ok", "On track"
        headline, caption = inr(budget - spent), "left to spend this month"

    scale = max(spent, budget, 1)
    fill_pct = spent / scale * 100
    marker_pct = budget / scale * 100

    # Categories, biggest first
    rows = []
    ordered = sorted(expenses.items(), key=lambda kv: kv[1], reverse=True)
    for i, (cat, amt) in enumerate(ordered):
        color = CATEGORY_COLORS[i % len(CATEGORY_COLORS)]
        share = (amt / spent * 100) if spent else 0
        zero = " zero" if amt <= 0 else ""
        rows.append(
            f"<div class='cat{zero}'>"
            f"<div class='cat-top'><span class='dot' style='background:{color}'></span>"
            f"<span class='cat-name'>{_label(cat)}</span>"
            f"<span class='cat-amt'>{inr(amt)}</span></div>"
            f"<div class='mini-track'><div class='mini-fill' style='width:{share:.1f}%;background:{color}'></div></div>"
            f"</div>"
        )
    category_html = "".join(rows) or "<p class='empty'>No spending logged yet. Add your first expense below.</p>"

    # Savings goals: how much of the goal your cash on hand could cover
    goals = []
    for name, target in profile["savings_goals"].items():
        covered = max(0, min(cash / target * 100, 100)) if target else 0
        goals.append(
            f"<div class='goal'>"
            f"<div class='cat-top'><span class='cat-name'>{_label(name)}</span>"
            f"<span class='cat-amt'>{inr(target)}</span></div>"
            f"<div class='mini-track'><div class='mini-fill' style='width:{covered:.0f}%;background:var(--green)'></div></div>"
            f"<div class='note'>Your cash on hand covers {covered:.0f}% of this goal</div>"
            f"</div>"
        )
    goals_html = "".join(goals) or "<p class='empty'>No savings goals yet.</p>"

    return f"""
    <div class="card summary">
      <div class="summary-head">
        <span class="card-title">This month</span>
        <span class="pill pill-{tone}">{pill}</span>
      </div>

      <div class="headline headline-{tone}">{headline}</div>
      <div class="caption">{caption}</div>

      <div class="track">
        <div class="fill fill-{tone}" style="width:{fill_pct:.1f}%"></div>
        <div class="marker" style="left:{marker_pct:.1f}%"></div>
      </div>
      <div class="track-legend">
        <span>Spent {inr(spent)}</span>
        <span>Budget {inr(budget)}</span>
      </div>

      <div class="stats">
        <div class="stat">
          <div class="stat-label">Cash available</div>
          <div class="stat-value">{inr(cash)}</div>
        </div>
        <div class="stat">
          <div class="stat-label">Monthly budget</div>
          <div class="stat-value">{inr(budget)}</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Where your money went</div>
      <div class="cat-list">{category_html}</div>
    </div>

    <div class="card">
      <div class="card-title">Savings goals</div>
      <div class="cat-list">{goals_html}</div>
    </div>
    """


HEADER_HTML = """
<div class="topbar">
  <div class="logo" aria-hidden="true">₹</div>
  <div>
    <h1>Money Assistant</h1>
    <p>Track your spending, check your budget, and get a clear answer before you buy.</p>
  </div>
</div>
"""

# =====================================================================
# 5. UI STYLING
# =====================================================================

CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=Figtree:wght@400;500;600;700&display=swap');

:root {
    --paper: #F2F5F3;
    --surface: #FFFFFF;
    --ink: #12231E;
    --muted: #5F716B;
    --line: #DCE4E0;
    --green: #0B6B57;
    --green-soft: #E1F1EB;
    --red: #C63D2B;
    --red-soft: #FBE7E3;
    --amber: #B87500;
    --amber-soft: #FBF0D6;
    --display: 'Bricolage Grotesque', 'Figtree', system-ui, sans-serif;
}

body, .gradio-container {
    background: var(--paper) !important;
    color: var(--ink);
    font-family: 'Figtree', system-ui, sans-serif !important;
}
.gradio-container { max-width: 1120px !important; margin: 0 auto !important; }
footer { display: none !important; }

/* ---------- Header ---------- */
.topbar { display: flex; align-items: center; gap: 16px; padding: 8px 4px 4px; }
.logo {
    width: 48px; height: 48px; flex: none; border-radius: 14px;
    background: var(--green); color: #fff;
    display: grid; place-items: center;
    font-family: var(--display); font-weight: 800; font-size: 26px;
}
.topbar h1 { margin: 0; font-family: var(--display); font-size: 28px; font-weight: 800; letter-spacing: -0.02em; color: var(--ink); }
.topbar p { margin: 2px 0 0; color: var(--muted); font-size: 15px; line-height: 1.4; max-width: 60ch; }

/* ---------- Cards ---------- */
.card {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 18px;
    padding: 20px;
    margin-bottom: 14px;
    color: var(--ink);
}
.card-title { font-family: var(--display); font-weight: 700; font-size: 16px; color: var(--ink); }
.card .card-title { display: block; margin-bottom: 14px; }
.summary .card-title { margin-bottom: 0; }
.summary-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }

/* ---------- Headline number ---------- */
.headline {
    font-family: var(--display); font-weight: 800; font-size: 48px; line-height: 1;
    letter-spacing: -0.03em; font-variant-numeric: tabular-nums;
}
.headline-ok { color: var(--green); }
.headline-watch { color: var(--amber); }
.headline-over { color: var(--red); }
.caption { margin-top: 6px; color: var(--muted); font-size: 15px; }

.pill { font-size: 13px; font-weight: 600; padding: 4px 12px; border-radius: 999px; }
.pill-ok { background: var(--green-soft); color: var(--green); }
.pill-watch { background: var(--amber-soft); color: var(--amber); }
.pill-over { background: var(--red-soft); color: var(--red); }

/* ---------- Budget bar ---------- */
.track {
    position: relative; height: 14px; margin-top: 20px;
    background: #E9EEEB; border-radius: 999px; overflow: visible;
}
.fill { height: 100%; border-radius: 999px; animation: grow 0.9s cubic-bezier(0.16, 1, 0.3, 1) both; }
.fill-ok { background: var(--green); }
.fill-watch { background: #E0A100; }
.fill-over { background: var(--red); }
.marker {
    position: absolute; top: -5px; bottom: -5px; width: 3px; margin-left: -1.5px;
    background: var(--ink); border-radius: 2px;
}
.track-legend {
    display: flex; justify-content: space-between; margin-top: 10px;
    font-size: 13px; color: var(--muted); font-variant-numeric: tabular-nums;
}
@keyframes grow { from { width: 0; } }

/* ---------- Stats ---------- */
.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 20px; }
.stat { background: var(--paper); border-radius: 12px; padding: 12px 14px; }
.stat-label { font-size: 13px; color: var(--muted); }
.stat-value { margin-top: 2px; font-family: var(--display); font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }

/* ---------- Category & goal lists ---------- */
.cat-list { display: flex; flex-direction: column; gap: 14px; }
.cat-top { display: flex; align-items: center; gap: 10px; }
.dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
.cat-name { flex: 1; font-weight: 500; font-size: 15px; }
.cat-amt { font-weight: 600; font-size: 15px; font-variant-numeric: tabular-nums; }
.cat.zero { opacity: 0.55; }
.mini-track { height: 6px; background: #E9EEEB; border-radius: 999px; margin-top: 8px; overflow: hidden; }
.mini-fill { height: 100%; border-radius: 999px; animation: grow 0.9s cubic-bezier(0.16, 1, 0.3, 1) both; }
.note { margin-top: 8px; font-size: 13px; color: var(--muted); }
.empty { margin: 0; color: var(--muted); font-size: 14px; }

/* ---------- Add expense ---------- */
#add-expense { padding: 16px; }
#add-expense .panel-title { font-family: var(--display); font-weight: 700; font-size: 16px; margin-bottom: 4px; }
.add-status { min-height: 22px; margin-top: 4px; font-size: 14px; font-weight: 500; }
.add-status.ok { color: var(--green); }
.add-status.warn { color: var(--red); }

/* ---------- Chat ---------- */
#chat { border-radius: 18px !important; }
#chat [data-testid="user"] {
    background: var(--green) !important; color: #fff !important;
    border: none !important; border-radius: 16px 16px 4px 16px !important;
}
#chat [data-testid="bot"] {
    background: var(--paper) !important; color: var(--ink) !important;
    border: 1px solid var(--line) !important; border-radius: 16px 16px 16px 4px !important;
}
#chat [data-testid="user"] * { color: #fff !important; }
#chat .prose, #chat .message { font-size: 15px; line-height: 1.55; }

/* Suggestion chips */
#chips { gap: 8px !important; flex-wrap: wrap !important; }
.chip {
    background: var(--surface) !important; color: var(--green) !important;
    border: 1px solid var(--line) !important; border-radius: 999px !important;
    font-weight: 600 !important; font-size: 14px !important; min-width: 0 !important;
    box-shadow: none !important; transition: background 0.15s ease, border-color 0.15s ease;
}
.chip:hover { background: var(--green-soft) !important; border-color: var(--green) !important; }

/* Buttons & inputs */
button:focus-visible, input:focus-visible, textarea:focus-visible, select:focus-visible {
    outline: 3px solid rgba(11, 107, 87, 0.35) !important; outline-offset: 2px;
}
button.primary { font-weight: 600 !important; border-radius: 12px !important; }
#msg-box textarea { font-size: 16px !important; }

/* Phones */
@media (max-width: 640px) {
    .topbar h1 { font-size: 23px; }
    .headline { font-size: 40px; }
    .card { padding: 16px; }
}
@media (prefers-reduced-motion: reduce) {
    .fill, .mini-fill { animation: none; }
}
"""

# Keep the app in light mode regardless of the visitor's OS setting
FORCE_LIGHT_JS = """
() => {
  const b = document.body;
  const force = () => b.classList.remove('dark');
  force();
  new MutationObserver(force).observe(b, { attributes: true, attributeFilter: ['class'] });
}
"""

theme = gr.themes.Base(
    primary_hue=gr.themes.colors.emerald,
    neutral_hue=gr.themes.colors.slate,
    radius_size=gr.themes.sizes.radius_lg,
    font=[gr.themes.GoogleFont("Figtree"), "system-ui", "sans-serif"],
).set(
    body_background_fill="#F2F5F3",
    body_text_color="#12231E",
    block_background_fill="#FFFFFF",
    block_border_width="1px",
    block_border_color="#DCE4E0",
    block_shadow="none",
    input_background_fill="#FFFFFF",
    input_border_color="#CBD6D1",
    button_primary_background_fill="#0B6B57",
    button_primary_background_fill_hover="#085A49",
    button_primary_text_color="#FFFFFF",
)

# =====================================================================
# 6. APP LOGIC & UI WITH GRADIO
# =====================================================================

def _supported(fn, **kwargs):
    """Keep only the keyword args this Gradio version accepts (API differs between releases)."""
    params = inspect.signature(fn).parameters
    return {k: v for k, v in kwargs.items() if k in params}


def _extract_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join([part.get("text", "") if isinstance(part, dict) else part for part in content])
    return "" if content is None else str(content)


def _debug_state() -> str:
    return json.dumps(USER_DB["U102"], indent=2)


def user_submit(message, history):
    history = history or []
    if not message or not message.strip():
        return "", history
    return "", history + [{"role": "user", "content": message.strip()}]


def bot_respond(history):
    history = history or []
    if not history or history[-1].get("role") != "user":
        yield history, gr.update(), gr.update()
        return

    if not API_KEY or API_KEY == "YOUR_GEMINI_API_KEY_HERE":
        history = history + [{
            "role": "assistant",
            "content": "The assistant isn't connected yet. Add your `GEMINI_API_KEY` as an environment variable and restart the app."
        }]
        yield history, render_dashboard(), _debug_state()
        return

    # Show a quick status while the agent looks up the numbers
    thinking = history + [{"role": "assistant", "content": "Checking your numbers…"}]
    yield thinking, gr.update(), gr.update()

    user_message = _extract_text(history[-1]["content"])
    try:
        response = chat.send_message(message=user_message)
        reply_text = response.text or "I couldn't put together an answer for that. Could you rephrase it?"
    except Exception as e:
        print(f"[agent error] {e}")
        reply_text = "Something went wrong while checking your numbers. Please try again in a moment."

    history = history + [{"role": "assistant", "content": reply_text}]
    yield history, render_dashboard(), _debug_state()


def add_expense_manual(category, amount):
    """Add an expense straight from the form, without going through the chat."""
    try:
        amount = float(amount or 0)
    except (TypeError, ValueError):
        amount = 0
    if not category or amount <= 0:
        return (gr.update(), gr.update(),
                "<div class='add-status warn'>Enter an amount greater than ₹0.</div>", gr.update())

    result = json.loads(log_expense(category, amount))
    over = str(result.get("alert", "")).startswith("CRITICAL")
    msg = f"Added {inr(amount)} to {html.escape(category)}. Cash left: {inr(result.get('new_balance', 0))}."
    if over:
        msg += " You're over budget this month."
    css = "warn" if over else "ok"
    return render_dashboard(), _debug_state(), f"<div class='add-status {css}'>{msg}</div>", None


QUICK_PROMPTS = [
    ("Log ₹500 for fuel", "I just spent ₹500 on fuel, please log it."),
    ("How's my budget?", "How is my budget looking this month?"),
    ("Should I buy Apple stock?", "Should I invest in Apple stock right now?"),
    ("Can I book Goa flights?", "Should I book a flight to Goa for my trip?"),
]

CHAT_PLACEHOLDER = (
    "**Ask me anything about your money.**\n\n"
    "I can log an expense, check your budget, or tell you whether a purchase makes sense. "
    "Tap a suggestion below to start."
)

# Newer Gradio versions moved theme/css/js from Blocks() to launch(); support both.
ui_options = dict(theme=theme, css=CUSTOM_CSS, js=FORCE_LIGHT_JS)
blocks_options = _supported(gr.Blocks.__init__, **ui_options)
launch_options = {k: v for k, v in ui_options.items() if k not in blocks_options}

with gr.Blocks(title="Money Assistant", **blocks_options) as demo:

    gr.HTML(HEADER_HTML)

    with gr.Row(equal_height=False):

        # ---------- Left: your numbers ----------
        with gr.Column(scale=5, min_width=320):
            dashboard_html = gr.HTML(render_dashboard())

            with gr.Group(elem_id="add-expense"):
                gr.HTML("<div class='panel-title'>Add an expense</div>")
                with gr.Row():
                    exp_category = gr.Dropdown(EXPENSE_CATEGORIES, value="Food", label="Category", min_width=140)
                    exp_amount = gr.Number(label="Amount (₹)", value=None, minimum=0, min_width=140)
                add_btn = gr.Button("Add expense", variant="primary")
                add_status = gr.HTML("")

            debug_json = gr.Code(_debug_state(), language="json", label="Raw data (debug)", visible=SHOW_DEBUG)

        # ---------- Right: chat ----------
        with gr.Column(scale=7, min_width=340):
            chatbot = gr.Chatbot(**_supported(
                gr.Chatbot.__init__,
                elem_id="chat",
                type="messages",
                height=540,
                show_label=False,
                bubble_full_width=False,
                show_copy_button=True,
                placeholder=CHAT_PLACEHOLDER,
                avatar_images=(None, None),
            ))

            with gr.Row(elem_id="chips"):
                chip_buttons = [
                    gr.Button(label, size="sm", elem_classes="chip", min_width=0)
                    for label, _ in QUICK_PROMPTS
                ]

            with gr.Row(equal_height=True):
                txt = gr.Textbox(
                    placeholder="Ask about your budget, or “Should I buy…?”",
                    show_label=False,
                    scale=8,
                    container=False,
                    elem_id="msg-box",
                )
                send_btn = gr.Button("Send", scale=1, variant="primary", min_width=90)

    # ---------- Wiring ----------
    outputs = [chatbot, dashboard_html, debug_json]

    txt.submit(user_submit, [txt, chatbot], [txt, chatbot], queue=False).then(bot_respond, chatbot, outputs)
    send_btn.click(user_submit, [txt, chatbot], [txt, chatbot], queue=False).then(bot_respond, chatbot, outputs)

    for btn, (_, prompt_text) in zip(chip_buttons, QUICK_PROMPTS):
        btn.click(
            lambda history, p=prompt_text: user_submit(p, history)[1],
            chatbot, chatbot, queue=False,
        ).then(bot_respond, chatbot, outputs)

    add_btn.click(
        add_expense_manual,
        [exp_category, exp_amount],
        [dashboard_html, debug_json, add_status, exp_amount],
    )

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=10000,
        **launch_options,
    )
