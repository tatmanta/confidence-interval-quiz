from flask import Flask, render_template, request, redirect, url_for, session
from pathlib import Path
import json
import re

app = Flask(__name__)
app.secret_key = "change-this-secret"  # replace with any random string

# -----------------------------
# Number parsing / formatting
# -----------------------------

_SHORTHAND_RE = re.compile(r"""^\s*([+-]?\d*\.?\d+)\s*([kKmMbBtT])?\s*$""")


def parse_number(value: str):
    """
    Parse a human-entered number string such as:
      '40,000,000', '40.5', '40,000,000.25', '.5', '42.',
      plus shorthand:
      '10K', '10M', '3.2B', '1.2T' (case-insensitive).

    Returns float if valid, or None if invalid.
    """
    if value is None:
        return None

    s = str(value).strip()
    if s == "":
        return None

    # Remove common separators (spaces/underscores). Keep commas for validation.
    s = s.replace(" ", "").replace("_", "")

    # Allow leading '.' (e.g., ".5")
    if s.startswith("."):
        s = "0" + s

    # Allow trailing '.' (e.g., "42.")
    if s.endswith(".") and s.count(".") == 1:
        s = s[:-1]

    # Handle shorthand suffixes (K/M/B/T)
    shorthand_match = _SHORTHAND_RE.fullmatch(s.replace(",", ""))
    if shorthand_match:
        try:
            num = float(shorthand_match.group(1))
        except ValueError:
            return None
        suffix = (shorthand_match.group(2) or "").upper()
        multipliers = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}
        return num * multipliers.get(suffix, 1.0)

    # If not shorthand, validate numeric formatting with commas/decimals
    if not re.fullmatch(r"[0-9,\.]+", s):
        return None

    if ",," in s or ".." in s:
        return None

    if s.startswith(",") or s.endswith(","):
        return None

    if s.count(".") > 1:
        return None

    int_part, *rest = s.split(".")
    if "," in int_part:
        if not re.fullmatch(r"\d{1,3}(,\d{3})*", int_part):
            return None

    clean = s.replace(",", "")
    try:
        return float(clean)
    except ValueError:
        return None


def format_number(value):
    """Format a number with commas and minimal decimals."""
    if value is None:
        return ""

    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)

    if num.is_integer():
        return f"{int(num):,}"
    s = f"{num:,.4f}".rstrip("0").rstrip(".")
    return s


# -----------------------------
# Geo-ish default units (IP/country-ish)
# -----------------------------

def infer_default_unit_system(req) -> str | None:
    """
    Returns 'imperial' or 'metric' or None.
    Priority:
      1) Cloudflare country header (if present): CF-IPCountry
      2) Accept-Language heuristic (no IP needed)
    """
    # 1) Cloudflare (if you use it)
    cf_country = (req.headers.get("CF-IPCountry") or "").upper()
    if cf_country:
        return "imperial" if cf_country == "US" else "metric"

    # 2) Accept-Language (fallback)
    langs = [lang for (lang, _q) in req.accept_languages]
    blob = ",".join(langs).lower()
    if "en-us" in blob:
        return "imperial"
    return "metric"


# -----------------------------
# Questions
# IMPORTANT: remove unit text from question.text for any question using unit toggle.
# Add unit_kind for questions where you want the title suffix to switch.
# unit_kind must match what your question.html JS expects (e.g., height, length, distance, weight, temp).
# -----------------------------

