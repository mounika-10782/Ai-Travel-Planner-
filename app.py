
from flask import Flask, render_template, request
import json

app = Flask(__name__)
app.jinja_env.globals.update(enumerate=enumerate)

# ============================================================
# KNOWLEDGE BASE — facts the AI uses to make decisions
# ============================================================

DISTANCES = {
    ("Delhi",     "Mumbai"):    1400,
    ("Delhi",     "Goa"):       1900,
    ("Delhi",     "Bangalore"): 2100,
    ("Delhi",     "Jaipur"):     280,
    ("Delhi",     "Agra"):       200,
    ("Delhi",     "Manali"):     530,
    ("Delhi",     "Varanasi"):   820,
    ("Mumbai",    "Goa"):        600,
    ("Mumbai",    "Bangalore"):  980,
    ("Mumbai",    "Hyderabad"):  710,
    ("Bangalore", "Goa"):        560,
    ("Bangalore", "Hyderabad"):  570,
    ("Bangalore", "Ooty"):       270,
    ("Agra",      "Varanasi"):   620,
    ("Jaipur",    "Agra"):       230,
}

TRANSPORT_COST = { "flight": 400, "train": 80, "bus": 30, "cab": 200 }
TRANSPORT_ICON = { "flight": "✈️", "train": "🚆", "bus": "🚌", "cab": "🚗" }

HOTEL_COST  = { "budget": 800, "standard": 2500, "premium": 6000, "luxury": 15000 }
HOTEL_STARS = { "budget": "★★", "standard": "★★★", "premium": "★★★★", "luxury": "★★★★★" }

FOOD_COST = { "budget": 900, "standard": 2400, "premium": 5400 }

ATTRACTIONS = {
    "Delhi":     ["Red Fort", "Qutub Minar", "India Gate", "Lotus Temple"],
    "Mumbai":    ["Gateway of India", "Marine Drive", "Elephanta Caves"],
    "Goa":       ["Baga Beach", "Basilica of Bom Jesus", "Fort Aguada", "Dudhsagar Falls"],
    "Bangalore": ["Lalbagh Garden", "Cubbon Park", "ISKCON Temple"],
    "Hyderabad": ["Charminar", "Golconda Fort", "Ramoji Film City"],
    "Jaipur":    ["Amber Fort", "Hawa Mahal", "City Palace", "Jantar Mantar"],
    "Agra":      ["Taj Mahal", "Agra Fort", "Fatehpur Sikri"],
    "Manali":    ["Rohtang Pass", "Solang Valley", "Hadimba Temple"],
    "Ooty":      ["Ooty Lake", "Nilgiri Railway", "Doddabetta Peak"],
    "Varanasi":  ["Kashi Vishwanath", "Dashashwamedh Ghat", "Sarnath"],
}

CITIES = list(ATTRACTIONS.keys())

# ============================================================
# STRIPS WORLD STATE
# The world is a Python SET of true facts.
# e.g. {"at:Delhi", "transport_available:train"}
# ============================================================

class WorldState:
    def __init__(self, facts):
        self.facts = set(facts)

    def is_true(self, predicate):
        return predicate in self.facts

    def add(self, predicate):
        self.facts.add(predicate)

    def remove(self, predicate):
        self.facts.discard(predicate)

    def snapshot(self):
        return sorted(self.facts)


# ============================================================
# STRIPS OPERATORS
# Each has: precondition check → apply effects → return cost
# ============================================================

def get_distance(a, b):
    return DISTANCES.get((a, b)) or DISTANCES.get((b, a)) or 1500


def op_travel(state, from_city, to_city, mode):
    """TRAVEL operator — move between cities."""
    if not state.is_true(f"at:{from_city}"):
        return False, 0, "", ""
    if state.is_true(f"at:{to_city}"):
        return False, 0, "", ""
    if not state.is_true(f"transport_available:{mode}"):
        return False, 0, "", ""

    dist = get_distance(from_city, to_city)
    cost = round(dist * TRANSPORT_COST[mode] / 100)

    # Apply STRIPS effects
    state.remove(f"at:{from_city}")    # DELETE effect
    state.add(f"at:{to_city}")         # ADD effect
    state.add(f"visited:{to_city}")    # ADD effect

    desc = f"{from_city} → {to_city}"
    sub  = f"{TRANSPORT_ICON[mode]} {mode.title()} · ~{dist} km"
    return True, cost, desc, sub


