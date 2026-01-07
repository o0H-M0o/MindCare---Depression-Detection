"""
Prompt templates and BDI question rephrasing for mental health assessment
"""

# Rephrased BDI-II questions for social media text analysis
REPHRASED_BDI = {
    "Q1": "how sad the user feels",
    "Q2": "how discouraged the user is about future",
    "Q3": "how much the user feels like a failure",
    "Q4": "how much the user loses pleasure from things",
    "Q5": "how often the user feels guilty",
    "Q6": "how much the user feels punished",
    "Q7": "how much the user feels disappointed about him/herself",
    "Q8": "how often the user criticizes or blames him/herself",
    "Q9": "how much the user thinks about killing him/herself",
    "Q10": "how often the user cries",
    "Q11": "how much the user feels restless or agitated",
    "Q12": "how much the user loses interest in things",
    "Q13": "how difficult the user to make decisions",
    "Q14": "how much the user feels worthless",
    "Q15": "how much the user loses energy",
    "Q16": "how much the user experienced changes in sleeping",
    "Q17": "how much the user feels irritable",
    "Q18": "how much the user experienced changes in appetite",
    "Q19": "how difficult the user to concentrate",
    "Q20": "how much the user feels tired or fatigued",
    "Q21": "how much the user loses interest in sex"
}

def build_assessment_prompt(symptom: str, texts: list) -> str:
    """
    Build a prompt for LLM to assess depression level based on user's text
    
    Args:
        symptom: The specific BDI symptom to assess
        texts: List of user's journal entries or social media posts
        
    Returns:
        Formatted prompt string
    """
    # Combine texts into a single paragraph
    combined_text = " ".join(texts)
    
    prompt = f"""You are a psychiatrist who prefers to give minor diagnoses rather than serious ones. The following paragraph was concatenated from a user's journal entries or social media posts. Read the posts as a whole, determine the level of "{symptom}" and give a number in 0, 1, 2, or 3.

Respond strictly in the following format:
LEVEL: <number>
REASON: <short explanation>

User's text:
{combined_text}"""
    
    return prompt

# def build_batch_assessment_prompt(texts: list) -> str:
    
#     combined_text = " ".join(texts)

#     symptoms_list = "\n".join([f"{i+1}. {symptom}" for i, symptom in enumerate(REPHRASED_BDI.values())])

#     prompt = f"""
# You are a clinical assessor trained to evaluate depression symptoms using the Beck Depression Inventory (BDI). 
# Your task is to assess **all 21 symptoms** based ONLY on the information explicitly stated in the user's text. 
# Do NOT assume, infer, or guess anything that is not clearly supported by the text.

# -----------------------------
# ### IMPORTANT SCORING RULES
# For each symptom, assign a score from 0 to 3:
# - **0** = No evidence of the symptom  
# - **1** = Mild indication  
# - **2** = Moderate indication  
# - **3** = Strong, clear, or persistent indication  

# If the text does NOT provide enough evidence for a symptom, ALWAYS assign **0**.

# -----------------------------
# ### Symptoms to assess
# {symptoms_list}

# -----------------------------
# ### OUTPUT INSTRUCTIONS
# You MUST respond in *exactly* the following format:

# Q1_LEVEL: <0/1/2/3>
# Q1_REASON: <1–2 sentences, citing the specific text evidence or stating “no evidence in the text”>

# Q2_LEVEL: <0/1/2/3>
# Q2_REASON: <explanation>

# ...

# Q21_LEVEL: <0/1/2/3>
# Q21_REASON: <explanation>

# Do NOT add any additional text, disclaimers, comments, or formatting.

# -----------------------------
# ### USER TEXT (COMBINED ENTRIES)
# {combined_text}
# """
#     return prompt

def build_batch_assessment_prompt(texts: list) -> str:
    """
    Build a prompt for LLM to assess all 21 BDI symptoms in one request
    
    Args:
        texts: List of user's journal entries or social media posts
        
    Returns:
        Formatted prompt string for batch assessment
    """
    # Combine texts into a single paragraph
    combined_text = " ".join(texts)
    
    # Create numbered list of symptoms
    symptoms_list = "\n".join([f"{i+1}. {symptom}" for i, symptom in enumerate(REPHRASED_BDI.values())])
    
    #If the text does NOT provide clear evidence for a symptom, ALWAYS assign 0.
    prompt = f"""You are a psychiatrist who diagnoses depression. The following paragraph was concatenated from a user's journal entries. Read the posts and assess ALL 21 symptoms listed below.For each symptom, determine the level (0, 1, 2, or 3) based on the user's text only and explain why.

Symptoms to assess:
{symptoms_list}

Respond strictly in the following format for EACH symptom:
Q1_LEVEL: <0/1/2/3>
Q1_REASON: <explanation>
Q2_LEVEL: <0/1/2/3>
Q2_REASON: <explanation>
...
Q21_LEVEL: <0/1/2/3>
Q21_REASON: <explanation>
User's text:
{combined_text}"""
    
    return prompt