QUESTIONS = [
    {
        "id": "q1",
        "text": "Distance from Earth to the nearest star (excluding the Sun), in light-years",
        "true_value": 4.2441,
        "unit": "light-years",
        # no toggle here; leave as-is
    },
    {
        "id": "q2",
        "text": "GDP of Mongolia, in USD",
        "true_value": 13_637_000_000,
        "unit": "USD",
        # no toggle here; leave as-is
    },
    {
        "id": "q3",
        "text": "Height of tallest man in recorded history (inches / cm)",
        "true_value": 107,  # inches
        "unit": "inches",
        "unit_kind": "height",
    },
    {
        "id": "q4",
        "text": "Depth of deepest part of Pacific Ocean (feet / meters)",
        "true_value": 10_984,  # meters
        "unit": "meters",
        "unit_kind": "length",
    },
    {
        "id": "q5",
        "text": "Average distance from Earth to the Moon (miles / km)",
        "true_value": 237_674.5,  # miles
        "unit": "miles",
        "unit_kind": "distance",
    },
    {
        "id": "q6",
        "text": "Population of Russia in 2019",
        "true_value": 145_872_256,
        "unit": "people",
    },
    {
        "id": "q7",
        "text": "Maximum number of passengers carried on an Emirates A380 (two-class layout)",
        "true_value": 615,
        "unit": "passengers",
    },
    {
        "id": "q8",
        "text": "Number of passengers who died on the Titanic",
        "true_value": 1_517,
        "unit": "people",
    },
    {
        "id": "q9",
        "text": "Market capitalization of Apple on the day Steve Jobs died, in USD",
        "true_value": 351_500_000_000,
        "unit": "USD",
    },
    {
    "id": "q10",
    "text": "Fastest lap time in an F1 car around the Monaco circuit, in seconds",
    "true_value": 74.260,  # seconds
    "unit": "seconds",
    "unit_kind": "time",
    },
    {
        "id": "q11",
        "text": "Number of regular season goals scored by Wayne Gretzky in his NHL career",
        "true_value": 894,
        "unit": "goals",
    },
    {
        "id": "q12",
        "text": "NASA's budget for the year 2019, in USD",
        "true_value": 19_653_000_000,
        "unit": "USD",
    },
    {
        "id": "q13",
        "text": "Number of Big Macs sold globally in a year (on average) by McDonald's",
        "true_value": 550_000_000,
        "unit": "Big Macs per year",
    },
    {
        "id": "q14",
        "text": "Number of students from China attending U.S. colleges in the 2018–2019 academic year",
        "true_value": 369_548,
        "unit": "students",
    },
    {
        "id": "q15",
        "text": "Total number of passengers flying domestically on U.S. airlines in 2019",
        "true_value": 811_400_000,
        "unit": "passengers",
    },
    {
        "id": "q16",
        "text": "Amount of coal produced by U.S. mines in 2019 (pounds / kg)",
        "true_value": 1_410_518_000_000,  # pounds
        "unit": "pounds",
        "unit_kind": "weight",
    },
    {
        "id": "q17",
        "text": "Breeds eligible to compete at the 144th Westminster Kennel Dog Show",
        "true_value": 205,
        "unit": "breeds and varieties",
    },
    {
        "id": "q18",
        "text": "Number of total worldwide searches processed by Google each day",
        "true_value": 3_500_000_000,
        "unit": "searches per day",
    },
    {
        "id": "q19",
        "text": "Full weight (including planes, ammunition, people) of a Nimitz-class aircraft carrier (pounds / kg)",
        "true_value": 226_679_700,  # pounds
        "unit": "pounds",
        "unit_kind": "weight",
    },
    {
        "id": "q20",
        "text": "Number of times that the name 'Jesus' appears in the King James Bible",
        "true_value": 942,
        "unit": "occurrences",
    },
]

TOTAL_QUESTIONS = len(QUESTIONS)
STATS_PATH = Path("stats.json")


def load_stats():
    """Load cumulative stats from disk or initialize."""
    if STATS_PATH.exists():
        try:
            with open(STATS_PATH, "r") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}

    data.setdefault("total_runs", 0)
    data.setdefault("total_correct", 0)
    data.setdefault("per_question", {})
    data.setdefault("history", [])

    for q in QUESTIONS:
        qid = q["id"]
        data["per_question"].setdefault(qid, {"attempts": 0, "correct": 0})

    return data


def save_stats(stats):
    with open(STATS_PATH, "w") as f:
        json.dump(stats, f, indent=2)


@app.route("/intro")
def intro():
    return render_template("intro.html")


@app.route("/")
def index():
    return redirect(url_for("intro"))