def op_book_hotel(state, city, hotel_type, nights):
    """BOOK-HOTEL operator — reserve accommodation."""
    if not state.is_true(f"at:{city}"):
        return False, 0, "", ""
    if state.is_true(f"has_accom:{city}"):
        return False, 0, "", ""

    cost = HOTEL_COST[hotel_type] * nights
    state.add(f"has_accom:{city}")     # ADD effect

    desc = f"{hotel_type.title()} Hotel — {city}"
    sub  = f"{nights} night(s) · {HOTEL_STARS[hotel_type]}"
    return True, cost, desc, sub


def op_visit_attraction(state, attraction, city):
    """VISIT-ATTRACTION operator — sightsee."""
    if not state.is_true(f"at:{city}"):
        return False, 0, "", ""
    if not state.is_true(f"has_accom:{city}"):
        return False, 0, "", ""
    if state.is_true(f"seen:{attraction}"):
        return False, 0, "", ""

    state.add(f"seen:{attraction}")    # ADD effect

    desc = attraction
    sub  = f"Sightseeing · {city}"
    return True, 300, desc, sub


def op_arrange_meals(state, city, food_type, days):
    """ARRANGE-MEALS operator — plan food."""
    if not state.is_true(f"at:{city}"):
        return False, 0, "", ""
    if state.is_true(f"meals:{city}"):
        return False, 0, "", ""

    cost = FOOD_COST[food_type] * days
    state.add(f"meals:{city}")         # ADD effect

    desc = f"{food_type.title()} Dining — {city}"
    sub  = f"{days} day(s)"
    return True, cost, desc, sub


# ============================================================
# GOAL STACK PLANNER — the core AI algorithm
# 1. Build a list of goals (the "Goal Stack")
# 2. For each goal: check precondition → apply operator
# 3. Collect steps → return final plan
# ============================================================

