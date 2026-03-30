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

# ===== UI =====
st.markdown("""
<style>
.stApp {
    background: linear-gradient(135deg, #f5f7fa, #e4ecf3);
}
</style>
""", unsafe_allow_html=True)

col1, col2 = st.columns([1, 5])

with col1:
    st.image("logo.png", width=100)

with col2:
    st.markdown(
        "<h1 style='margin-bottom:0;'>XDAS Release Notes</h1>",
        unsafe_allow_html=True
    )

st.markdown("<br>", unsafe_allow_html=True)

# ===== HELPERS =====

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


# ===== CORE =====

def generate_release_notes(cleaned_stories):

    combined_input = ""
    project_list = []

    for project, stories in cleaned_stories.items():
        display_name = map_project_name(project)
        project_list.append(display_name)

        for story in stories:
            combined_input += f"\n- {story['title']}: {story['ac']}"

        combined_input += "\n\n"

    project_string = ", ".join(project_list)

    prompt = f"""
You are a Product Marketing Manager writing high-quality release notes for the XDAS platform.

----------------------------------------

**INTRODUCTION**

We are excited to introduce the latest XDAS platform release, bringing focused enhancements across the following modules: {project_string}.

----------------------------------------

PROJECT SUMMARIES:

After the introduction, write 2–3 lines for EACH project summarizing updates.

- Mention ALL projects
- Use natural language
- Do NOT repeat same verbs

----------------------------------------

FEATURE GROUPING (VERY IMPORTANT):

- Combine multiple related user stories into a single feature
- DO NOT create one feature per story
- Group similar capabilities together

Examples:
- different functionalities but referencing same feature → one feature
- Security fixes → one feature

- Aim for 3–6 features per project

----------------------------------------

STRUCTURE:

**<Project Name>**

**<Feature Name>**

<Description>

----------------------------------------

RULES:

- Bold ALL headings
- Always add spacing
- No questions
- No AI endings
 - Do not include any stories mentioned as regression testing, ATS
- End cleanly after last feature

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
        leading=16,
        alignment=TA_JUSTIFY
    )

    bold_style = ParagraphStyle(
        'Bold',
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=18
    )

    content = []

    for line in release_notes.split("\n"):
        line = line.strip()

        if not line:
            content.append(Spacer(1, 8))
            continue

        if line.startswith("**") and line.endswith("**"):
            clean_line = line.replace("**", "")
            content.append(Paragraph(clean_line, bold_style))
        else:
            content.append(Paragraph(line, normal_style))

        content.append(Spacer(1, 6))

    doc.build(content)


# ===== INPUT =====

sprint = st.text_input("Sprint (e.g., 62)")
projects = st.text_input("Projects (comma separated)")

# ===== ACTION =====

if st.button("Generate Release Notes"):

    if not sprint or not projects:
        st.warning("Please enter both Sprint and Projects")
        st.stop()

    ITERATIONS = [f"NS-{sprint}", f"NS {sprint}"]
    PROJECTS = [p.strip() for p in projects.split(",")]

    with st.spinner("🔄 Fetching data..."):
        all_stories = {}

        for project in PROJECTS:
            ids = get_work_item_ids(project, ITERATIONS)
            details = get_work_item_details(ids)

            all_stories[project] = []

            for item in details:
                fields = item.get("fields", {})
                all_stories[project].append({
                    "title": fields.get("System.Title", ""),
                    "ac": fields.get("Microsoft.VSTS.Common.AcceptanceCriteria", "")
                })

    with st.spinner("🧹 Cleaning data..."):
        cleaned_stories = {}

        for project, stories in all_stories.items():
            cleaned_stories[project] = []

            for story in stories:
                cleaned_stories[project].append({
                    "title": story["title"],
                    "ac": clean_html(story["ac"])
                })

    with st.spinner("🤖 Generating release notes..."):
        release_notes = generate_release_notes(cleaned_stories)

    with st.spinner("📄 Creating PDF..."):
        create_pdf(release_notes)

    st.success("✅ Release notes generated")

    st.subheader("Release Notes")
    st.markdown(release_notes)

    with open("Release_Notes.pdf", "rb") as f:
        st.download_button("Download PDF", f, file_name="Release_Notes.pdf")