@app.route("/question/<int:index>", methods=["GET", "POST"])
def question(index):
    # If we’re at the first question, start a completely fresh quiz run
    if index == 0:
        session.clear()
        session["answers"] = {}
        session["stats_saved"] = False

    # Guard against invalid indices
    if index < 0 or index >= TOTAL_QUESTIONS:
        return redirect(url_for("results"))

    q = QUESTIONS[index]
    progress = int(index / TOTAL_QUESTIONS * 100)

    # Choose default unit system for THIS render:
    # 1) session preference (set from prior POSTs)
    # 2) infer from request (cloudflare/accept-language)
    # 3) fallback
    default_unit_system = session.get("unit_system") or infer_default_unit_system(request) or "imperial"

    if request.method == "POST":
        raw_lower = request.form.get("lower", "").strip()
        raw_upper = request.form.get("upper", "").strip()

        # Posted by template
        unit_system = request.form.get("unit_system")
        if unit_system in ("metric", "imperial"):
            session["unit_system"] = unit_system

        lower = parse_number(raw_lower)
        upper = parse_number(raw_upper)

        # Invalid numeric format
        if lower is None or upper is None:
            error = "Please enter valid numeric values (commas, decimals, and shorthand like 10M or 3.2B are allowed)."
            return render_template(
                "question.html",
                question=q,
                index=index,
                total=TOTAL_QUESTIONS,
                progress=progress,
                error=error,
                lower_value=raw_lower,
                upper_value=raw_upper,
                default_unit_system=default_unit_system,
            )

        # Logical check: lower must not exceed upper
        if lower > upper:
            error = "Lower bound must be less than or equal to upper bound."
            return render_template(
                "question.html",
                question=q,
                index=index,
                total=TOTAL_QUESTIONS,
                progress=progress,
                error=error,
                lower_value=raw_lower,
                upper_value=raw_upper,
                default_unit_system=default_unit_system,
            )

        # Save valid answer in session
        answers = session.get("answers", {})
        answers[q["id"]] = {"lower": lower, "upper": upper}
        session["answers"] = answers

        # Move to next question or results
        if index + 1 < TOTAL_QUESTIONS:
            return redirect(url_for("question", index=index + 1))
        return redirect(url_for("results"))

    # GET request: render the question form
    return render_template(
        "question.html",
        question=q,
        index=index,
        total=TOTAL_QUESTIONS,
        progress=progress,
        error=None,
        lower_value="",
        upper_value="",
        default_unit_system=default_unit_system,
    )


@app.route("/results")
def results():
    answers = session.get("answers")
    if not answers or len(answers) != TOTAL_QUESTIONS:
        return redirect(url_for("index"))

    per_question_results = []
    correct_count = 0

    for q in QUESTIONS:
        qid = q["id"]
        user_ans = answers.get(qid)
        true_value = q["true_value"]

        lower = user_ans["lower"]
        upper = user_ans["upper"]
        is_correct = lower <= true_value <= upper
        if is_correct:
            correct_count += 1

        per_question_results.append(
            {
                "id": qid,
                "text": q["text"],
                "unit": q.get("unit", ""),
                "lower": lower,
                "upper": upper,
                "true_value": true_value,
                "is_correct": is_correct,
            }
        )

    score_pct = round((correct_count / TOTAL_QUESTIONS) * 100, 1)

    if score_pct < 60:
        interpretation = (
            "Your intervals were too narrow: they behaved more like a low confidence level "
            "than 95%. This suggests strong overconfidence."
        )
    elif score_pct < 80:
        interpretation = (
            "Your intervals were still too narrow. You captured the true value less often "
            "than you would at 95% confidence."
        )
    elif score_pct < 95:
        interpretation = (
            "You’re getting closer to well-calibrated ranges, but still a bit overconfident "
            "compared with a true 95% confidence interval."
        )
    elif score_pct == 100:
        interpretation = (
            "You included the true value for every question. That means your intervals were "
            "closer to 100% confidence, i.e., wider than necessary for 95%."
        )
    else:
        interpretation = "Interesting result."

    stats = load_stats()

    if not session.get("stats_saved", False):
        stats["total_runs"] += 1
        stats["total_correct"] += correct_count

        for result in per_question_results:
            qid = result["id"]
            stats["per_question"][qid]["attempts"] += 1
            if result["is_correct"]:
                stats["per_question"][qid]["correct"] += 1

        save_stats(stats)
        session["stats_saved"] = True

    global_avg_correct_pct = round(
        (stats["total_correct"] / (stats["total_runs"] * TOTAL_QUESTIONS)) * 100, 1
    )

    per_question_stats = []
    for q in QUESTIONS:
        qid = q["id"]
        s = stats["per_question"][qid]
        correct_pct = round((s["correct"] / s["attempts"]) * 100, 1) if s["attempts"] > 0 else 0.0
        per_question_stats.append(
            {"id": qid, "text": q["text"], "correct_pct": correct_pct, "attempts": s["attempts"]}
        )

    return render_template(
        "results.html",
        total=TOTAL_QUESTIONS,
        correct_count=correct_count,
        score_pct=score_pct,
        interpretation=interpretation,
        per_question_results=per_question_results,
        global_avg_correct_pct=global_avg_correct_pct,
        total_runs=stats["total_runs"],
        per_question_stats=per_question_stats,
        format_number=format_number,
    )


if __name__ == "__main__":
    app.run(debug=True)
