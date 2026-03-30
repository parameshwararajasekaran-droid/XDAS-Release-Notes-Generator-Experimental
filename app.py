import streamlit as st
import requests
from requests.auth import HTTPBasicAuth
import re
from html import unescape
from openai import OpenAI
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import letter
from reportlab.lib.enums import TA_JUSTIFY

# ===== CONFIG =====
ORG = "techmobius"
PAT = st.secrets["AZURE_PAT"]
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# ===== PROJECT NAME MAPPING =====
PROJECT_NAME_MAPPING = {
    "workxtream development": "Manage Workflow"
}

# ===== BACKGROUND =====
st.markdown("""
<style>
.stApp {
    background: linear-gradient(135deg, #f5f7fa, #e4ecf3);
}
</style>
""", unsafe_allow_html=True)

# ===== HEADER =====
col1, col2 = st.columns([1, 5])

with col1:
    st.image("logo.png", width=100)

with col2:
    st.markdown(
        "<h1 style='margin-bottom:0; font-size:28px;'>XDAS Release Notes</h1>",
        unsafe_allow_html=True
    )

st.markdown("<br>", unsafe_allow_html=True)

# ===== FUNCTIONS =====

def clean_html(raw_html):
    if not raw_html:
        return ""
    clean = re.sub('<.*?>', ' ', raw_html)
    clean = unescape(clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def map_project_name(project):
    return PROJECT_NAME_MAPPING.get(project.lower(), project)


def get_iterations(project, ITERATIONS):
    url = f"https://dev.azure.com/{ORG}/{project}/_apis/work/teamsettings/iterations?api-version=7.0"
    response = requests.get(url, auth=HTTPBasicAuth('', PAT))
    data = response.json()

    iterations = []
    for it in data.get("value", []):
        name = it.get("name", "")
        if any(iter_name in name for iter_name in ITERATIONS):
            iterations.append(it.get("path"))

    return iterations


def get_work_item_ids(project, ITERATIONS):
    url = f"https://dev.azure.com/{ORG}/{project}/_apis/wit/wiql?api-version=7.0"

    iteration_paths = get_iterations(project, ITERATIONS)

    if not iteration_paths:
        return []

    iteration_filter = " OR ".join([
        f"[System.IterationPath] UNDER '{it}'" for it in iteration_paths
    ])

    query = {
        "query": f"""
        SELECT [System.Id]
        FROM WorkItems
        WHERE
            [System.WorkItemType] = 'User Story'
            AND [System.State] = 'Closed'
            AND ({iteration_filter})
        """
    }

    response = requests.post(url, json=query, auth=HTTPBasicAuth('', PAT))
    return [item["id"] for item in response.json().get("workItems", [])]


def get_work_item_details(ids):
    if not ids:
        return []

    ids_str = ",".join(map(str, ids))
    url = f"https://dev.azure.com/{ORG}/_apis/wit/workitems?ids={ids_str}&api-version=7.0"

    response = requests.get(url, auth=HTTPBasicAuth('', PAT))
    return response.json().get("value", [])


def generate_release_notes(cleaned_stories):

    combined_input = ""
    project_list = []

    for project, stories in cleaned_stories.items():
        display_name = map_project_name(project)
        project_list.append(display_name)
        combined_input += f"\nPROJECT: {display_name}\n{stories}\n"

    project_string = ", ".join(project_list)

    prompt = f"""
You are a Product Marketing Manager writing high-quality release notes for the XDAS platform.

GOAL:
Generate clean, professional, user-friendly release notes.

----------------------------------------

STRICT FORMAT (MUST FOLLOW EXACTLY):

**INTRODUCTION**

<blank line>

We are excited to introduce the latest XDAS platform release, bringing focused enhancements across ALL the following projects: {project_string}.

IMPORTANT:
- You MUST include every project listed above
- Do NOT omit any project
- Do NOT rename any project except:
  - "workxtream development" MUST be written as "Manage Workflow"

<blank line>

<Project summaries>

----------------------------------------

PROJECT STRUCTURE:

Each project MUST be formatted as:

**<Project Name>**

<blank line>

**<Feature Name>**

<blank line>

<Feature explanation paragraph>

----------------------------------------

STRICT RULES:

- ALWAYS bold:
  - INTRODUCTION
  - Project names
  - Feature names

- NEVER write content on same line as headings
- ALWAYS leave one blank line after headings

- DO NOT include:
  ❌ Questions
  ❌ Suggestions
  ❌ "Would you like me to..."
  ❌ Any closing remarks

- End output immediately after last feature

----------------------------------------

FEATURE GUIDELINES:

- 4–6 lines per feature
- Clear, concise, product-focused

----------------------------------------

FILTER OUT:

- QA
- Testing
- Regression
- Acceptance criteria

----------------------------------------

INPUT:
{combined_input}
"""

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content


def create_pdf(release_notes):

    doc = SimpleDocTemplate("Release_Notes.pdf", pagesize=letter)

    normal_style = ParagraphStyle(
        'Normal',
        fontName='Helvetica',
        fontSize=11,
        leading=17,
        alignment=TA_JUSTIFY
    )

    content = []

    for line in release_notes.split("\n"):
        if line.strip():
            content.append(Paragraph(line, normal_style))
            content.append(Spacer(1, 6))

    doc.build(content)


# ===== INPUT =====

sprint = st.text_input("Sprint (e.g., 62)")
projects = st.text_input("Projects (comma separated)")


# ===== BUTTON =====

if st.button("Generate Release Notes"):

    if not sprint or not projects:
        st.warning("Please enter both Sprint and Projects")
        st.stop()

    ITERATIONS = [f"NS-{sprint}", f"NS {sprint}"]
    PROJECTS = [p.strip() for p in projects.split(",")]

    with st.spinner("🔄 Fetching latest updates..."):
        all_stories = {}

        for project in PROJECTS:
            ids = get_work_item_ids(project, ITERATIONS)
            details = get_work_item_details(ids)

            all_stories[project] = []

            for item in details:
                fields = item.get("fields", {})
                title = fields.get("System.Title", "")
                ac = fields.get("Microsoft.VSTS.Common.AcceptanceCriteria", "")

                all_stories[project].append({
                    "title": title,
                    "ac": ac
                })

    with st.spinner("🧹 Organizing release data..."):
        cleaned_stories = {}

        for project, stories in all_stories.items():
            cleaned_stories[project] = []

            for story in stories:
                cleaned_stories[project].append({
                    "title": story["title"],
                    "ac": clean_html(story["ac"])
                })

    with st.spinner("🤖 Crafting release notes..."):
        release_notes = generate_release_notes(cleaned_stories)

    with st.spinner("📄 Preparing your document..."):
        create_pdf(release_notes)

    st.success("✅ Release notes generated")

    st.subheader("Release Notes")
    st.markdown(release_notes)

    with open("Release_Notes.pdf", "rb") as f:
        st.download_button("Download PDF", f, file_name="Release_Notes.pdf")