def goal_stack_planner(origin, destination, stopovers,
                        total_days, budget,
                        transport_mode, hotel_type, food_type):

    # ── Initial World State ──
    state = WorldState([
        f"at:{origin}",
        f"transport_available:{transport_mode}",
    ])

    all_route    = [origin] + stopovers + [destination]
    visit_cities = stopovers + [destination]
    days_per_city = max(1, total_days // len(visit_cities))

    # ── Build the Goal Stack ──
    goals = []
    for i in range(len(all_route) - 1):
        goals.append({"type": "TRAVEL",
                       "from_city": all_route[i],
                       "to_city":   all_route[i+1],
                       "mode":      transport_mode})

    for city in visit_cities:
        goals.append({"type": "HOTEL", "city": city, "nights": days_per_city})
        n_attr = min(3, days_per_city + 1)
        for attr in ATTRACTIONS.get(city, [])[:n_attr]:
            goals.append({"type": "VISIT", "attraction": attr, "city": city})
        goals.append({"type": "MEALS", "city": city, "days": days_per_city})

    # ── Resolve each goal ──
    plan_steps = []
    trace_log  = []
    total_cost = 0
    step_num   = 1

    for goal in goals:
        success, cost, desc, sub = False, 0, "", ""

        if goal["type"] == "TRAVEL":
            success, cost, desc, sub = op_travel(
                state, goal["from_city"], goal["to_city"], goal["mode"])
            op_name = "TRAVEL"

        elif goal["type"] == "HOTEL":
            success, cost, desc, sub = op_book_hotel(
                state, goal["city"], hotel_type, goal["nights"])
            op_name = "BOOK-HOTEL"

        elif goal["type"] == "VISIT":
            success, cost, desc, sub = op_visit_attraction(
                state, goal["attraction"], goal["city"])
            op_name = "VISIT-ATTRACTION"

        elif goal["type"] == "MEALS":
            success, cost, desc, sub = op_arrange_meals(
                state, goal["city"], food_type, goal["days"])
            op_name = "ARRANGE-MEALS"

        else:
            continue

        trace_log.append({
            "goal": goal["type"],
            "detail": goal.get("to_city") or goal.get("attraction") or goal.get("city",""),
            "operator": op_name,
            "success": success,
            "cost": cost,
        })

        if success:
            total_cost += cost
            plan_steps.append({
                "step":     step_num,
                "type":     goal["type"],
                "operator": op_name,
                "desc":     desc,
                "sub":      sub,
                "cost":     cost,
            })
            step_num += 1

    # ── Build cost breakdown ──
    category_totals = {}
    for s in plan_steps:
        category_totals[s["type"]] = category_totals.get(s["type"], 0) + s["cost"]

    # ── Format goal stack for display ──
    goal_stack_display = []
    for i, g in enumerate(goals):
        idx = len(goals) - i
        if g["type"] == "TRAVEL":
            detail = f"{g['from_city']} → {g['to_city']}"
        elif g["type"] == "HOTEL":
            detail = f"{g['city']} ({g['nights']} nights)"
        elif g["type"] == "VISIT":
            detail = f"{g['attraction']} in {g['city']}"
        else:
            detail = f"{g['city']} ({g['days']} days)"
        goal_stack_display.append({"idx": idx, "type": g["type"], "detail": detail})

    return {
        "steps":          plan_steps,
        "total_cost":     total_cost,
        "feasible":       total_cost <= budget,
        "goal_reached":   state.is_true(f"at:{destination}"),
        "trace":          trace_log,
        "goal_stack":     goal_stack_display,
        "final_state":    state.snapshot(),
        "budget":         budget,
        "category_totals": category_totals,
        "days_per_city":  days_per_city,
        "route":          all_route,
        "goals_count":    len(goals),
        "ops_count":      len(plan_steps),
        "satisfied_count": sum(1 for t in trace_log if t["success"]),
    }


# ============================================================
# FLASK ROUTES
# ============================================================

@app.route("/", methods=["GET"])
def index():
    """Show the main input form."""
    return render_template("index.html", cities=CITIES)


@app.route("/plan", methods=["POST"])
def plan():
    """
    Receive form data from the user,
    run the Python AI planner,
    send results to the results page.
    """
    # Read form inputs
    origin        = request.form.get("origin", "Delhi")
    destination   = request.form.get("destination", "Goa")
    stopovers_raw = request.form.get("stopovers", "")
    total_days    = int(request.form.get("days", 5))
    budget        = int(request.form.get("budget", 30000))
    transport     = request.form.get("transport", "train")
    hotel         = request.form.get("hotel", "standard")
    food          = request.form.get("food", "standard")

    # Parse stopovers (comma-separated)
    stopovers = [s.strip() for s in stopovers_raw.split(",") if s.strip() and s.strip() != origin and s.strip() != destination]

    # Validate
    if origin == destination:
        return render_template("index.html", cities=CITIES,
                               error="Origin and destination cannot be the same city!")

    # ── RUN THE AI PLANNER ──
    result = goal_stack_planner(
        origin, destination, stopovers,
        total_days, budget, transport, hotel, food
    )

    # Pass everything to the results template
    return render_template("result.html",
                           result=result,
                           origin=origin,
                           destination=destination,
                           stopovers=stopovers,
                           days=total_days,
                           budget=budget,
                           transport=transport,
                           hotel=hotel,
                           food=food,
                           hotel_stars=HOTEL_STARS,
                           transport_icon=TRANSPORT_ICON)


if __name__ == "__main__":
    print("\n" + "="*50)
    print("  WanderAI — Travel Planner (Flask)")
    print("  Open browser: http://127.0.0.1:5000")
    print("="*50 + "\n")
    app.run(debug=True)
