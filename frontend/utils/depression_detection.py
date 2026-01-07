"""
Depression Detection Logic Module

Goal
-----
Provide a simple, explainable, and stable signal for whether a user is
likely experiencing ongoing low mood based on their own journal entries.

This module is intentionally non-diagnostic and uses calm, transparent rules.
It avoids reacting to a single bad day, focuses on recent entries, and
produces user-friendly outputs.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


# ----------------------------
# Thresholds and simple rules
# ----------------------------
BDI_MILD_THRESHOLD = 10  # Single entry is considered low mood if >= 10
STREAK_MIN = 5           # Number of consecutive entries >= 10 to signal concern
WINDOW_DAYS = 30         # Recent window for pattern detection
MIN_ENTRIES_FOR_DETECTION = 10  # Require this many entries to make a call


def evaluate_recent_data_requirements(
	df: pd.DataFrame,
	*,
	window_days: int = 30,
	min_entries: int = 10,
	min_distinct_days: int = 5,
	reference_dt: Optional[datetime] = None,
) -> Dict:
	"""Evaluate whether the dashboard should be shown based on recent data.

	Requirement
	-----------
	- >= `min_entries` total entries
	- Entries span >= `min_distinct_days` distinct calendar days
	- Within the last `window_days` days

	Notes
	-----
	This is intended for gating dashboards. It operates on the provided DataFrame
	(which in this app usually contains *analyzed* entries produced by
	`prepare_dashboard_data`).
	"""
	if df is None or df.empty or "datetime" not in df.columns:
		return {
			"meets": False,
			"recent_entries": 0,
			"distinct_days": 0,
			"window_days": int(window_days),
			"min_entries": int(min_entries),
			"min_distinct_days": int(min_distinct_days),
			"message": (
				"Not enough recent entries to show the dashboard yet. "
				"Keep journaling to unlock insights."
			),
		}

	work = df[["datetime"]].copy()
	work["datetime"] = _ensure_datetime(work["datetime"])  # invalid -> NaT
	work = work.dropna(subset=["datetime"])
	if work.empty:
		return {
			"meets": False,
			"recent_entries": 0,
			"distinct_days": 0,
			"window_days": int(window_days),
			"min_entries": int(min_entries),
			"min_distinct_days": int(min_distinct_days),
			"message": (
				"Not enough recent entries to show the dashboard yet. "
				"Keep journaling to unlock insights."
			),
		}

	ref = reference_dt or datetime.now()
	cutoff = ref - timedelta(days=window_days)
	recent = work[work["datetime"] >= cutoff]

	recent_entries = int(len(recent))
	distinct_days = int(recent["datetime"].dt.date.nunique()) if recent_entries > 0 else 0

	meets = (recent_entries >= min_entries) and (distinct_days >= min_distinct_days)
	if meets:
		msg = ""
	else:
		msg = (
			"**Not enough data yet**\n\n"
			f"We’re building insights from your entries. Add a few more to see trends and analysis. Insights will appear once you have:\n\n"
			f"- ≥ {min_entries} total entries\n\n"
			f"- Entries span ≥ {min_distinct_days} different days (in the last {window_days} days)\n\n"
			f"Current (last {window_days} days):\n"
			f"- {recent_entries} entries\n"
			f"- {distinct_days} distinct days"
		)
		

	return {
		"meets": bool(meets),
		"recent_entries": recent_entries,
		"distinct_days": distinct_days,
		"window_days": int(window_days),
		"min_entries": int(min_entries),
		"min_distinct_days": int(min_distinct_days),
		"message": msg,
	}

# Standard BDI symptom names (Q1-Q21)
BDI_SYMPTOM_NAMES = {
    "Q1": "Sadness",
    "Q2": "Pessimism",
    "Q3": "Past Failure",
    "Q4": "Loss of Pleasure",
    "Q5": "Guilty Feelings",
    "Q6": "Punishment Feelings",
    "Q7": "Self-Dislike",
    "Q8": "Self Criticalness",
    "Q9": "Suicidal Thoughts or Wishes",
    "Q10": "Crying",
    "Q11": "Agitation",
    "Q12": "Loss of Interest",
    "Q13": "Indecisiveness",
    "Q14": "Worthlessness",
    "Q15": "Loss of Energy",
    "Q16": "Changes in Sleeping Pattern",
    "Q17": "Irritability",
    "Q18": "Changes in Appetite",
    "Q19": "Concentration Difficulty",
    "Q20": "Tiredness or Fatigue",
    "Q21": "Loss of Interest in Sex"
}


def _ensure_datetime(series: pd.Series) -> pd.Series:
	"""Safely coerce a Series to datetime64; invalid values become NaT."""
	return pd.to_datetime(series, errors="coerce")


def _label_severity(score: float) -> str:
	"""Map average BDI score to user-facing severity labels.

	- < 10 → Minimal
	- 10–18 → Mild
	- 19–29 → Moderate
	- ≥ 30 → Severe
	"""
	if pd.isna(score):
		return "Minimal"
	if score < 10:
		return "Minimal"
	if score < 19:
		return "Mild"
	if score < 30:
		return "Moderate"
	return "Severe"


def _has_streak(values: List[bool], min_len: int) -> bool:
	"""Return True if there exists a consecutive streak of True values of length >= min_len."""
	if not values:
		return False
	run = 0
	for v in values:
		run = run + 1 if v else 0
		if run >= min_len:
			return True
	return False


def analyze_depression(df: pd.DataFrame, window_days: int = WINDOW_DAYS) -> Dict:
	"""Analyze recent entries to gently indicate likely ongoing low mood.

	Inputs
	------
	df columns (each row = one journal entry):
	  - datetime: timestamp of entry
	  - bdi_total_score: int [0–63]
	  - bdi_severity: Minimal | Mild | Moderate | Severe (not strictly required)
	  - assessment_data: dict of 21 BDI symptoms with scores [0–3]
	  - sentiment_label: Positive | Neutral | Negative (context only)

	Core Logic
	----------
	- Consider only the last `window_days` of entries for detection.
	- A single entry is considered low mood if bdi_total_score >= 10.
	- Likely depressed if, within the recent window, either:
		• At least 50% of entries have bdi_total_score >= 10
		• OR there are ≥ 5 entries in a row with bdi_total_score >= 10
	- If there are fewer than 10 valid entries overall, do not detect depression
	  (return Low confidence).

	Additional Signals (user-facing only)
	-------------------------------------
	- overall_severity: based on average of the most recent 7 entries
	- trend_direction: compare earlier half vs recent half averages (all valid entries)
	- top_symptoms: up to 3 highest-average BDI symptoms (recent window)

	Returns
	-------
	Dict with keys:
	  - depression_detected: bool
	  - overall_severity: Minimal | Mild | Moderate | Severe
	  - trend_direction: Improving | Stable | Worsening
	  - confidence_level: Low | Medium | High
	  - entries_used: int (entries in the recent window)
	  - time_span_days: int (span of recent window entries)
	  - top_symptoms: list[str] (up to 3)
	  - explanation: str (user-friendly summary)
	"""

	if df is None or df.empty:
		return {
			"depression_detected": False,
			"overall_severity": "Minimal",
			"trend_direction": "Stable",
			"confidence_level": "Low",
			"entries_used": 0,
			"time_span_days": 0,
			"top_symptoms": [],
			"explanation": "Not enough entries yet to show insights. Keep journaling to see trends over time."
		}

	# Ensure required columns exist gracefully
	required_cols = ["datetime", "bdi_total_score"]
	for col in required_cols:
		if col not in df.columns:
			raise ValueError(f"Missing required column: {col}")

	# Normalize types and sort
	work = df.copy()
	work["datetime"] = _ensure_datetime(work["datetime"])  # invalid -> NaT
	work["bdi_total_score"] = pd.to_numeric(work["bdi_total_score"], errors="coerce")
	work = work.dropna(subset=["datetime", "bdi_total_score"]).sort_values("datetime").reset_index(drop=True)

	if work.empty:
		return {
			"depression_detected": False,
			"overall_severity": "Minimal",
			"trend_direction": "Stable",
			"confidence_level": "Low",
			"entries_used": 0,
			"time_span_days": 0,
			"top_symptoms": [],
			"explanation": "Not enough entries yet to show insights. Keep journaling to see trends over time."
		}

	total_entries_overall = len(work)

	# ----------------------------
	# Recent window for detection
	# ----------------------------
	latest_dt = work["datetime"].max()
	cutoff = latest_dt - timedelta(days=window_days)
	recent = work[work["datetime"] >= cutoff].copy()
	entries_used = int(len(recent))

	if entries_used > 0:
		time_span_days = int((recent["datetime"].max() - recent["datetime"].min()).days or 0)
	else:
		time_span_days = 0

	# ----------------------------
	# Minimum data rule (overall)
	# ----------------------------
	# If fewer than 10 valid entries overall, don't detect depression.
	min_data_ok = total_entries_overall >= MIN_ENTRIES_FOR_DETECTION

	# ----------------------------
	# Pattern-based detection
	# ----------------------------
	depression_detected = False
	if min_data_ok and entries_used > 0:
		recent_scores = recent["bdi_total_score"].astype(float)
		flags = (recent_scores >= BDI_MILD_THRESHOLD).tolist()

		# Rule 1: proportion >= 50%
		proportion = (np.mean(flags) if flags else 0.0)

		# Rule 2: streak of >= STREAK_MIN
		streak = _has_streak(flags, STREAK_MIN)

		depression_detected = (proportion >= 0.5) or streak

	# ----------------------------
	# Severity from most recent 7 entries (current state)
	# ----------------------------
	last7 = work.tail(7)["bdi_total_score"].astype(float)
	avg_last7 = float(last7.mean()) if len(last7) > 0 else float("nan")
	overall_severity = _label_severity(avg_last7)

	# ----------------------------
	# Trend direction (earlier half vs recent half) using all valid entries
	# ----------------------------
	trend_direction = "Stable"
	n = len(work)
	if n >= 4:  # need some data to compare halves
		mid = n // 2
		early_avg = float(work.iloc[:mid]["bdi_total_score"].mean())
		recent_avg = float(work.iloc[mid:]["bdi_total_score"].mean())

		# Use a small tolerance to avoid overreacting to tiny differences
		tol = 0.5
		if recent_avg + tol < early_avg:
			trend_direction = "Improving"
		elif recent_avg > early_avg + tol:
			trend_direction = "Worsening"
		else:
			trend_direction = "Stable"

	# ----------------------------
	# Top symptoms (recent window, reflection only)
	# ----------------------------
	top_symptoms: List[str] = []
	if "assessment_data" in recent.columns and not recent.empty:
		totals: Dict[str, float] = {}
		counts: Dict[str, int] = {}
		for _, row in recent.iterrows():
			assess = row.get("assessment_data", {})
			if isinstance(assess, dict) and assess:
				for name, val in assess.items():
					if isinstance(val, dict):
						# Try to get score from 'level' or 'score'
						score_key = "level" if "level" in val else ("score" if "score" in val else None)
						if score_key:
							score = float(val[score_key])
							if 0 <= score <= 3:
								# Use standard BDI name if available, else symptom text, else key
								symptom_name = BDI_SYMPTOM_NAMES.get(name, val.get("symptom", name.replace("_", " ").title()))
								totals[symptom_name] = totals.get(symptom_name, 0.0) + score
								counts[symptom_name] = counts.get(symptom_name, 0) + 1
					elif isinstance(val, (int, float)):
						score = float(val)
						if 0 <= score <= 3:
							symptom_name = BDI_SYMPTOM_NAMES.get(name, name.replace("_", " ").title())
							totals[symptom_name] = totals.get(symptom_name, 0.0) + score
							counts[symptom_name] = counts.get(symptom_name, 0) + 1

		if totals:
			avgs = {k: (totals[k] / counts[k]) for k in totals if counts.get(k, 0) > 0}
			if avgs:
				# Top 3 by average
				top_symptoms = [
					name for name, _ in sorted(avgs.items(), key=lambda kv: kv[1], reverse=True)[:3]
				]

	# ----------------------------
	# Confidence level (simple and transparent)
	# ----------------------------
	if total_entries_overall < MIN_ENTRIES_FOR_DETECTION:
		confidence = "Low"
	elif total_entries_overall < 20:
		confidence = "Medium"
	else:
		confidence = "High"

	# ----------------------------
	# User-facing explanation
	# ----------------------------
	if not min_data_ok:
		explanation = (
			"You have a limited number of entries so far. We'll show gentle insights, "
			"but more entries will make them clearer. This is not a diagnosis."
		)
	elif depression_detected:
		explanation = (
			"Your recent entries suggest consistent low mood over the last few weeks. "
			"Consider checking in with someone you trust or a professional. This is not a diagnosis."
		)
	else:
		explanation = (
			"Your recent entries do not show a consistent pattern of low mood. "
			"It's normal to have ups and downs. This is not a diagnosis."
		)

	return {
		"depression_detected": bool(depression_detected),
		"overall_severity": overall_severity,
		"trend_direction": trend_direction,
		"confidence_level": confidence,
		"entries_used": int(entries_used),
		"time_span_days": int(time_span_days),
		"top_symptoms": top_symptoms,
		"explanation": explanation,
	}


def prepare_dashboard_data(db_client, window_days: int = 90) -> Optional[pd.DataFrame]:
	"""Fetch and prepare entries from Supabase for the dashboard and analysis.

	Notes
	-----
	- Keeps `bdi_severity` in Minimal/Mild/Moderate/Severe when possible.
	- Falls back to deriving severity from `bdi_total_score` if needed.
	- Uses sentiment as supporting context only.
	"""

	try:
		entries = db_client.get_recent_entries(days=window_days, limit=1000)
		if not entries:
			return None

		rows = []
		for entry in entries:
			entry_id = entry.get("id")
			if not entry_id:
				continue

			assessment = db_client.get_assessment_by_entry(entry_id)
			if not assessment:
				# Skip if no completed BDI assessment
				continue

			sentiment = db_client.get_sentiment_by_entry(entry_id)

			# Parse datetime: try explicit fields, then fall back to any timestamp field
			dt: Optional[datetime] = None
			date_str = entry.get("date")
			time_str = entry.get("time", "00:00:00")
			if date_str:
				dt = pd.to_datetime(f"{date_str} {time_str}", errors="coerce")
			if pd.isna(dt) or dt is None:
				# try a more generic field
				dt = pd.to_datetime(entry.get("datetime"), errors="coerce")
			if pd.isna(dt) or dt is None:
				# cannot use this entry without a valid timestamp
				continue

			# BDI totals and severity
			total = assessment.get("total_score", 0)
			try:
				total = int(total)
			except Exception:
				total = 0

			raw_sev = str(assessment.get("category", "")).strip()
			raw_sev_up = raw_sev.title()

			if raw_sev_up in {"Minimal", "Mild", "Moderate", "Severe"}:
				sev = raw_sev_up
			elif raw_sev_up in {"No", "None"}:
				sev = "Minimal"
			else:
				sev = _label_severity(total)

			# Sentiment (context only)
			sentiment_label = "Neutral"
			if sentiment:
				lbl = sentiment.get("top_label")
				if isinstance(lbl, str) and lbl in {"Positive", "Neutral", "Negative"}:
					sentiment_label = lbl

			rows.append(
				{
					"datetime": dt,
					"bdi_total_score": total,
					"bdi_severity": sev,
					"assessment_data": assessment.get("assessment_data", {}),
					"sentiment_label": sentiment_label,
					# keep a bit of text context if available
					"text": entry.get("text", ""),
				}
			)

		if not rows:
			return None

		out = pd.DataFrame(rows)
		out = out.sort_values("datetime").reset_index(drop=True)
		return out

	except Exception as exc:
		# In production, consider logging this with more context
		print(f"Error preparing dashboard data: {exc}")
		return None