def build_messages(symptom: str, texts: list) -> list:
    """
    Build message structure for Gemini API (individual symptom assessment)
    
    Args:
        symptom: The specific BDI symptom to assess
        texts: List of user's journal entries
        
    Returns:
        List of message dictionaries
    """
    user_prompt = build_assessment_prompt(symptom, texts)
    
    messages = [
        {"role": "user", "parts": [user_prompt]}
    ]
    
    return messages


def build_batch_messages(texts: list) -> list:
    """
    Build message structure for Gemini API batch assessment
    
    Args:
        texts: List of user's journal entries
        
    Returns:
        List of message dictionaries
    """
    user_prompt = build_batch_assessment_prompt(texts)
    
    messages = [
        {"role": "user", "parts": [user_prompt]}
    ]
    
    return messages


def build_support_recommendation_prompt(
    *,
    symptoms_json: str,
    overall_severity: str,
    trend_direction: str,
) -> str:
    """Build a non-diagnostic support recommendation prompt for institution staff.

    The input symptoms_json should be a JSON array of objects with:
    - symptom: str
    - average_score: float (0-3)
    - entries_count: int
    """
    return (
        "You are assisting an institution staff member/support person reviewing an individual's well-being trends. "
        "Based on the individual's top BDI-related symptoms (with average severity scores 0-3) and recent trend, "
        "write a short, practical recommendation for supportive follow-up.\n\n"
        "Constraints:\n"
        "- Do NOT diagnose or label the individual.\n"
        "- Be calm, trauma-informed, and respectful.\n"
        "- Do NOT request or include any personal identifying details.\n"
        "- Focus on actionable next steps the staff/support person can take.\n"
        "- If the symptoms include suicidal thoughts/wishes, include urgent safety guidance (encourage immediate professional help and emergency services if there is imminent risk).\n\n"
        f"Context:\n- Overall severity: {overall_severity}\n- Trend: {trend_direction}\n\n"
        "Top symptoms (JSON array of objects with symptom, average_score, entries_count):\n"
        f"{symptoms_json}\n\n"
        "Output format:\n"
        "- Title line (1 sentence)\n"
        "- 4-6 bullet points with concrete actions\n"
        "- One short closing disclaimer about seeking professional help\n"
    )


def build_self_support_recommendation_prompt(
    *,
    symptoms_json: str,
    overall_severity: str,
    trend_direction: str,
) -> str:
    """Build a non-diagnostic self-support prompt for the individual user.

    The input symptoms_json should be a JSON array of objects with:
    - symptom: str
    - average_score: float (0-3)
    - entries_count: int
    """
    return (
        "You are a supportive mental health assistant writing for the individual user (the person who wrote the journal entries). "
        "Based on their top BDI-related symptoms (with average severity scores 0-3) and recent trend, "
        "write a short, practical set of self-support suggestions tailored to them.\n\n"
        "Safety + constraints (must follow):\n"
        "- Do NOT diagnose, label, or claim certainty.\n"
        "- Do NOT give medical advice (no medication changes, no treatment plans).\n"
        "- Be calm, supportive, and non-judgmental.\n"
        "- Avoid mentioning private details; only reference the provided symptom summary.\n"
        "- Provide coping steps the user can try today (small, realistic actions).\n"
        "- If the symptoms include suicidal thoughts/wishes, include urgent safety guidance: encourage reaching out immediately to local emergency services or a trusted person and professional help.\n\n"
        f"Context:\n- Overall severity: {overall_severity}\n- Trend: {trend_direction}\n\n"
        "Top symptoms (JSON array of objects with symptom, average_score, entries_count):\n"
        f"{symptoms_json}\n\n"
        "Output format:\n"
        "- Title line (1 sentence, addressed to 'you')\n"
        "- 4-6 bullet points (actionable self-care + help-seeking steps)\n"
        "- One short closing disclaimer: this is not a diagnosis and professional support can help\n"
    )
